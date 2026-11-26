"""The steps for one job: extract_audio -> transcribe -> detect [-> llm_review] (ADR 0002/0003).

llm_review runs only when an LLM client is given (STUTTERCUT_LLM_ENABLED=true). With the local
provider (ollama) and free RAM below STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB, the ASR model is
unloaded first (span unload_asr; on CUDA the test is free VRAM < STUTTERCUT_LLM_EXPECTED_GB +
STUTTERCUT_LLM_VRAM_MARGIN_GB) and loaded again before the next transcribe (span load_model):
the two models never sit in memory together on a 16 GB Mac. If the review fails, the job
keeps its rules-only cuts and tiers: WARN log, span error, still ready_for_review
(design: "LLM fails -> rules-only").

Render (separate call, after review): ready_for_review | done | failed at render -> rendering
-> done (output paths stored) or failed with failed_step=render; cuts are never touched.

Status: processing -> transcribed -> ready_for_review, or failed + failed_step. Every step
records a span; any error is logged with the job id. Words and detected cuts are replaced on
a re-run (cuts the user kept are never touched), so retries are safe.
"""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from stuttercut.asr import Transcriber, Unloadable
from stuttercut.config import RENDER_FORMATS, Config, LlmConfig
from stuttercut.llm import LLMClient
from stuttercut.llm.review import review
from stuttercut.media.audio import MediaError, extract_audio
from stuttercut.media.fcpxml import write_xml
from stuttercut.media.render import RenderError, plan, removed_s, render_mp4, video_info
from stuttercut.media.vad import VoiceDetector
from stuttercut.observability.metrics import PeakRss
from stuttercut.observability.spans import span
from stuttercut.platform import free_ram_gb, free_vram_gb
from stuttercut.rules import Interval
from stuttercut.rules.detect import detect
from stuttercut.storage import paths, repo

log = logging.getLogger(__name__)

STEPS = ("extract_audio", "transcribe", "detect")


def _fail(conn: sqlite3.Connection, job_id: str, step: str, e: Exception) -> str:
    extra: dict[str, object] = {"job_id": job_id, "step": step}
    if isinstance(e, RenderError):
        extra["render_step"] = e.step
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


def should_unload_asr(
    device: str, free_ram: float, free_vram: float | None, cfg: LlmConfig
) -> bool:
    """CUDA: the LLM must fit in free VRAM with a margin. MPS/CPU (shared memory): free RAM."""
    if device == "cuda" and free_vram is not None:
        return free_vram < cfg.expected_gb + cfg.vram_margin_gb
    return free_ram < cfg.unload_asr_below_gb


def _free_asr_for_local_llm(
    conn: sqlite3.Connection, cfg: Config, job_id: str, transcriber: Transcriber
) -> None:
    if cfg.llm.provider != "ollama" or not isinstance(transcriber, Unloadable):
        return
    if not transcriber.loaded:
        return
    ram = free_ram_gb()
    vram = free_vram_gb() if transcriber.device == "cuda" else None
    if not should_unload_asr(transcriber.device, ram, vram, cfg.llm):
        return
    with span(conn, job_id, "unload_asr"):
        transcriber.unload()
    vram_after = free_vram_gb() if vram is not None else None
    log.info(
        "ASR model unloaded before the local LLM",
        extra={"job_id": job_id, "device": transcriber.device, "free_ram_gb": round(ram, 1),
               "free_ram_gb_after": round(free_ram_gb(), 1),
               "free_vram_gb": None if vram is None else round(vram, 1),
               "free_vram_gb_after": None if vram_after is None else round(vram_after, 1)},
    )  # fmt: skip


def _try_llm_review(conn: sqlite3.Connection, cfg: Config, job_id: str, llm: LLMClient) -> None:
    try:
        warm = getattr(llm, "warm", None)  # local model: load it under its own, longer timeout
        if warm is not None:
            with span(conn, job_id, "llm_load"):
                warm()
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


RENDERABLE = ("ready_for_review", "done")


@dataclass(frozen=True)
class RenderResult:
    status: str  # done | failed
    approved: int = 0
    removed_s: float = 0.0
    output_s: float = 0.0
    encoder: str | None = None
    mp4: Path | None = None
    xml: Path | None = None


def run_render(
    conn: sqlite3.Connection, cfg: Config, job_id: str, fmt: str = "mp4"
) -> RenderResult:
    """Approved, not-kept cuts -> <name>_clean.mp4 and/or .xml in the output folder."""
    if fmt not in RENDER_FORMATS:
        raise ValueError(f"format must be one of {RENDER_FORMATS}, got {fmt!r}")
    job = repo.get_job(conn, job_id)
    if job is None:
        raise KeyError(f"no job {job_id}")
    retry = job["status"] == "failed" and job["failed_step"] == "render"
    if job["status"] not in RENDERABLE and not retry:
        raise ValueError(f"job {job_id} is {job['status']}; render needs one of {RENDERABLE}")
    repo.set_status(conn, job_id, "rendering")
    cuts = repo.approved_cuts(conn, job_id)
    source = Path(job["source_path"])
    try:
        with span(conn, job_id, "render"):
            info = video_info(source)
            if not info.has_audio:
                raise RenderError("probe", f"{source.name} has no audio stream")
            keeps = plan(cuts, info.duration_s, cfg.render, info.fps)
            out_dir = paths.output_dir(cfg)
            mp4 = xml = None
            encoder = None
            if fmt in ("mp4", "both"):
                mp4, encoder = render_mp4(source, keeps, out_dir, cfg.render,
                                          cfg.media.ffmpeg_threads)  # fmt: skip
            if fmt in ("xml", "both"):
                xml = write_xml(source, keeps, info, out_dir)
    except Exception as e:
        _fail(conn, job_id, "render", e)
        return RenderResult("failed", approved=len(cuts))
    repo.update_job(conn, job_id, output_path=str(mp4) if mp4 else None,
                    xml_path=str(xml) if xml else None)  # fmt: skip
    repo.set_status(conn, job_id, "done")
    removed = removed_s(keeps, info.duration_s)
    log.info(
        "render done",
        extra={"job_id": job_id, "format": fmt, "approved": len(cuts), "segments": len(keeps),
               "removed_s": round(removed, 3), "encoder": encoder},
    )  # fmt: skip
    return RenderResult("done", len(cuts), removed, info.duration_s - removed, encoder, mp4, xml)
