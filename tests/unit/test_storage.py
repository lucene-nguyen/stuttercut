import sqlite3
from pathlib import Path

import pytest

from stuttercut.asr import Word
from stuttercut.storage import repo
from stuttercut.storage.db import MIGRATIONS, connect, migrate


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "db" / "stuttercut.db")


def test_migrations_create_schema_and_version(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(word)")}
    assert columns == {"id", "job_id", "variant", "idx", "text", "start_s", "end_s"}
    span_cols = {r["name"] for r in conn.execute("PRAGMA table_info(span)")}
    assert span_cols == {"id", "job_id", "step", "started_at", "duration_s", "status", "error"}
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrate_is_idempotent_and_reopen_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    conn = connect(path)
    job_id = repo.create_job(conn, "a.mp4")
    assert migrate(conn) == len(MIGRATIONS)
    conn.close()
    assert repo.get_job(connect(path), job_id) is not None


def test_job_lifecycle(conn: sqlite3.Connection) -> None:
    job_id = repo.create_job(conn, "C:/videos/bài 1.mp4")
    job = repo.get_job(conn, job_id)
    assert job is not None and job["status"] == "queued" and job["created_at"].endswith("Z")

    repo.set_status(conn, job_id, "failed", failed_step="transcribe", error="boom")
    repo.update_job(conn, job_id, duration_s=12.5, peak_rss_mb=900)
    job = repo.get_job(conn, job_id)
    assert job is not None
    assert (job["status"], job["failed_step"], job["error"]) == ("failed", "transcribe", "boom")
    assert (job["duration_s"], job["peak_rss_mb"]) == (12.5, 900)

    repo.set_status(conn, job_id, "processing")  # retry clears the failure
    job = repo.get_job(conn, job_id)
    assert job is not None and job["failed_step"] is None and job["error"] is None


def test_constraints_reject_bad_values(conn: sqlite3.Connection) -> None:
    job_id = repo.create_job(conn, "a.mp4")
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_status(conn, job_id, "exploded")
    with pytest.raises(ValueError, match="variant"):
        repo.replace_words(conn, job_id, "both", [])
    with pytest.raises(ValueError, match="update_job accepts only"):
        repo.update_job(conn, job_id, status="done")
    with pytest.raises(sqlite3.IntegrityError):  # foreign key
        repo.replace_words(conn, "no-such-job", "verbatim", [Word("a", 0.0, 1.0)])


def test_replace_words_is_retry_safe(conn: sqlite3.Connection) -> None:
    job_id = repo.create_job(conn, "a.mp4")
    first = [Word("ờ", 0.1, 0.3), Word("tôi", 0.4, 0.6)]
    repo.replace_words(conn, job_id, "verbatim", first)
    repo.replace_words(conn, job_id, "verbatim", first[1:])
    repo.replace_words(conn, job_id, "intended", first[1:])
    assert repo.get_words(conn, job_id, "verbatim") == first[1:]
    assert repo.word_counts(conn, job_id) == {"verbatim": 1, "intended": 1}


def test_migration_2_adds_cut_table(conn: sqlite3.Connection) -> None:
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(cut)")}
    assert columns == {"id", "job_id", "start_s", "end_s", "reason", "source", "confidence", "kept"}


def test_migrate_from_version_1_keeps_jobs(tmp_path: Path) -> None:
    raw = sqlite3.connect(tmp_path / "old.db")
    raw.executescript(MIGRATIONS[0] + "\nPRAGMA user_version = 1;")
    raw.execute("INSERT INTO job (id, source_path) VALUES ('old1', 'a.mp4')")
    raw.commit()
    raw.close()

    conn = connect(tmp_path / "old.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert repo.get_job(conn, "old1") is not None
    assert repo.get_cuts(conn, "old1") == []


def test_replace_cuts_keeps_user_restored_ones(conn: sqlite3.Connection) -> None:
    from stuttercut.rules import Cut

    job_id = repo.create_job(conn, "a.mp4")
    first = [Cut(0.0, 0.3, "filler", "rules", 0.9), Cut(1.0, 2.0, "pause", "rules", 0.6)]
    assert repo.replace_cuts(conn, job_id, first) == 2
    restored = repo.get_cuts(conn, job_id)[1]
    repo.set_cut_kept(conn, restored["id"], True)

    again = [Cut(0.0, 0.3, "filler", "rules", 0.9), Cut(1.1, 1.9, "pause", "vad", 0.9)]
    assert repo.replace_cuts(conn, job_id, again) == 1  # the pause overlaps the kept one
    rows = repo.get_cuts(conn, job_id)
    assert [(r["reason"], r["kept"]) for r in rows] == [("filler", 0), ("pause", 1)]
    assert repo.cut_counts(conn, job_id, "reason") == {"filler": 1}  # kept ones not counted
    assert repo.cut_counts(conn, job_id, "source") == {"rules": 1}
    with pytest.raises(ValueError, match="by must be"):
        repo.cut_counts(conn, job_id, "kept")
    with pytest.raises(sqlite3.IntegrityError):
        repo.replace_cuts(conn, job_id, [Cut(1.0, 1.0, "filler", "rules", 0.5)])
