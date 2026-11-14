"""One SPAN row per pipeline step: job_id, step, started_at, duration_s, status, error."""

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager

from stuttercut.storage import repo

log = logging.getLogger(__name__)


@contextmanager
def span(conn: sqlite3.Connection, job_id: str, step: str) -> Iterator[None]:
    """Record the step as ok, or as error (and re-raise) if the block raises."""
    started_at = repo.now_iso()
    t0 = time.perf_counter()
    log.info("step started", extra={"job_id": job_id, "step": step})
    try:
        yield
    except BaseException as e:
        duration = round(time.perf_counter() - t0, 3)
        repo.insert_span(
            conn, job_id, step, started_at, duration, "error", f"{type(e).__name__}: {e}"
        )
        raise
    duration = round(time.perf_counter() - t0, 3)
    repo.insert_span(conn, job_id, step, started_at, duration, "ok")
    log.info("step done", extra={"job_id": job_id, "step": step, "duration_s": duration})
