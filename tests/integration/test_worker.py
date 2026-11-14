"""Worker pipeline with the fake transcriber and synthetic FFmpeg media (no model, no network)."""

import queue
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from stuttercut.asr import Transcriber
from stuttercut.asr.fake import FakeTranscriber
from stuttercut.config import Config
from stuttercut.media.audio import FFmpegError, NoAudioStreamError, TooLongError, extract_audio
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import worker_main
from stuttercut.worker.pipeline import run_job
from tests.conftest import FIXTURES

FIXTURE = FIXTURES / "synthetic_pair.json"


@pytest.fixture
def conn(cfg: Config) -> sqlite3.Connection:
    return connect(paths.db_path(cfg))


def spans(conn: sqlite3.Connection, job_id: str) -> list[tuple[str, str]]:
    return [(s["step"], s["status"]) for s in repo.get_spans(conn, job_id)]


def test_extract_audio_writes_16k_mono_wav(
    cfg: Config, make_video: Callable[..., Path], tmp_path: Path
) -> None:
    import wave

    video = make_video("bài nói thử.mp4", seconds=1.5)
    wav = tmp_path / "out dir" / "audio.wav"
    wav.parent.mkdir()
    duration = extract_audio(video, wav, cfg.media)
    assert duration == pytest.approx(1.5, abs=0.1)
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


def test_extract_audio_rejects_no_audio_and_too_long(
    cfg: Config, make_video: Callable[..., Path], tmp_path: Path
) -> None:
    with pytest.raises(NoAudioStreamError):
        extract_audio(make_video("silent.mp4", audio=False), tmp_path / "a.wav", cfg.media)
    short_limit = type(cfg.media)(max_duration_s=1.0)
    with pytest.raises(TooLongError) as err:
        extract_audio(make_video("long.mp4", seconds=2.0), tmp_path / "b.wav", short_limit)
    assert err.value.max_s == 1.0


def test_extract_audio_keeps_ffmpeg_stderr(cfg: Config, tmp_path: Path) -> None:
    from tests.conftest import HAS_FFMPEG

    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not on PATH")
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(FFmpegError) as err:
        extract_audio(broken, tmp_path / "c.wav", cfg.media)
    assert err.value.stderr  # FFmpeg's own message is kept for the log


def test_run_job_happy_path(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video()))
    fake = FakeTranscriber(FIXTURE)

    assert run_job(conn, cfg, job_id, fake) == "transcribed"

    job = repo.get_job(conn, job_id)
    assert job is not None
    assert job["status"] == "transcribed" and job["failed_step"] is None
    assert job["duration_s"] == pytest.approx(2.0, abs=0.1) and job["peak_rss_mb"] > 0
    assert repo.word_counts(conn, job_id) == {"verbatim": 8, "intended": 6}
    assert repo.get_words(conn, job_id, "verbatim")[0].text == "ờ"
    assert spans(conn, job_id) == [("extract_audio", "ok"), ("transcribe", "ok")]
    assert fake.calls == [paths.job_dir(cfg, job_id) / "audio.wav"]


def test_run_job_transcribe_failure(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video()))
    fake = FakeTranscriber(FIXTURE, error=RuntimeError("CUDA out of memory"))

    assert run_job(conn, cfg, job_id, fake) == "failed"

    job = repo.get_job(conn, job_id)
    assert job is not None
    assert (job["status"], job["failed_step"]) == ("failed", "transcribe")
    assert job["error"] == "RuntimeError: CUDA out of memory"
    assert spans(conn, job_id) == [("extract_audio", "ok"), ("transcribe", "error")]
    assert repo.word_counts(conn, job_id) == {"verbatim": 0, "intended": 0}


def test_run_job_media_failure(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video("silent.mp4", audio=False)))
    fake = FakeTranscriber(FIXTURE)

    assert run_job(conn, cfg, job_id, fake) == "failed"

    job = repo.get_job(conn, job_id)
    assert job is not None and job["failed_step"] == "extract_audio"
    assert job["error"].startswith("NoAudioStreamError")
    assert fake.calls == []


def test_worker_main_runs_queued_jobs_one_at_a_time(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    ok_job = repo.create_job(conn, str(make_video("a.mp4")))
    bad_job = repo.create_job(conn, str(make_video("b.mp4", audio=False)))
    jobs: queue.Queue[str | None] = queue.Queue()
    for item in (ok_job, bad_job, None):
        jobs.put(item)
    loads: list[Config] = []

    def make(c: Config) -> Transcriber:
        loads.append(c)
        return FakeTranscriber(FIXTURE)

    worker_main(jobs, cfg, make)

    assert len(loads) == 1  # model loaded once, reused for every job
    statuses = {j: repo.get_job(conn, j)["status"] for j in (ok_job, bad_job)}  # type: ignore[index]
    assert statuses == {ok_job: "transcribed", bad_job: "failed"}
    assert (paths.log_dir(cfg) / "app.jsonl").exists()


def test_worker_main_fails_jobs_when_model_cannot_load(
    cfg: Config, conn: sqlite3.Connection
) -> None:
    from stuttercut.platform import InsufficientMemoryError

    job_id = repo.create_job(conn, "never-read.mp4")
    jobs: queue.Queue[str | None] = queue.Queue()
    jobs.put(job_id)
    jobs.put(None)

    def make(c: Config) -> Transcriber:
        raise InsufficientMemoryError("only 2.0 GB RAM free")

    worker_main(jobs, cfg, make)

    job = repo.get_job(conn, job_id)
    assert job is not None
    assert (job["status"], job["failed_step"]) == ("failed", "load_model")
    assert "InsufficientMemoryError" in job["error"]
