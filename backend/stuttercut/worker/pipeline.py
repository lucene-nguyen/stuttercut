"""The steps for one job: extract_audio -> transcribe -> detect [-> llm_review] (ADR 0002/0003).

llm_review runs only when an LLM client is given (STUTTERCUT_LLM_ENABLED=true). With the local
provider (ollama) and free RAM below STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB, the ASR model is
unloaded first (span unload_asr) and loaded again before the next transcribe (span load_model):
the two models never sit in memory together on a 16 GB Mac. If the review fails, the job
keeps its rules-only cuts and tiers: WARN log, span error, still ready_for_review
(design: "LLM fails -> rules-only").

Status: processing -> transcribed -> ready_for_review, or failed + failed_step. Every step
records a span; any error is logged with the job id. Words and detected cuts are replaced on
a re-run (cuts the user kept are never touched), so retries are safe.
"""

import logging
import sqlite3
from pathlib import Path

from stuttercut.asr import Transcriber, Unloadable
from stuttercut.config import Config
from stuttercut.llm import LLMClient
from stuttercut.llm.review import review
from stuttercut.media.audio import MediaError, extract_audio
from stuttercut.media.vad import VoiceDetector
from stuttercut.observability.metrics import PeakRss
from stuttercut.observability.spans import span
from stuttercut.platform import free_ram_gb
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
    stored = repo.replace_cuts(conn, job_id, cuts, cfg.rules.tier_sure_min)
    log.info(
        "cuts detected",
        extra={"job_id": job_id, "cuts": stored, "vad": voiced is not None,
               "diff": intended is not None},
    )  # fmt: skip


def _llm_review(conn: sqlite3.Connection, cfg: Config, job_id: str, llm: LLMClient) -> None:
    """Send transcript text + candidates (no media, no paths) and store verdicts/retakes."""
    repo.clear_llm_cuts(conn, job_id)  # a re-run replaces the LLM's own earlier proposals
    words = repo.get_words(conn, job_id, "verbatim")
    rows = [r for r in repo.get_cuts(conn, job_id) if not r["kept"]]
    outcome = review(words, rows, llm, cfg.llm, cfg.rules.tier_sure_min)
    for cut_id, final, tier_, verdict, llm_conf, reason in outcome.updates:
        repo.apply_review(conn, cut_id, final, tier_, verdict, llm_conf, reason)
    for cut, tier_, reason in outcome.new_cuts:
        repo.add_llm_cut(conn, job_id, cut, tier_, reason)
    cost = outcome.cost_usd(cfg.llm)
    repo.update_job(
        conn, job_id, llm_input_tokens=outcome.input_tokens,
        llm_output_tokens=outcome.output_tokens, llm_cost_usd=cost,
    )  # fmt: skip
    keeps = sum(u[3] == "keep" for u in outcome.updates)
    log.info(
        "llm review done",
        extra={"job_id": job_id, "model": llm.model, "requests": outcome.requests,
               "input_tokens": outcome.input_tokens, "output_tokens": outcome.output_tokens,
               "cost_usd": cost, "judged": len(outcome.updates), "keep": keeps,
               "new_retakes": len(outcome.new_cuts), "ignored": outcome.ignored},
    )  # fmt: skip


def _free_asr_for_local_llm(
    conn: sqlite3.Connection, cfg: Config, job_id: str, transcriber: Transcriber
) -> None:
    if cfg.llm.provider != "ollama" or not isinstance(transcriber, Unloadable):
        return
    free = free_ram_gb()
    if not transcriber.loaded or free >= cfg.llm.unload_asr_below_gb:
        return
    with span(conn, job_id, "unload_asr"):
        transcriber.unload()
    log.info(
        "ASR model unloaded before the local LLM",
        extra={"job_id": job_id, "free_ram_gb": round(free, 1),
               "free_ram_gb_after": round(free_ram_gb(), 1),
               "threshold_gb": cfg.llm.unload_asr_below_gb},
    )  # fmt: skip


def _try_llm_review(conn: sqlite3.Connection, cfg: Config, job_id: str, llm: LLMClient) -> None:
    try:
        with span(conn, job_id, "llm_review"):
            _llm_review(conn, cfg, job_id, llm)
    except Exception:  # never fails the job: rules-only cuts stay
        log.warning("LLM review failed; keeping rules-only cuts", exc_info=True,
                    extra={"job_id": job_id, "step": "llm_review"})  # fmt: skip
    release = getattr(llm, "release", None)  # local model: free RAM/VRAM for the next job
    if release is not None:
        try:
            release()
        except Exception:
            log.warning("could not unload the local LLM", exc_info=True, extra={"job_id": job_id})


def run_job(
    conn: sqlite3.Connection,
    cfg: Config,
    job_id: str,
    transcriber: Transcriber,
    vad: VoiceDetector | None = None,
    llm: LLMClient | None = None,
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
            if isinstance(transcriber, Unloadable) and not transcriber.loaded:
                step = "load_model"  # freed for the local LLM after the previous job
                with span(conn, job_id, step):
                    transcriber.load()
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
        if llm is not None:
            try:
                _free_asr_for_local_llm(conn, cfg, job_id, transcriber)
            except Exception:  # an unload problem must not block the review
                log.warning("could not unload the ASR model", exc_info=True,
                            extra={"job_id": job_id})  # fmt: skip
            _try_llm_review(conn, cfg, job_id, llm)
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


def run_llm_review(conn: sqlite3.Connection, cfg: Config, job_id: str, llm: LLMClient) -> str:
    """Re-run only the LLM review on the stored candidates (rules-only cuts stay on failure)."""
    _try_llm_review(conn, cfg, job_id, llm)
    return "ready_for_review"
