"""API contract: metrics, traces, logs, UI error reports and the diagnostics export."""

import io
import json
import logging
import zipfile
from collections.abc import Callable
from pathlib import Path

from stuttercut.config import Config
from stuttercut.storage import paths, repo
from tests.contract.conftest import Api, db, upload


def test_metrics_cover_jobs_steps_and_failures(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    assert client.get("/api/metrics").json()["jobs"] == 0
    ok = upload(client, make_video("một.mp4", seconds=10.0)).json()["id"]
    bad = upload(client, make_video("hai.mp4", seconds=10.0)).json()["id"]
    repo.set_status(db(cfg), bad, "failed", failed_step="render", error="FFmpegError: x")

    m = client.get("/api/metrics").json()
    assert m["jobs"] == 2 and m["by_status"] == {"ready_for_review": 1, "failed": 1}
    assert m["success_rate"] == 0.5 and m["failures_by_step"] == {"render": 1}
    assert {"extract_audio", "preview", "transcribe", "detect"} <= set(m["avg_step_s"])
    assert m["avg_processing_s"] is not None and m["avg_clip_s"] == 10.0
    assert m["peak_rss_mb"] > 0 and m["peak_rss_job"] in (ok, bad)


def test_trace_is_a_waterfall_with_the_failed_step_and_ffmpeg_stderr(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    video = make_video("lỗi.mp4", seconds=10.0)
    job_id = upload(client, video).json()["id"]
    client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "approve_sure"})
    source = Path(repo.get_job(db(cfg), job_id)["source_path"])
    source.write_bytes(b"not a video any more")  # render fails inside FFmpeg
    client.post(f"/api/jobs/{job_id}/render", json={"format": "mp4"})

    t = client.get(f"/api/jobs/{job_id}/trace").json()
    steps = [(s["step"], s["status"]) for s in t["spans"]]
    assert steps[:4] == [("extract_audio", "ok"), ("preview", "ok"), ("transcribe", "ok"),
                         ("detect", "ok")]  # fmt: skip
    assert steps[-1] == ("render", "error") and t["failed_step"] == "render"
    assert t["spans"][0]["offset_s"] == 0 and t["total_s"] >= t["spans"][-1]["offset_s"]
    assert t["errors"] and t["errors"][0]["step"] == "render" and "ffmpeg_stderr" in t["errors"][0]
    assert client.get("/api/jobs/nope/trace").status_code == 404


def test_logs_filter_by_level_and_job_and_take_ui_errors(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    job_id = upload(client, make_video(seconds=10.0)).json()["id"]
    res = client.post("/api/logs", json={"message": "TypeError: x is undefined",
                                         "stack": "at Review", "url": "/#/review/1"})  # fmt: skip
    assert res.status_code == 204
    for h in logging.getLogger("stuttercut").handlers:
        h.flush()

    errors = client.get("/api/logs", params={"level": "ERROR"}).json()
    assert errors[0]["msg"] == "TypeError: x is undefined" and errors[0]["source"] == "ui"
    mine = client.get("/api/logs", params={"job": job_id}).json()
    assert mine and all(e["job_id"] == job_id for e in mine)
    infos = client.get("/api/logs", params={"level": "info", "limit": 3}).json()
    assert len(infos) == 3 and {e["level"] for e in infos} == {"INFO"}
    assert infos[0]["ts"] >= infos[-1]["ts"]  # newest first
    assert client.get("/api/logs", params={"level": "LOUD"}).status_code == 422
    too_long = client.post("/api/logs", json={"message": "x" * 3000})
    assert too_long.status_code == 422


def test_export_has_logs_and_environment_but_no_transcript(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    job_id = upload(client, make_video(seconds=10.0)).json()["id"]
    words = repo.get_words(db(cfg), job_id, "verbatim")
    assert words  # the job has a transcript...
    res = client.post("/api/diagnostics/export")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert "stuttercut-diagnostics-" in res.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = z.namelist()
    assert {"environment.json", "metrics.json", "jobs.json", "README.txt"} <= set(names)
    assert any(n.startswith("logs/api.jsonl") for n in names)
    assert not any(n.endswith((".db", ".mp4", ".wav")) for n in names)
    env = json.loads(z.read("environment.json"))
    assert env["python"] and "api_key" not in env["settings"]["llm"]
    blob = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
    for w in ("chào", "phẩm", "bền"):  # ...that never reaches the export
        assert w not in blob
    assert json.loads(z.read("jobs.json"))[0]["id"] == job_id
    assert paths.log_dir(cfg).is_dir()
