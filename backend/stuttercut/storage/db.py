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
    # 3: LLM review (LEARNING-208). confidence becomes the final confidence; the rule's own
    # stays in rule_confidence (NULL for cuts the LLM proposed).
    """
    ALTER TABLE cut ADD COLUMN tier TEXT NOT NULL DEFAULT 'unsure'
        CHECK (tier IN ('sure', 'unsure'));
    ALTER TABLE cut ADD COLUMN rule_confidence REAL;
    ALTER TABLE cut ADD COLUMN llm_verdict TEXT CHECK (llm_verdict IN ('cut', 'keep'));
    ALTER TABLE cut ADD COLUMN llm_confidence REAL;
    ALTER TABLE cut ADD COLUMN llm_reason TEXT;
    UPDATE cut SET rule_confidence = confidence;
    ALTER TABLE job ADD COLUMN llm_input_tokens INTEGER;
    ALTER TABLE job ADD COLUMN llm_output_tokens INTEGER;
    ALTER TABLE job ADD COLUMN llm_cost_usd REAL;
    """,
    # 4: render (LEARNING-210). approved = the cut counts for render (CLI --approve now, the
    # review UI later); job.output_path holds the MP4, xml_path the FCP XML.
    """
    ALTER TABLE cut ADD COLUMN approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1));
    ALTER TABLE job ADD COLUMN xml_path TEXT;
    """,
    # 5: review UI (LEARNING-209). SQLite cannot change a CHECK, so cut is rebuilt to allow
    # source 'user' (a cut marked by hand) and to record when the user decided (decided_at).
    # job.options = detection options from the upload form (JSON); step/step_started_at = the
    # step running now, for progress.
    """
    CREATE TABLE cut_new (
        id               INTEGER PRIMARY KEY,
        job_id           TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
        start_s          REAL NOT NULL,
        end_s            REAL NOT NULL CHECK (end_s > start_s),
        reason           TEXT NOT NULL CHECK (reason IN ('filler', 'repeat', 'pause', 'retake')),
        source           TEXT NOT NULL CHECK (source IN ('rules', 'vad', 'diff', 'llm', 'user')),
        confidence       REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        kept             INTEGER NOT NULL DEFAULT 0 CHECK (kept IN (0, 1)),
        tier             TEXT NOT NULL DEFAULT 'unsure' CHECK (tier IN ('sure', 'unsure')),
        rule_confidence  REAL,
        llm_verdict      TEXT CHECK (llm_verdict IN ('cut', 'keep')),
        llm_confidence   REAL,
        llm_reason       TEXT,
        approved         INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
        decided_at       TEXT
    );
    INSERT INTO cut_new (id, job_id, start_s, end_s, reason, source, confidence, kept, tier,
                         rule_confidence, llm_verdict, llm_confidence, llm_reason, approved)
        SELECT id, job_id, start_s, end_s, reason, source, confidence, kept, tier,
               rule_confidence, llm_verdict, llm_confidence, llm_reason, approved FROM cut;
    DROP TABLE cut;
    ALTER TABLE cut_new RENAME TO cut;
    CREATE INDEX cut_job ON cut(job_id);
    ALTER TABLE job ADD COLUMN options TEXT;
    ALTER TABLE job ADD COLUMN step TEXT;
    ALTER TABLE job ADD COLUMN step_started_at TEXT;
    """,
    # 6: cut edge editing (LEARNING-209 follow-up). orig_* = the edges as detected or marked,
    # kept for eval and "Reset edges"; *_edited = the user moved that edge (no padding then).
    # A trigger fills orig_* on every insert. job.fps = the source frame rate ("30000/1001"),
    # stored once so planning does not run ffprobe on every request.
    """
    ALTER TABLE cut ADD COLUMN orig_start_s REAL;
    ALTER TABLE cut ADD COLUMN orig_end_s REAL;
    ALTER TABLE cut ADD COLUMN start_edited INTEGER NOT NULL DEFAULT 0
        CHECK (start_edited IN (0, 1));
    ALTER TABLE cut ADD COLUMN end_edited INTEGER NOT NULL DEFAULT 0
        CHECK (end_edited IN (0, 1));
    UPDATE cut SET orig_start_s = start_s, orig_end_s = end_s;
    CREATE TRIGGER cut_orig_edges AFTER INSERT ON cut WHEN NEW.orig_start_s IS NULL
    BEGIN
        UPDATE cut SET orig_start_s = NEW.start_s, orig_end_s = NEW.end_s WHERE id = NEW.id;
    END;
    ALTER TABLE job ADD COLUMN fps TEXT;
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
