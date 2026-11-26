"""JSON views of jobs for the UI: list rows, review detail and progress (pure, no FastAPI)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stuttercut.config import Config
from stuttercut.media.render import plan, removed_s
from stuttercut.storage import repo

# Rough seconds of work per second of clip, for a progress bar only (c001 on an RTX 4060:
# transcribe 85 s for 161 s). The bar stops at 99% until the step really ends.
STEP_RATE = {
    "extract_audio": 0.01, "preview": 0.05, "load_model": 0.05, "transcribe": 0.55,
    "detect": 0.02, "unload_asr": 0.01, "llm_load": 0.05, "llm_review": 0.35, "render": 0.06,
}  # fmt: skip
STEP_LABEL = {
    "extract_audio": "Extracting audio", "preview": "Making preview", "load_model": "Loading model",
    "transcribe": "Transcribing", "detect": "Detecting cuts", "unload_asr": "Freeing memory",
    "llm_load": "Loading LLM", "llm_review": "Reviewing with LLM", "render": "Rendering",
}  # fmt: skip
TERMINAL = ("ready_for_review", "done", "failed", "cancelled")


def progress(job: sqlite3.Row, now: datetime | None = None) -> int | None:
    """Percent of the running step, estimated from its usual speed; None when idle."""
    if not job["step"] or not job["step_started_at"]:
        return None
    started = datetime.fromisoformat(job["step_started_at"].replace("Z", "+00:00"))
    elapsed = ((now or datetime.now(UTC)) - started).total_seconds()
    expected = max(1.0, (job["duration_s"] or 60) * STEP_RATE.get(job["step"], 0.05))
    return max(0, min(99, int(100 * elapsed / expected)))


def saved_s(conn: sqlite3.Connection, job: sqlite3.Row, cfg: Config) -> float:
    """Seconds the approved cuts remove (after padding and merging, as render will)."""
    duration = job["duration_s"]
    if not duration:
        return 0.0
    return round(removed_s(plan(repo.approved_cuts(conn, job["id"]), duration, cfg.render),
                           duration), 2)  # fmt: skip


def summary(conn: sqlite3.Connection, job: sqlite3.Row, cfg: Config) -> dict[str, Any]:
    counts = repo.cut_counts(conn, job["id"], "tier")
    return {
        "id": job["id"],
        "name": Path(job["source_path"]).name,
        "status": job["status"],
        "step": job["step"],
        "step_label": STEP_LABEL.get(job["step"] or ""),
        "progress": progress(job),
        "failed_step": job["failed_step"],
        "error": job["error"],
        "duration_s": job["duration_s"],
        "created_at": job["created_at"],
        "cut_count": sum(counts.values()),
        "saved_s": saved_s(conn, job, cfg),
        "output_path": job["output_path"],
        "xml_path": job["xml_path"],
    }


def detail(conn: sqlite3.Connection, job: sqlite3.Row, cfg: Config) -> dict[str, Any]:
    words = repo.get_words(conn, job["id"], "verbatim")
    cut_keys = ("id", "start_s", "end_s", "reason", "source", "confidence", "tier", "kept",
                "approved", "decided_at", "llm_verdict", "llm_reason")  # fmt: skip
    return {
        **summary(conn, job, cfg),
        "words": [
            {"i": i, "text": w.text, "start": w.start, "end": w.end} for i, w in enumerate(words)
        ],
        "cuts": [{k: c[k] for k in cut_keys} for c in repo.get_cuts(conn, job["id"])],
    }
