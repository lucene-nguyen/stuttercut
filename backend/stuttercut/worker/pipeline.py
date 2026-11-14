"""The transcription steps for one job: extract_audio -> transcribe (ADR 0002, 0003).

Every step records a span; any error leaves the job ``failed`` with ``failed_step`` and is
logged with the job id. Words already stored for a job are replaced, so a retry is safe.
"""

import logging
import sqlite3
from pathlib import Path

from stuttercut.asr import Transcriber
from stuttercut.config import Config
from stuttercut.media.audio import MediaError, extract_audio
from stuttercut.observability.metrics import PeakRss
from stuttercut.observability.spans import span
from stuttercut.storage import paths, repo

log = logging.getLogger(__name__)

STEPS = ("extract_audio", "transcribe")


def run_job(conn: sqlite3.Connection, cfg: Config, job_id: str, transcriber: Transcriber) -> str:
    """Run the steps; returns the final status (``transcribed`` or ``failed``)."""
    job = repo.get_job(conn, job_id)
    if job is None:
        raise KeyError(f"no job {job_id}")
    repo.set_status(conn, job_id, "processing")
    wav = paths.job_dir(cfg, job_id) / "audio.wav"
    step = STEPS[0]
    with PeakRss() as rss:
        try:
            with span(conn, job_id, step):
                duration = extract_audio(Path(job["source_path"]), wav, cfg.media)
                repo.update_job(conn, job_id, duration_s=round(duration, 3))
            step = "transcribe"
            with span(conn, job_id, step):
                pair = transcriber.transcribe(wav)
                repo.replace_words(conn, job_id, "verbatim", pair.verbatim)
                # Verbatim-only also clears intended words left by an earlier dual attempt.
                repo.replace_words(conn, job_id, "intended", pair.intended or [])
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            extra: dict[str, object] = {"job_id": job_id, "step": step}
            if isinstance(e, MediaError) and e.stderr:
                extra["ffmpeg_stderr"] = e.stderr[-4000:]
            log.error("job failed", exc_info=True, extra=extra)
            repo.set_status(conn, job_id, "failed", failed_step=step, error=error)
            return "failed"
        finally:
            repo.update_job(conn, job_id, peak_rss_mb=rss.peak_mb)
    repo.set_status(conn, job_id, "transcribed")
    log.info("job transcribed", extra={"job_id": job_id, **repo.word_counts(conn, job_id)})
    return "transcribed"
