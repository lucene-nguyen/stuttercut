"""Read side of observability for the Diagnostics screen (LEARNING-228): logs, metrics, traces,
environment, and the diagnostics export.

Nothing here reads transcript text: logs hold counts, steps and errors, spans hold timings, and
the export leaves out the database (words) and every media file.
"""

import dataclasses
import io
import json
import platform
import sqlite3
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any

from stuttercut.config import Config
from stuttercut.storage import repo

LEVELS = {
    "ERROR": "ERROR",
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
}
PIPELINE = ("extract_audio", "preview", "load_model", "transcribe", "detect", "unload_asr",
            "llm_load", "llm_review")  # fmt: skip


def log_files(log_dir: Path) -> list[Path]:
    """Every JSON Lines file, rotated ones included (app/api/worker.jsonl[.N])."""
    return sorted(p for p in log_dir.glob("*.jsonl*") if p.is_file()) if log_dir.is_dir() else []


def read_logs(
    log_dir: Path, level: str | None = None, job: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Newest first. ``level`` matches exactly (WARN = WARNING); ``job`` = a job id."""
    want = LEVELS.get(level.upper()) if level else None
    if level and want is None:
        raise ValueError(f"level must be one of {sorted(LEVELS)}")
    entries: list[dict[str, Any]] = []
    for path in log_files(log_dir):
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut by a crash
                if not isinstance(e, dict):
                    continue
                if (want and e.get("level") != want) or (job and e.get("job_id") != job):
                    continue
                entries.append(e)
    entries.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
    return entries[:limit]


def _since(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def metrics(conn: sqlite3.Connection, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    """Jobs, success rate, average time per step and per job, peak RSS over the last ``days``."""
    since = _since(now or datetime.now(UTC), days)
    jobs = list(conn.execute("SELECT * FROM job WHERE created_at >= ?", (since,)))
    by_status: dict[str, int] = {}
    for j in jobs:
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1
    failed = [j for j in jobs if j["status"] == "failed"]
    finished = sum(by_status.get(s, 0) for s in ("ready_for_review", "done", "failed"))
    failures: dict[str, int] = {}
    for j in failed:
        failures[j["failed_step"] or "unknown"] = failures.get(j["failed_step"] or "unknown", 0) + 1
    spans = list(
        conn.execute(
            "SELECT s.job_id, s.step, s.duration_s FROM span s JOIN job j ON j.id = s.job_id"
            " WHERE j.created_at >= ? AND s.status = 'ok'",
            (since,),
        )
    )
    per_step: dict[str, list[float]] = {}
    per_job: dict[str, float] = {}
    for s in spans:
        per_step.setdefault(s["step"], []).append(s["duration_s"])
        if s["step"] in PIPELINE:
            per_job[s["job_id"]] = per_job.get(s["job_id"], 0.0) + s["duration_s"]
    peak = max(jobs, key=lambda j: j["peak_rss_mb"] or 0, default=None)
    durations = [j["duration_s"] for j in jobs if j["duration_s"]]
    return {
        "days": days,
        "jobs": len(jobs),
        "by_status": by_status,
        "success_rate": round(1 - len(failed) / finished, 3) if finished else None,
        "failures_by_step": failures,
        "avg_step_s": {k: round(sum(v) / len(v), 2) for k, v in sorted(per_step.items())},
        "avg_processing_s": round(sum(per_job.values()) / len(per_job), 1) if per_job else None,
        "avg_clip_s": round(sum(durations) / len(durations), 1) if durations else None,
        "peak_rss_mb": peak["peak_rss_mb"] if peak else None,
        "peak_rss_job": peak["id"] if peak and peak["peak_rss_mb"] else None,
    }


def trace(conn: sqlite3.Connection, job_id: str, log_dir: Path) -> dict[str, Any] | None:
    """Spans of one job as a waterfall (offset from the first span), plus its error lines."""
    job = repo.get_job(conn, job_id)
    if job is None:
        return None
    spans = repo.get_spans(conn, job_id)
    t0 = datetime.fromisoformat(spans[0]["started_at"].replace("Z", "+00:00")) if spans else None
    rows = []
    for s in spans:
        start = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
        offset = round((start - t0).total_seconds(), 3) if t0 else 0.0
        rows.append({"step": s["step"], "status": s["status"], "error": s["error"],
                     "started_at": s["started_at"], "duration_s": s["duration_s"],
                     "offset_s": offset})  # fmt: skip
    total = max((r["offset_s"] + r["duration_s"] for r in rows), default=0.0)
    errors = [
        {k: e[k] for k in ("ts", "msg", "step", "exc", "ffmpeg_stderr", "render_step") if k in e}
        for e in read_logs(log_dir, "ERROR", job_id, limit=20)
    ]
    return {
        "id": job_id,
        "name": Path(job["source_path"]).name,
        "status": job["status"],
        "failed_step": job["failed_step"],
        "error": job["error"],
        "created_at": job["created_at"],
        "total_s": round(total, 3),
        "spans": rows,
        "errors": errors,
    }


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def _ffmpeg() -> str | None:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True,
                             text=True, timeout=10).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0] if out else None


def environment(cfg: Config) -> dict[str, Any]:
    """Machine, versions and settings (the API key left out), for support and the screen."""
    import psutil

    settings = dataclasses.asdict(cfg)
    settings["llm"].pop("api_key", None)
    mem = psutil.virtual_memory()
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": psutil.cpu_count(),
        "ram_gb": round(mem.total / 2**30, 1),
        "ram_free_gb": round(mem.available / 2**30, 1),
        "python": sys.version.split()[0],
        "packages": {
            p: _version(p)
            for p in (
                "stuttercut",
                "fastapi",
                "torch",
                "transformers",
                "ctranslate2",
                "silero-vad",
                "anthropic",
            )
        },
        "ffmpeg": _ffmpeg(),
        "settings": json.loads(json.dumps(settings, default=str)),
    }


def export_zip(conn: sqlite3.Connection, cfg: Config, log_dir: Path) -> bytes:
    """Logs + environment + metrics + job traces (no transcripts, no media, no database)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in log_files(log_dir):
            z.write(path, f"logs/{path.name}")
        z.writestr("environment.json", json.dumps(environment(cfg), indent=2))
        z.writestr("metrics.json", json.dumps(metrics(conn), indent=2))
        traces = [trace(conn, j["id"], log_dir) for j in repo.list_jobs(conn, limit=50)]
        z.writestr("jobs.json", json.dumps(traces, indent=2, ensure_ascii=False))
        z.writestr("README.txt", "StutterCut diagnostics: logs, environment, metrics and job "
                   "traces. No transcripts, audio, video or database are included.\n")  # fmt: skip
    return buf.getvalue()
