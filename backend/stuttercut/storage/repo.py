"""Repository functions over the SQLite schema. Plain SQL, no ORM; each write commits."""

import sqlite3
import uuid
from datetime import UTC, datetime

from stuttercut.asr import Word
from stuttercut.rules import Cut

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


def replace_cuts(conn: sqlite3.Connection, job_id: str, cuts: list[Cut]) -> int:
    """Replace the job's detected cuts; cuts the user kept (kept=1) are never touched.

    A new cut that overlaps a kept one by more than half of itself is skipped, so a re-run
    does not suggest again what the user already restored. Returns how many were stored.
    """
    with conn:
        conn.execute("DELETE FROM cut WHERE job_id = ? AND kept = 0", (job_id,))
        kept = conn.execute(
            "SELECT start_s, end_s FROM cut WHERE job_id = ? AND kept = 1", (job_id,)
        ).fetchall()
        fresh = [
            c
            for c in cuts
            if not any(
                min(c.end, k["end_s"]) - max(c.start, k["start_s"]) > (c.end - c.start) / 2
                for k in kept
            )
        ]
        conn.executemany(
            "INSERT INTO cut (job_id, start_s, end_s, reason, source, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(job_id, c.start, c.end, c.reason, c.source, c.confidence) for c in fresh],
        )
    return len(fresh)


def get_cuts(conn: sqlite3.Connection, job_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM cut WHERE job_id = ? ORDER BY start_s", (job_id,)))


def set_cut_kept(conn: sqlite3.Connection, cut_id: int, kept: bool) -> None:
    with conn:
        conn.execute("UPDATE cut SET kept = ? WHERE id = ?", (int(kept), cut_id))


def cut_counts(conn: sqlite3.Connection, job_id: str, by: str) -> dict[str, int]:
    """Active (not kept) cuts per ``reason`` or per ``source``."""
    if by not in ("reason", "source"):
        raise ValueError(f"by must be reason or source, got {by!r}")
    rows = conn.execute(
        f"SELECT {by} AS k, COUNT(*) AS n FROM cut WHERE job_id = ? AND kept = 0 GROUP BY {by}",
        (job_id,),
    )
    return {r["k"]: r["n"] for r in rows}
