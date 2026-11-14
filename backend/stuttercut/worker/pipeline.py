"""The steps for one job: extract_audio -> transcribe -> detect (ADR 0002, 0003).

Status: processing -> transcribed -> ready_for_review, or failed + failed_step. Every step
records a span; any error is logged with the job id. Words and detected cuts are replaced on
a re-run (cuts the user kept are never touched), so retries are safe.
"""

import logging
import sqlite3
from pathlib import Path

from stuttercut.asr import Transcriber
from stuttercut.config import Config
from stuttercut.media.audio import MediaError, extract_audio
from stuttercut.media.vad import VoiceDetector
from stuttercut.observability.metrics import PeakRss
from stuttercut.observability.spans import span
from stuttercut.rules import Interval
from stuttercut.rules.detect import detect
from stuttercut.storage import paths, repo

log = logging.getLogger(__name__)

STEPS = ("extract_audio", "transcribe", "detect")


def _fail(conn: sqlite3.Connection, job_id: str, step: str, e: Exception) -> str:
    extra: dict[str, object] = {"job_id": job_id, "step": step}
    if isinstance(e, MediaError) and e.stderr:
        extra["ffmpeg_stderr"] = e.stderr[-4000:]
    log.error("job failed", exc_info=True, extra=extra)
    repo.set_status(conn, job_id, "failed", failed_step=step, error=f"{type(e).__name__}: {e}")
    return "failed"


def _detect(conn: sqlite3.Connection, cfg: Config, job_id: str, vad: VoiceDetector | None) -> None:
    """Words from the DB + VAD on the job's audio -> rules -> CUT rows."""
    verbatim = repo.get_words(conn, job_id, "verbatim")
    intended = repo.get_words(conn, job_id, "intended") or None
    voiced: list[Interval] | None = None
    if vad is not None:
        try:
            voiced = vad.voiced(paths.job_dir(cfg, job_id) / "audio.wav")
        except Exception:  # VAD is a backup source: degrade to word rules, do not fail
            log.warning("VAD failed; detecting from words only", exc_info=True,
                        extra={"job_id": job_id})  # fmt: skip
    cuts = detect(verbatim, cfg.rules, intended=intended, voiced=voiced)
    stored = repo.replace_cuts(conn, job_id, cuts)
    log.info(
        "cuts detected",
        extra={"job_id": job_id, "cuts": stored, "vad": voiced is not None,
               "diff": intended is not None},
    )  # fmt: skip


def run_job(
    conn: sqlite3.Connection,
    cfg: Config,
    job_id: str,
    transcriber: Transcriber,
    vad: VoiceDetector | None = None,
) -> str:
    """Run all steps; returns the final status (``ready_for_review`` or ``failed``)."""
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
            repo.set_status(conn, job_id, "transcribed")
            step = "detect"
            with span(conn, job_id, step):
                _detect(conn, cfg, job_id, vad)
        except Exception as e:
            return _fail(conn, job_id, step, e)
        finally:
            repo.update_job(conn, job_id, peak_rss_mb=rss.peak_mb)
    repo.set_status(conn, job_id, "ready_for_review")
    log.info("job ready for review", extra={"job_id": job_id, **repo.word_counts(conn, job_id)})
    return "ready_for_review"


def run_detect(
    conn: sqlite3.Connection, cfg: Config, job_id: str, vad: VoiceDetector | None = None
) -> str:
    """Re-run only the detect step on stored words (e.g. after changing thresholds)."""
    try:
        with span(conn, job_id, "detect"):
            _detect(conn, cfg, job_id, vad)
    except Exception as e:
        return _fail(conn, job_id, "detect", e)
    repo.set_status(conn, job_id, "ready_for_review")
    return "ready_for_review"
