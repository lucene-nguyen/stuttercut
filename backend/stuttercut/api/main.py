"""API server (process 1). Run: uvicorn stuttercut.api.main:app --host 127.0.0.1

The app starts the worker process (process 2) and stops it on shutdown. Tests build their own
app with ``create_app(cfg, worker=...)``.
"""

import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from stuttercut.api.routes import health, jobs, observability
from stuttercut.api.worker_proc import WorkerHandle, fail_running, pending_messages
from stuttercut.config import Config, load_config
from stuttercut.observability.logging import setup_logging
from stuttercut.storage import paths
from stuttercut.storage.db import connect
from stuttercut.worker.main import Message


class Worker(Protocol):
    def start(self) -> None: ...
    def put(self, msg: Message) -> None: ...
    def stop(self, timeout_s: float = 5.0) -> None: ...


def reveal_in_file_manager(path: Path) -> None:
    """Finder (macOS) / Explorer (Windows) with the file selected; the folder elsewhere."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def open_in_file_manager(folder: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def create_app(
    cfg: Config | None = None,
    worker: Worker | None = None,
    reveal: Callable[[Path], None] = reveal_in_file_manager,
    open_folder: Callable[[Path], None] = open_in_file_manager,
) -> FastAPI:
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(paths.log_dir(cfg), cfg.log, "api")
        conn = connect(paths.db_path(cfg))  # migrate before the worker opens the DB
        try:  # after a crash or restart: what was running failed; what was waiting runs
            fail_running(conn, "interrupted: StutterCut stopped while this step ran")
            pending = pending_messages(conn)
        finally:
            conn.close()
        app.state.worker.start()
        for msg in pending:
            app.state.worker.put(msg)
        yield
        app.state.worker.stop()

    app = FastAPI(title="StutterCut", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.worker = worker or WorkerHandle(cfg)
    app.state.reveal = reveal
    app.state.open_folder = open_folder
    app.state.sse_interval_s = 0.5
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(observability.router)
    return app


app = create_app()
