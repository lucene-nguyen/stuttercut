"""The worker process as seen from the API (ADR 0003): start it, send it messages, watch it.

One process and one queue, so one job runs at a time; the API process never loads the model or
encodes. The watchdog (a thread in the API process, LEARNING-235) samples the worker every
STUTTERCUT_WATCHDOG_INTERVAL_S and stops it when it died, when worker + FFmpeg use more than
STUTTERCUT_WORKER_MAX_RSS_GB, or when the running step passes its timeout. The running job then
fails at that step with the reason (a span records it), a fresh worker starts, and the work still
waiting in the database is queued again. Reviewed cuts are never touched.
"""

import contextlib
import logging
import multiprocessing as mp
import sqlite3
import threading
import time
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from typing import Any

import psutil

from stuttercut.config import Config
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import Message, worker_main
from stuttercut.worker.pipeline import job_options

log = logging.getLogger(__name__)

RUNNING = "status IN ('processing', 'transcribed') OR (status = 'rendering' AND step IS NOT NULL)"


def fail_running(conn: sqlite3.Connection, reason: str) -> list[str]:
    """Jobs the worker was running -> failed at their step, with a span. Returns their ids."""
    rows = list(conn.execute(f"SELECT * FROM job WHERE {RUNNING}"))
    for job in rows:
        step = job["step"] or ("render" if job["status"] == "rendering" else "transcribe")
        started = job["step_started_at"] or repo.now_iso()
        elapsed = datetime.now(UTC) - datetime.fromisoformat(started.replace("Z", "+00:00"))
        repo.insert_span(conn, job["id"], step, started, round(elapsed.total_seconds(), 3),
                         "error", reason)  # fmt: skip
        repo.set_step(conn, job["id"], None)
        repo.set_status(conn, job["id"], "failed", failed_step=step, error=reason)
        log.error("job failed: worker stopped", extra={"job_id": job["id"], "step": step,
                                                       "reason": reason})  # fmt: skip
    return [j["id"] for j in rows]


def pending_messages(conn: sqlite3.Connection) -> list[Message]:
    """Work waiting in the database, oldest first: queued jobs and requested renders."""
    msgs: list[Message] = []
    for job in conn.execute(
        "SELECT * FROM job WHERE status = 'queued' OR (status = 'rendering' AND step IS NULL)"
        " ORDER BY created_at"
    ):
        if job["status"] == "rendering":
            req = job_options(job).get("render")
            render = req if isinstance(req, dict) else {}
            msgs.append(("render", job["id"], str(render.get("format", "mp4")),
                         str(render.get("folder") or "")))  # fmt: skip
        else:
            msgs.append(("retry", job["id"]) if job["failed_step"] else ("process", job["id"]))
    return msgs


def tree_rss_mb(proc: psutil.Process) -> float:
    """RSS of the worker and its children (FFmpeg)."""
    total = 0
    for p in [proc, *proc.children(recursive=True)]:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            continue  # a child that just exited
    return total / 2**20


class WorkerHandle:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._ctx = mp.get_context("spawn")  # same behaviour on Windows, macOS and Linux
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self.queue: Any = self._ctx.Queue()
        self.process: BaseProcess | None = None
        self.restarts = 0
        self.stats: dict[str, Any] = {"alive": False}
        self._watchdog: threading.Thread | None = None

    # --- lifecycle --------------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._spawn()
        if self._watchdog is None:
            self._watchdog = threading.Thread(target=self._watch, name="watchdog", daemon=True)
            self._watchdog.start()

    def _spawn(self) -> None:
        self.process = self._ctx.Process(
            target=worker_main, args=(self.queue, self._cfg), name="stuttercut-worker", daemon=True
        )
        self.process.start()
        log.info("worker started", extra={"pid": self.process.pid, "restarts": self.restarts})

    def put(self, msg: Message) -> None:
        with self._lock:
            self.queue.put(msg)

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stopping.set()
        if self.process is None:
            return
        self.queue.put(None)
        self.process.join(timeout_s)
        if self.process.is_alive():
            self._kill_tree()
        log.info("worker stopped", extra={"exitcode": self.process.exitcode})

    def _kill_tree(self) -> None:
        """Terminate the worker and its FFmpeg children; kill what is left after the grace."""
        assert self.process is not None and self.process.pid is not None
        try:
            root = psutil.Process(self.process.pid)
            procs = [*root.children(recursive=True), root]
        except psutil.NoSuchProcess:
            procs = []
        for p in procs:
            with contextlib.suppress(psutil.Error):
                p.terminate()
        _gone, alive = psutil.wait_procs(procs, timeout=self._cfg.limits.kill_grace_s)
        for p in alive:
            with contextlib.suppress(psutil.Error):
                p.kill()
        self.process.join(self._cfg.limits.kill_grace_s)

    def restart(self, reason: str) -> None:
        """Stop the worker, fail the job it ran, start a fresh one, queue the waiting work."""
        with self._lock:
            if self._stopping.is_set():
                return
            log.error("restarting the worker", extra={"reason": reason})
            if self.process is not None and self.process.is_alive():
                self._kill_tree()
            conn = connect(paths.db_path(self._cfg))
            try:
                fail_running(conn, reason)
                self.queue = self._ctx.Queue()  # the old one may be broken by the kill
                for msg in pending_messages(conn):
                    self.queue.put(msg)
            finally:
                conn.close()
            self.restarts += 1
            self._spawn()

    # --- watchdog ---------------------------------------------------------------------------

    def check(self, conn: sqlite3.Connection) -> str | None:
        """One watchdog tick: the reason to restart the worker, or None."""
        limits = self._cfg.limits
        proc = self.process
        if proc is None:
            return None
        if not proc.is_alive():
            self.stats = {"alive": False, "exitcode": proc.exitcode, "restarts": self.restarts}
            return f"worker stopped unexpectedly (exit code {proc.exitcode})"
        try:
            ps = psutil.Process(proc.pid)
            rss = tree_rss_mb(ps)
            cpu = ps.cpu_percent(interval=None)
        except psutil.NoSuchProcess:
            return "worker stopped unexpectedly"
        self.stats = {"alive": True, "pid": proc.pid, "rss_mb": round(rss),
                      "cpu_percent": cpu, "restarts": self.restarts}  # fmt: skip
        if rss > limits.worker_max_rss_gb * 1024:
            used, limit = rss / 1024, limits.worker_max_rss_gb
            return f"resource limit: the worker used {used:.1f} GB (limit {limit:g} GB)"
        job = conn.execute(f"SELECT * FROM job WHERE ({RUNNING}) AND step IS NOT NULL").fetchone()
        if job is not None and job["step_started_at"]:
            started = datetime.fromisoformat(job["step_started_at"].replace("Z", "+00:00"))
            elapsed = (datetime.now(UTC) - started).total_seconds()
            limit = limits.step_timeout_s(job["step"], job["duration_s"])
            if elapsed > limit:
                return f"timeout: {job['step']} ran over {limit:.0f} s"
        return None

    def _watch(self) -> None:
        conn = connect(paths.db_path(self._cfg))
        try:
            while not self._stopping.wait(self._cfg.limits.watchdog_interval_s):
                try:
                    reason = self.check(conn)
                    if reason:
                        self.restart(reason)
                except Exception:  # the watchdog itself must never die
                    log.error("watchdog tick failed", exc_info=True)
                    time.sleep(self._cfg.limits.watchdog_interval_s)
        finally:
            conn.close()
