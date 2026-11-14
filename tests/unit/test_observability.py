import json
import logging
import sqlite3
from pathlib import Path

import pytest

from stuttercut.config import LogConfig
from stuttercut.observability.logging import setup_logging
from stuttercut.observability.metrics import PeakRss
from stuttercut.observability.spans import span
from stuttercut.storage import repo
from stuttercut.storage.db import connect


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "s.db")


def test_span_records_ok_and_error(conn: sqlite3.Connection) -> None:
    job_id = repo.create_job(conn, "a.mp4")
    with span(conn, job_id, "extract_audio"):
        pass
    with pytest.raises(RuntimeError, match="no GPU"), span(conn, job_id, "transcribe"):
        raise RuntimeError("no GPU")

    ok, err = repo.get_spans(conn, job_id)
    assert (ok["step"], ok["status"], ok["error"]) == ("extract_audio", "ok", None)
    assert (err["step"], err["status"], err["error"]) == (
        "transcribe",
        "error",
        "RuntimeError: no GPU",
    )
    assert err["duration_s"] >= 0 and err["started_at"].endswith("Z")


def test_json_lines_logging_with_context_and_rotation(tmp_path: Path) -> None:
    path = setup_logging(tmp_path / "logs", LogConfig(max_bytes=2000, backup_count=2))
    log = logging.getLogger("stuttercut.test")
    try:
        log.info("step done", extra={"job_id": "abc", "step": "transcribe", "duration_s": 1.5})
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert first["msg"] == "step done" and first["level"] == "INFO"
        assert (first["job_id"], first["step"], first["duration_s"]) == ("abc", "transcribe", 1.5)

        for i in range(200):
            log.info("filler line %d with tiếng Việt", i, extra={"job_id": "abc"})
        files = sorted(p.name for p in path.parent.iterdir())
        assert files == ["app.jsonl", "app.jsonl.1", "app.jsonl.2"]  # 1 live + backup_count
        assert path.stat().st_size <= 2000
    finally:
        for h in list(logging.getLogger("stuttercut").handlers):
            logging.getLogger("stuttercut").removeHandler(h)
            h.close()


def test_peak_rss_sees_allocation() -> None:
    with PeakRss(interval_s=0.01) as rss:
        block = bytearray(50 * 2**20)
        before_exit = rss.peak_mb
    assert rss.peak_mb >= before_exit > 0
    assert len(block) == 50 * 2**20
