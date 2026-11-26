"""Shared contract-test fixtures: the API with an in-process worker (fake transcriber)."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stuttercut.api.main import create_app
from stuttercut.asr.fake import FakeTranscriber
from stuttercut.config import Config
from stuttercut.storage import paths
from stuttercut.storage.db import connect
from stuttercut.worker.main import Message, handle
from tests.conftest import FIXTURES

FIXTURE = FIXTURES / "review_clip.json"


class InlineWorker:
    """Runs each message at once in this process (the real one is a separate process)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg, self.msgs, self.paused = cfg, [], False
        self.transcriber = FakeTranscriber(FIXTURE)

    def start(self) -> None: ...

    def stop(self, timeout_s: float = 5.0) -> None: ...

    def put(self, msg: Message) -> None:
        self.msgs.append(msg)
        if not self.paused:
            conn = connect(paths.db_path(self.cfg))
            handle(conn, self.cfg, msg, self.transcriber)
            conn.close()


@pytest.fixture
def api(cfg: Config) -> Iterator[tuple[TestClient, InlineWorker, list[Path]]]:
    worker, revealed = InlineWorker(cfg), []
    app = create_app(cfg, worker=worker, reveal=revealed.append, open_folder=revealed.append)
    app.state.sse_interval_s = 0.01
    with TestClient(app) as client:
        yield client, worker, revealed


def upload(client: TestClient, video: Path, options: dict[str, Any] | None = None) -> Any:
    params: dict[str, str] = {"name": video.name}
    if options is not None:
        params["options"] = json.dumps(options)
    return client.post("/api/jobs", params=params, content=video.read_bytes())


def db(cfg: Config) -> sqlite3.Connection:
    return connect(paths.db_path(cfg))


Api = tuple[TestClient, InlineWorker, list[Path]]
