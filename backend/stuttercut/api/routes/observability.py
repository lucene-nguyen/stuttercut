"""Metrics, traces, logs and the diagnostics export (design doc "API design", LEARNING-228)."""

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from stuttercut.api.routes.jobs import db
from stuttercut.observability import diagnostics
from stuttercut.storage import paths

router = APIRouter(prefix="/api")
ui_log = logging.getLogger("stuttercut.ui")


@router.get("/metrics")
def get_metrics(request: Request, days: int = 7) -> dict[str, Any]:
    with db(request) as conn:
        return diagnostics.metrics(conn, days)


@router.get("/jobs/{job_id}/trace")
def get_trace(request: Request, job_id: str) -> dict[str, Any]:
    with db(request) as conn:
        cfg = request.app.state.cfg
        found = diagnostics.trace(conn, job_id, paths.log_dir(cfg),
                                  paths.data_dir(cfg) / "jobs" / job_id)  # fmt: skip
    if found is None:
        raise HTTPException(404, f"no job {job_id}")
    return found


@router.get("/logs")
def get_logs(
    request: Request, level: str | None = None, job: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    try:
        return diagnostics.read_logs(paths.log_dir(request.app.state.cfg), level, job,
                                     max(1, min(limit, 1000)))  # fmt: skip
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


class UiError(BaseModel):
    """An error the React Error Boundary caught. Sizes are capped: it is a log line."""

    model_config = ConfigDict(extra="forbid")
    level: Literal["ERROR", "WARN"] = "ERROR"
    message: str = Field(max_length=2000)
    stack: str | None = Field(None, max_length=8000)
    component_stack: str | None = Field(None, max_length=8000)
    url: str | None = Field(None, max_length=500)


@router.post("/logs", status_code=204)
def post_log(body: UiError) -> None:
    ui_log.log(logging.ERROR if body.level == "ERROR" else logging.WARNING, body.message,
               extra={"source": "ui", "stack": body.stack,
                      "component_stack": body.component_stack, "url": body.url})  # fmt: skip


@router.get("/diagnostics/environment")
def get_environment(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    return {**diagnostics.environment(cfg), "log_dir": str(paths.log_dir(cfg))}


@router.post("/logs/open-folder", status_code=204)
def open_log_folder(request: Request) -> None:
    """ "Open log folder" on the Diagnostics screen: Finder / Explorer at the log folder."""
    folder = paths.log_dir(request.app.state.cfg)
    folder.mkdir(parents=True, exist_ok=True)
    request.app.state.open_folder(folder)


@router.post("/diagnostics/export")
async def export(request: Request) -> Response:
    """A zip of logs + environment + metrics + traces; no transcripts, media or database."""
    cfg = request.app.state.cfg

    def build() -> bytes:
        with db(request) as conn:
            return diagnostics.export_zip(conn, cfg, paths.log_dir(cfg))

    data = await run_in_threadpool(build)
    name = f"stuttercut-diagnostics-{date.today().isoformat()}.zip"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip
