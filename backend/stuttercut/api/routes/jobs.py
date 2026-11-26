"""Job routes for the Upload & jobs and Review screens (design doc "API design")."""

import asyncio
import json
import shutil
import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stuttercut.api import jobs_view
from stuttercut.config import RENDER_FORMATS, Config
from stuttercut.media.audio import MediaError
from stuttercut.media.render import video_info
from stuttercut.rules import REASONS
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect

router = APIRouter(prefix="/api/jobs")


@contextmanager
def db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(paths.db_path(request.app.state.cfg))
    try:
        yield conn
    finally:
        conn.close()


def _job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return job


class Options(BaseModel):
    """Detection options from the upload form; a reason switched off is not suggested."""

    model_config = ConfigDict(extra="forbid")
    filler: bool = True
    repeat: bool = True
    pause: bool = True
    retake: bool = True  # also the LLM review
    pause_min_ms: int | None = Field(None, ge=100, le=5000)


def _mmss(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _check_video(path: Path, cfg: Config) -> float:
    """ffprobe only (no decode): length, a video and an audio stream. Raises HTTP 422."""
    try:
        info = video_info(path)
    except MediaError:
        raise HTTPException(422, f"{path.name} is not a video we can read.") from None
    if not info.has_audio:
        raise HTTPException(422, f"{path.name} has no sound. Choose a video with a voice track.")
    if info.duration_s > cfg.media.max_duration_s:
        limit = round(cfg.media.max_duration_s / 60)
        raise HTTPException(
            422,
            f"{path.name} is {_mmss(info.duration_s)} long. "
            f"Choose a video of {limit} minutes or less.",
        )
    return info.duration_s


@router.post("", status_code=201)
async def create_job(request: Request, name: str, options: str | None = None) -> dict[str, Any]:
    """Body = the video file itself (no multipart); ``name`` = its file name."""
    cfg: Config = request.app.state.cfg
    filename = Path(name).name.strip()
    if not filename or filename in (".", ".."):
        raise HTTPException(422, "The file needs a name.")
    try:
        opts = Options.model_validate_json(options or "{}")
    except ValidationError as e:
        raise HTTPException(422, f"Invalid detection options: {e.errors()[0]['msg']}") from None
    job_id = uuid.uuid4().hex[:12]
    folder = paths.data_dir(cfg) / "uploads" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    limit, size = cfg.media.max_upload_mb * 2**20, 0
    try:
        with target.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"{filename} is over {cfg.media.max_upload_mb} MB.")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, f"{filename} is empty.")
        await run_in_threadpool(_check_video, target, cfg)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # no job, no file left behind
        raise
    with db(request) as conn:
        repo.create_job(conn, str(target), opts.model_dump_json(exclude_none=True), job_id)
        request.app.state.worker.put(("process", job_id))
        return jobs_view.summary(conn, _job(conn, job_id), cfg)


@router.get("")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    with db(request) as conn:
        return [jobs_view.summary(conn, j, cfg) for j in repo.list_jobs(conn)]


@router.get("/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    with db(request) as conn:
        return jobs_view.detail(conn, _job(conn, job_id), request.app.state.cfg)


@router.get("/{job_id}/preview")
def preview(request: Request, job_id: str) -> FileResponse:
    """The 480p proxy; FileResponse answers HTTP Range requests (seeking)."""
    with db(request) as conn:
        _job(conn, job_id)
    path = paths.data_dir(request.app.state.cfg) / "jobs" / job_id / "preview.mp4"
    if not path.is_file():
        raise HTTPException(404, "no preview yet")
    return FileResponse(path, media_type="video/mp4")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kept: bool


@router.patch("/{job_id}/cuts/{cut_id}")
def decide_one(request: Request, job_id: str, cut_id: int, body: Decision) -> dict[str, Any]:
    """Keep (not cut) or cut one segment; saved at once with a timestamp."""
    with db(request) as conn:
        job = _job(conn, job_id)
        if repo.decide(conn, job_id, [cut_id], keep=body.kept) == 0:
            raise HTTPException(404, f"no cut {cut_id} in job {job_id}")
        return {"saved_s": jobs_view.saved_s(conn, job, request.app.state.cfg)}


class Bulk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve_sure", "cut_all", "keep_all"]


@router.post("/{job_id}/cuts:bulk")
def decide_many(request: Request, job_id: str, body: Bulk) -> dict[str, Any]:
    """approve_sure = cut every sure-tier suggestion; cut_all / keep_all = every suggestion.
    Cuts marked by hand stay as they are."""
    with db(request) as conn:
        job = _job(conn, job_id)
        cuts = [c for c in repo.get_cuts(conn, job_id) if c["source"] != "user"]
        if body.action == "approve_sure":
            cuts = [c for c in cuts if c["tier"] == "sure"]
        changed = repo.decide(conn, job_id, [c["id"] for c in cuts], keep=body.action == "keep_all")
        return {"changed": changed, "saved_s": jobs_view.saved_s(conn, job, request.app.state.cfg)}


class MissedCut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_s: float = Field(ge=0)
    end_s: float
    reason: str


@router.post("/{job_id}/cuts", status_code=201)
def add_cut(request: Request, job_id: str, body: MissedCut) -> dict[str, Any]:
    """A cut the detector missed ("Mark missed cut" on a transcript selection)."""
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {REASONS}")
    with db(request) as conn:
        job = _job(conn, job_id)
        if not body.end_s > body.start_s or body.end_s > (job["duration_s"] or 0) + 0.01:
            raise HTTPException(422, "the cut must have end > start and lie inside the clip")
        cut_id = repo.add_user_cut(conn, job_id, body.start_s, body.end_s, body.reason)
        return {"id": cut_id, "saved_s": jobs_view.saved_s(conn, job, request.app.state.cfg)}


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = "mp4"
    folder: str | None = None  # None = STUTTERCUT_OUTPUT_DIR / the Videos folder


@router.post("/{job_id}/render", status_code=202)
def render(request: Request, job_id: str, body: RenderRequest) -> dict[str, Any]:
    if body.format not in RENDER_FORMATS:
        raise HTTPException(422, f"format must be one of {RENDER_FORMATS}")
    folder = str(Path(body.folder).expanduser()) if body.folder else ""
    if folder and not Path(folder).is_absolute():
        raise HTTPException(422, "Save to needs a full folder path.")
    with db(request) as conn:
        job = _job(conn, job_id)
        retry = job["status"] == "failed" and job["failed_step"] == "render"
        if job["status"] not in ("ready_for_review", "done") and not retry:
            raise HTTPException(409, f"job is {job['status']}; it cannot be rendered now")
        opts = {**json.loads(job["options"] or "{}"),
                "render": {"format": body.format, "folder": folder}}  # fmt: skip
        with conn:
            conn.execute("UPDATE job SET options = ? WHERE id = ?", (json.dumps(opts), job_id))
        repo.set_status(conn, job_id, "rendering")
        request.app.state.worker.put(("render", job_id, body.format, folder))
        return jobs_view.summary(conn, _job(conn, job_id), request.app.state.cfg)


@router.post("/{job_id}/retry", status_code=202)
def retry(request: Request, job_id: str) -> dict[str, Any]:
    """Re-run from the failed step; reviewed cuts are kept."""
    with db(request) as conn:
        job = _job(conn, job_id)
        if job["status"] != "failed":
            raise HTTPException(409, f"job is {job['status']}; only a failed job can be retried")
        failed_step = job["failed_step"]
        repo.set_status(conn, job_id, "rendering" if failed_step == "render" else "queued")
        with conn:  # keep failed_step for the worker to know where to resume
            conn.execute("UPDATE job SET failed_step = ? WHERE id = ?", (failed_step, job_id))
        request.app.state.worker.put(("retry", job_id))
        return jobs_view.summary(conn, _job(conn, job_id), request.app.state.cfg)


@router.post("/{job_id}/reveal", status_code=204)
def reveal(request: Request, job_id: str) -> None:
    """Show the rendered file (or the source) in Finder / Explorer."""
    with db(request) as conn:
        job = _job(conn, job_id)
    path = Path(job["output_path"] or job["xml_path"] or job["source_path"])
    if not path.exists():
        raise HTTPException(404, f"{path.name} is no longer there")
    request.app.state.reveal(path)


def _event(kind: str, data: dict[str, Any]) -> str:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


async def _events(request: Request, job_id: str, interval_s: float) -> AsyncIterator[str]:
    """Poll the DB the worker writes; emit what changed. Ends after ready / done / failed."""
    cfg = request.app.state.cfg
    step, spans_sent = None, 0
    while not await request.is_disconnected():
        with db(request) as conn:
            job = _job(conn, job_id)
            spans = repo.get_spans(conn, job_id)
            row = jobs_view.summary(conn, job, cfg)
        for s in spans[spans_sent:]:
            yield _event("step_done", {"step": s["step"], "duration_s": s["duration_s"],
                                       "status": s["status"]})  # fmt: skip
        spans_sent = len(spans)
        if job["step"] and job["step"] != step:
            yield _event("step_started", {"step": job["step"], "label": row["step_label"]})
        step = job["step"]
        if step:
            yield _event("progress", {"step": step, "label": row["step_label"],
                                      "percent": row["progress"]})  # fmt: skip
        if job["status"] in jobs_view.TERMINAL:
            kind = {"ready_for_review": "ready", "done": "done"}.get(job["status"], "failed")
            yield _event(kind, row)
            return
        await asyncio.sleep(interval_s)


@router.get("/{job_id}/events")
def events(request: Request, job_id: str) -> StreamingResponse:
    """SSE: step_started, progress, step_done, then ready | done | failed (stream ends)."""
    with db(request) as conn:
        _job(conn, job_id)
    return StreamingResponse(
        _events(request, job_id, request.app.state.sse_interval_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
