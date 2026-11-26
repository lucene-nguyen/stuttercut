"""The worker process as seen from the API (ADR 0003): start it, send it messages, stop it.

One process, one queue, so one job runs at a time; the API process never loads the model or
runs FFmpeg encodes itself.
"""

import logging
import multiprocessing as mp
from multiprocessing.process import BaseProcess
from typing import Any

from stuttercut.config import Config
from stuttercut.worker.main import Message, worker_main

log = logging.getLogger(__name__)


class WorkerHandle:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._ctx = mp.get_context("spawn")  # same behaviour on Windows, macOS and Linux
        self.queue: Any = self._ctx.Queue()
        self.process: BaseProcess | None = None

    def start(self) -> None:
        self.process = self._ctx.Process(
            target=worker_main, args=(self.queue, self._cfg), name="stuttercut-worker", daemon=True
        )
        self.process.start()
        log.info("worker started", extra={"pid": self.process.pid})

    def put(self, msg: Message) -> None:
        self.queue.put(msg)

    def stop(self, timeout_s: float = 5.0) -> None:
        if self.process is None:
            return
        self.queue.put(None)
        self.process.join(timeout_s)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout_s)
        log.info("worker stopped", extra={"exitcode": self.process.exitcode})
