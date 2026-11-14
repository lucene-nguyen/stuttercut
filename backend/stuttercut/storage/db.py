"""SQLite connection and schema migrations (ADR 0004). Schema version = PRAGMA user_version."""

import sqlite3
from pathlib import Path

# Append-only: never edit a released migration; add a new one.
MIGRATIONS: list[str] = [
    # 1: job, word, span (design doc "Data model"; word.variant added by ADR 0002)
    """
    CREATE TABLE job (
        id           TEXT PRIMARY KEY,
        source_path  TEXT NOT NULL,
        duration_s   REAL,
        status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
                         'queued', 'processing', 'transcribed', 'ready_for_review',
                         'rendering', 'done', 'failed', 'cancelled')),
        failed_step  TEXT,
        error        TEXT,
        output_path  TEXT,
        peak_rss_mb  INTEGER,
        created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    CREATE TABLE word (
        id       INTEGER PRIMARY KEY,
        job_id   TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
        variant  TEXT NOT NULL CHECK (variant IN ('verbatim', 'intended')),
        idx      INTEGER NOT NULL,
        text     TEXT NOT NULL,
        start_s  REAL NOT NULL,
        end_s    REAL NOT NULL,
        UNIQUE (job_id, variant, idx)
    );
    CREATE TABLE span (
        id          INTEGER PRIMARY KEY,
        job_id      TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
        step        TEXT NOT NULL,
        started_at  TEXT NOT NULL,
        duration_s  REAL NOT NULL,
        status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
        error       TEXT
    );
    CREATE INDEX span_job ON span(job_id);
    """,
    # 2: cut (design doc "Data model" + confidence; LEARNING-207)
    """
    CREATE TABLE cut (
        id          INTEGER PRIMARY KEY,
        job_id      TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
        start_s     REAL NOT NULL,
        end_s       REAL NOT NULL CHECK (end_s > start_s),
        reason      TEXT NOT NULL CHECK (reason IN ('filler', 'repeat', 'pause', 'retake')),
        source      TEXT NOT NULL CHECK (source IN ('rules', 'vad', 'diff', 'llm')),
        confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        kept        INTEGER NOT NULL DEFAULT 0 CHECK (kept IN (0, 1))
    );
    CREATE INDEX cut_job ON cut(job_id);
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) and migrate. WAL: API and worker processes share the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order; returns the schema version."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        try:  # one transaction per migration, version bump included
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
    return len(MIGRATIONS)
