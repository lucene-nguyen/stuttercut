"""Worker process entrypoint (ADR 0003): load the transcriber once, then run one job at a time.

Started by the API server (LEARNING-235) as ``multiprocessing.Process(target=worker_main,
args=(job_queue,))``; it reads job ids from the queue until it gets ``None``.
"""

import logging
import sys
from collections.abc import Callable
from typing import Protocol

from stuttercut.asr import Transcriber
from stuttercut.config import Config, load_config
from stuttercut.observability.logging import setup_logging
from stuttercut.platform import preflight_model_size, select_device
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.pipeline import run_job

log = logging.getLogger(__name__)


class JobQueue(Protocol):
    def get(self) -> str | None: ...


def load_transcriber(cfg: Config) -> Transcriber:
    """Pick the device, check free RAM for the model size, load CrisperWhisper."""
    from stuttercut.asr.crisperwhisper import CrisperWhisperTranscriber

    device = select_device(cfg.asr.device)
    size = preflight_model_size(cfg.asr)
    log.info("loading ASR model", extra={"device": device, "size": size})
    return CrisperWhisperTranscriber(size, device, cfg.asr)


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


def worker_main(
    job_queue: JobQueue,
    cfg: Config | None = None,
    make_transcriber: Callable[[Config], Transcriber] = load_transcriber,
) -> None:
    cfg = cfg or load_config()
    setup_logging(paths.log_dir(cfg), cfg.log)
    lower_priority(cfg.worker_nice)
    conn = connect(paths.db_path(cfg))
    try:
        transcriber: Transcriber | None = make_transcriber(cfg)
        load_error = ""
    except Exception as e:  # e.g. InsufficientMemoryError: fail jobs clearly, keep serving
        log.error("ASR model failed to load", exc_info=True)
        transcriber, load_error = None, f"{type(e).__name__}: {e}"
    try:
        while (job_id := job_queue.get()) is not None:
            if transcriber is None:
                repo.set_status(conn, job_id, "failed", failed_step="load_model", error=load_error)
                continue
            run_job(conn, cfg, job_id, transcriber)
    finally:
        conn.close()
