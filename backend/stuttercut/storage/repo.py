"""Repository functions over the SQLite schema. Plain SQL, no ORM; each write commits."""

import sqlite3
import uuid
from datetime import UTC, datetime

from stuttercut.asr import Word

VARIANTS = ("verbatim", "intended")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_job(conn: sqlite3.Connection, source_path: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with conn:
        conn.execute("INSERT INTO job (id, source_path) VALUES (?, ?)", (job_id, source_path))
    return job_id


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return row


def set_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    failed_step: str | None = None,
    error: str | None = None,
) -> None:
    """Moving to any status other than failed clears failed_step and error (e.g. on retry)."""
    with conn:
        conn.execute(
            "UPDATE job SET status = ?, failed_step = ?, error = ? WHERE id = ?",
            (status, failed_step, error, job_id),
        )


def update_job(conn: sqlite3.Connection, job_id: str, **fields: object) -> None:
    allowed = {"duration_s", "output_path", "peak_rss_mb"}
    if not fields or not set(fields) <= allowed:
        raise ValueError(f"update_job accepts only {sorted(allowed)}, got {sorted(fields)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with conn:
        conn.execute(f"UPDATE job SET {assignments} WHERE id = ?", (*fields.values(), job_id))


def replace_words(conn: sqlite3.Connection, job_id: str, variant: str, words: list[Word]) -> None:
    """Store one variant's words, replacing any from an earlier attempt (retry-safe)."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
    with conn:
        conn.execute("DELETE FROM word WHERE job_id = ? AND variant = ?", (job_id, variant))
        conn.executemany(
            "INSERT INTO word (job_id, variant, idx, text, start_s, end_s)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(job_id, variant, i, w.text, w.start, w.end) for i, w in enumerate(words)],
        )


def get_words(conn: sqlite3.Connection, job_id: str, variant: str) -> list[Word]:
    rows = conn.execute(
        "SELECT text, start_s, end_s FROM word WHERE job_id = ? AND variant = ? ORDER BY idx",
        (job_id, variant),
    )
    return [Word(text=r["text"], start=r["start_s"], end=r["end_s"]) for r in rows]


def word_counts(conn: sqlite3.Connection, job_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT variant, COUNT(*) AS n FROM word WHERE job_id = ? GROUP BY variant", (job_id,)
    )
    counts = dict.fromkeys(VARIANTS, 0)
    counts.update({r["variant"]: r["n"] for r in rows})
    return counts


def insert_span(
    conn: sqlite3.Connection,
    job_id: str,
    step: str,
    started_at: str,
    duration_s: float,
    status: str,
    error: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO span (job_id, step, started_at, duration_s, status, error)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, step, started_at, duration_s, status, error),
        )


def get_spans(conn: sqlite3.Connection, job_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM span WHERE job_id = ? ORDER BY id", (job_id,)))
