"""Worker process entrypoint (ADR 0003): load the transcriber once, then run one job at a time.

Started by the API server as ``multiprocessing.Process(target=worker_main, args=(job_queue,
cfg))``. It reads messages from the queue until it gets ``None``:
``job_id`` or ``("process", job_id)`` runs the pipeline; ``("render", job_id, format, folder)``
renders; ``("retry", job_id)`` re-runs from the failed step. One message at a time.
"""

import logging
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from stuttercut.asr import Transcriber
from stuttercut.config import Config, load_config
from stuttercut.llm import LLMClient, LLMError
from stuttercut.media.vad import VoiceDetector
from stuttercut.observability.logging import setup_logging
from stuttercut.platform import preflight_model_size, select_device
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.pipeline import run_job, run_render, run_retry

log = logging.getLogger(__name__)


Message = str | tuple[str, ...]


class JobQueue(Protocol):
    def get(self) -> Message | None: ...


def load_transcriber(cfg: Config) -> Transcriber:
    """Pick the device, check free RAM for the model size, load CrisperWhisper.

    STUTTERCUT_FAKE_TRANSCRIBER (tests, E2E) loads a fixture transcript instead.
    """
    if cfg.asr.fake_fixture is not None:
        from stuttercut.asr.fake import FakeTranscriber

        return FakeTranscriber(cfg.asr.fake_fixture, cfg.asr.passes)
    from stuttercut.asr.crisperwhisper import CrisperWhisperTranscriber

    device = select_device(cfg.asr.device)
    size = preflight_model_size(cfg.asr)
    log.info("loading ASR model", extra={"device": device, "size": size})
    return CrisperWhisperTranscriber(size, device, cfg.asr)


def load_vad(cfg: Config) -> VoiceDetector | None:
    """silero-vad if installed; otherwise detection runs on words only (WARN logged)."""
    if cfg.asr.fake_fixture is not None:
        return None  # fake transcript: VAD on its synthetic audio would invent cuts
    try:
        from stuttercut.media.vad import SileroVad

        return SileroVad(cfg.rules)
    except ImportError:
        log.warning("silero-vad not installed: VAD-based cuts and pause checks are off")
        return None


def load_llm(cfg: Config) -> LLMClient | None:
    """The review LLM when STUTTERCUT_LLM_ENABLED=true; None means rules-only.

    ollama (default) needs no key; if Ollama is not running, each review fails and falls back.
    anthropic needs LLM_API_KEY.
    """
    if not cfg.llm.enabled:
        return None
    if cfg.llm.provider == "ollama":
        from stuttercut.llm.ollama_client import OllamaClient

        return OllamaClient(cfg.llm)
    from stuttercut.llm.anthropic_client import AnthropicClient

    try:
        return AnthropicClient(cfg.llm)
    except LLMError:
        log.warning("LLM review enabled but LLM_API_KEY is empty; LLM review is off")
        return None


def lower_priority(nice: int) -> None:
    """Keep the machine usable during a job (design: worker os.nice(10))."""
    if nice <= 0:
        return
    import psutil

    try:
        if sys.platform == "win32":
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            psutil.Process().nice(nice)
    except psutil.Error:
        log.warning("could not lower worker priority", exc_info=True)


def handle(
    conn: sqlite3.Connection,
    cfg: Config,
    msg: Message,
    transcriber: Transcriber | None,
    vad: VoiceDetector | None = None,
    llm: LLMClient | None = None,
    load_error: str = "",
) -> None:
    """Run one queue message. Errors are logged, never raised: the worker keeps serving."""
    kind, job_id, *args = ("process", msg) if isinstance(msg, str) else msg
    try:
        if kind == "render":
            fmt, folder = [*args, "mp4", ""][:2]
            run_render(conn, cfg, job_id, fmt, Path(folder) if folder else None)
        elif transcriber is None:
            repo.set_status(conn, job_id, "failed", failed_step="load_model", error=load_error)
        elif kind == "retry":
            run_retry(conn, cfg, job_id, transcriber, vad, llm)
        else:
            run_job(conn, cfg, job_id, transcriber, vad, llm)
    except Exception:
        log.error("worker message failed", exc_info=True, extra={"job_id": job_id, "kind": kind})


def worker_main(
    job_queue: JobQueue,
    cfg: Config | None = None,
    make_transcriber: Callable[[Config], Transcriber] = load_transcriber,
    make_vad: Callable[[Config], VoiceDetector | None] = load_vad,
    make_llm: Callable[[Config], LLMClient | None] = load_llm,
) -> None:
    cfg = cfg or load_config()
    setup_logging(paths.log_dir(cfg), cfg.log, "worker")
    lower_priority(cfg.worker_nice)
    conn = connect(paths.db_path(cfg))
    try:
        transcriber: Transcriber | None = make_transcriber(cfg)
        load_error = ""
        vad = make_vad(cfg)
        llm = make_llm(cfg)
    except Exception as e:  # e.g. InsufficientMemoryError: fail jobs clearly, keep serving
        log.error("ASR model failed to load", exc_info=True)
        transcriber, load_error, vad, llm = None, f"{type(e).__name__}: {e}", None, None
    try:
        while (msg := job_queue.get()) is not None:
            handle(conn, cfg, msg, transcriber, vad, llm, load_error)
    finally:
        conn.close()
