"""Repository functions over the SQLite schema. Plain SQL, no ORM; each write commits."""

import sqlite3
import uuid
from datetime import UTC, datetime

from stuttercut.asr import Word
from stuttercut.rules import Cut, tier

VARIANTS = ("verbatim", "intended")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_job(
    conn: sqlite3.Connection,
    source_path: str,
    options: str | None = None,
    job_id: str | None = None,
) -> str:
    """``options``: detection options from the upload form, as JSON (None = defaults)."""
    job_id = job_id or uuid.uuid4().hex[:12]
    with conn:
        conn.execute(
            "INSERT INTO job (id, source_path, options) VALUES (?, ?, ?)",
            (job_id, source_path, options),
        )
    return job_id


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,)))


def set_step(conn: sqlite3.Connection, job_id: str, step: str | None) -> None:
    """The step running now (None when it ends), for progress in the UI."""
    with conn:
        conn.execute(
            "UPDATE job SET step = ?, step_started_at = ? WHERE id = ?",
            (step, now_iso() if step else None, job_id),
        )


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
    """Replace the job's detected cuts; cuts the user decided on are never touched.

    Kept, approved and hand-marked (source user) cuts stay. A new cut that overlaps one of
    them by more than half of itself is skipped, so a re-run does not suggest again what the
    user already decided. Returns how many were stored.
    """
    with conn:
        conn.execute(
            "DELETE FROM cut WHERE job_id = ? AND kept = 0 AND approved = 0 AND source != 'user'",
            (job_id,),
        )
        kept = conn.execute("SELECT start_s, end_s FROM cut WHERE job_id = ?", (job_id,)).fetchall()
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


def decide(conn: sqlite3.Connection, job_id: str, cut_ids: list[int], keep: bool) -> int:
    """The user's decision: keep (not cut) or cut (approved for render), with a timestamp."""
    if not cut_ids:
        return 0
    marks = ",".join("?" * len(cut_ids))
    with conn:
        cur = conn.execute(
            "UPDATE cut SET kept = ?, approved = ?, decided_at = ?"
            f" WHERE job_id = ? AND id IN ({marks})",
            (int(keep), int(not keep), now_iso(), job_id, *cut_ids),
        )
    return cur.rowcount


def add_user_cut(
    conn: sqlite3.Connection, job_id: str, start: float, end: float, reason: str
) -> int:
    """A cut the detector missed, marked by hand: approved at once (source user)."""
    with conn:
        cur = conn.execute(
            "INSERT INTO cut (job_id, start_s, end_s, reason, source, confidence, tier, approved,"
            " decided_at) VALUES (?, ?, ?, ?, 'user', 1.0, 'sure', 1, ?)",
            (job_id, start, end, reason, now_iso()),
        )
    return int(cur.lastrowid or 0)


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


def approved_cuts(
    conn: sqlite3.Connection, job_id: str
) -> list[tuple[float, float, bool, bool, bool]]:
    """(start, end, start_edited, end_edited, is_pause) of the cuts render applies."""
    rows = conn.execute(
        "SELECT start_s, end_s, start_edited, end_edited, reason FROM cut"
        " WHERE job_id = ? AND approved = 1 AND kept = 0 ORDER BY start_s",
        (job_id,),
    )
    return [(r["start_s"], r["end_s"], bool(r["start_edited"]), bool(r["end_edited"]),
             r["reason"] == "pause") for r in rows]  # fmt: skip


def set_cut_edges(
    conn: sqlite3.Connection, job_id: str, cut_id: int, start: float, end: float
) -> int:
    """Move a cut's edges; an edge differs from the original = edited. Approves the cut."""
    with conn:
        cur = conn.execute(
            "UPDATE cut SET start_s = ?, end_s = ?,"
            " start_edited = abs(? - orig_start_s) > 1e-6, end_edited = abs(? - orig_end_s) > 1e-6,"
            " approved = 1, kept = 0, decided_at = ? WHERE job_id = ? AND id = ?",
            (start, end, start, end, now_iso(), job_id, cut_id),
        )
    return cur.rowcount


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
