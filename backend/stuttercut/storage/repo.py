"""Repository functions over the SQLite schema. Plain SQL, no ORM; each write commits."""

import sqlite3
import uuid
from datetime import UTC, datetime

from stuttercut.asr import Word
from stuttercut.rules import Cut, tier

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
    allowed = {
        "duration_s", "output_path", "xml_path", "peak_rss_mb",
        "llm_input_tokens", "llm_output_tokens", "llm_cost_usd",
    }  # fmt: skip
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


def replace_cuts(
    conn: sqlite3.Connection, job_id: str, cuts: list[Cut], sure_min: float = 0.7
) -> int:
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
            "INSERT INTO cut (job_id, start_s, end_s, reason, source, confidence, tier,"
            " rule_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    job_id,
                    c.start,
                    c.end,
                    c.reason,
                    c.source,
                    c.confidence,
                    tier(c.confidence, sure_min),
                    c.confidence,
                )
                for c in fresh
            ],
        )
    return len(fresh)


def apply_review(
    conn: sqlite3.Connection,
    cut_id: int,
    confidence: float,
    tier_: str,
    verdict: str,
    llm_confidence: float,
    reason: str,
) -> None:
    """Store the LLM verdict and the combined confidence on one cut (the cut stays)."""
    with conn:
        conn.execute(
            "UPDATE cut SET confidence = ?, tier = ?, llm_verdict = ?, llm_confidence = ?,"
            " llm_reason = ? WHERE id = ?",
            (confidence, tier_, verdict, llm_confidence, reason, cut_id),
        )


def add_llm_cut(conn: sqlite3.Connection, job_id: str, cut: Cut, tier_: str, reason: str) -> None:
    """A cut proposed by the LLM itself (source=llm): no rule confidence."""
    with conn:
        conn.execute(
            "INSERT INTO cut (job_id, start_s, end_s, reason, source, confidence, tier,"
            " llm_verdict, llm_confidence, llm_reason) VALUES (?, ?, ?, ?, ?, ?, ?, 'cut', ?, ?)",
            (job_id, cut.start, cut.end, cut.reason, cut.source, cut.confidence, tier_,
             cut.confidence, reason),
        )  # fmt: skip


def get_cuts(conn: sqlite3.Connection, job_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM cut WHERE job_id = ? ORDER BY start_s", (job_id,)))


def set_cut_kept(conn: sqlite3.Connection, cut_id: int, kept: bool) -> None:
    with conn:
        conn.execute("UPDATE cut SET kept = ? WHERE id = ?", (int(kept), cut_id))


def cut_counts(conn: sqlite3.Connection, job_id: str, by: str) -> dict[str, int]:
    """Active (not kept) cuts per ``reason``, ``source`` or ``tier``."""
    if by not in ("reason", "source", "tier"):
        raise ValueError(f"by must be reason, source or tier, got {by!r}")
    rows = conn.execute(
        f"SELECT {by} AS k, COUNT(*) AS n FROM cut WHERE job_id = ? AND kept = 0 GROUP BY {by}",
        (job_id,),
    )
    return {r["k"]: r["n"] for r in rows}


APPROVE_MODES = ("sure", "all", "none")


def approve_cuts(conn: sqlite3.Connection, job_id: str, mode: str) -> int:
    """Mark which active cuts (kept=0) render applies: sure tier, all, or none. Returns count."""
    if mode not in APPROVE_MODES:
        raise ValueError(f"approve must be one of {APPROVE_MODES}, got {mode!r}")
    with conn:
        conn.execute(
            "UPDATE cut SET approved = CASE WHEN kept = 0 AND (? = 'all' OR (? = 'sure'"
            " AND tier = 'sure')) THEN 1 ELSE 0 END WHERE job_id = ?",
            (mode, mode, job_id),
        )
    return len(approved_cuts(conn, job_id))


def approved_cuts(conn: sqlite3.Connection, job_id: str) -> list[tuple[float, float]]:
    """(start, end) of the cuts render applies: approved and not kept by the user."""
    rows = conn.execute(
        "SELECT start_s, end_s FROM cut WHERE job_id = ? AND approved = 1 AND kept = 0"
        " ORDER BY start_s",
        (job_id,),
    )
    return [(r["start_s"], r["end_s"]) for r in rows]


def latest_job(conn: sqlite3.Connection) -> str | None:
    """Newest job that can be rendered (ready_for_review, done, or failed at render)."""
    row = conn.execute(
        "SELECT id FROM job WHERE status IN ('ready_for_review', 'done')"
        " OR (status = 'failed' AND failed_step = 'render') ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row["id"])


def clear_llm_cuts(conn: sqlite3.Connection, job_id: str) -> None:
    """Remove cuts the LLM proposed (not kept) before a new review."""
    with conn:
        conn.execute("DELETE FROM cut WHERE job_id = ? AND source = 'llm' AND kept = 0", (job_id,))
