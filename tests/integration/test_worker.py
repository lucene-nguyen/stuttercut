"""Worker pipeline with the fake transcriber and synthetic FFmpeg media (no model, no network)."""

import queue
import sqlite3
from collections.abc import Callable
from dataclasses import replace
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

    assert run_job(conn, cfg, job_id, fake) == "ready_for_review"

    job = repo.get_job(conn, job_id)
    assert job is not None
    assert job["status"] == "ready_for_review" and job["failed_step"] is None
    assert job["duration_s"] == pytest.approx(2.0, abs=0.1) and job["peak_rss_mb"] > 0
    assert repo.word_counts(conn, job_id) == {"verbatim": 8, "intended": 0}  # verbatim only
    assert repo.get_words(conn, job_id, "verbatim")[0].text == "ờ"
    assert spans(conn, job_id) == [("extract_audio", "ok"), ("transcribe", "ok"), ("detect", "ok")]
    # fixture: "ờ" filler + "tôi tôi" repeat, found from words alone (no VAD)
    assert repo.cut_counts(conn, job_id, "reason") == {"filler": 1, "repeat": 1}
    assert fake.calls == [paths.job_dir(cfg, job_id) / "audio.wav"]


def test_run_job_dual_then_verbatim_retry(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video()))

    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE, passes="dual")) == "ready_for_review"
    assert repo.word_counts(conn, job_id) == {"verbatim": 8, "intended": 6}

    # A verbatim-only rerun must not leave the earlier intended words behind.
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE)) == "ready_for_review"
    assert repo.word_counts(conn, job_id) == {"verbatim": 8, "intended": 0}


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

    worker_main(jobs, cfg, make, make_vad=lambda c: None)

    assert len(loads) == 1  # model loaded once, reused for every job
    statuses = {j: repo.get_job(conn, j)["status"] for j in (ok_job, bad_job)}  # type: ignore[index]
    assert statuses == {ok_job: "ready_for_review", bad_job: "failed"}
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

    worker_main(jobs, cfg, make, make_vad=lambda c: None)

    job = repo.get_job(conn, job_id)
    assert job is not None
    assert (job["status"], job["failed_step"]) == ("failed", "load_model")
    assert "InsufficientMemoryError" in job["error"]


class FakeVad:
    """Hears speech in one 400 ms stretch that no fixture word covers (2.1-2.5 s)."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def voiced(self, wav: Path) -> list[tuple[float, float]]:
        if self.error:
            raise self.error
        assert wav.name == "audio.wav"
        return [(0.1, 1.95), (2.1, 2.5)]


def test_detect_uses_vad_and_rerun_keeps_user_choices(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    from stuttercut.worker.pipeline import run_detect

    job_id = repo.create_job(conn, str(make_video(seconds=3.0)))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), FakeVad()) == "ready_for_review"
    assert repo.cut_counts(conn, job_id, "source") == {"rules": 2, "vad": 1}

    kept = next(c for c in repo.get_cuts(conn, job_id) if c["source"] == "vad")
    repo.set_cut_kept(conn, kept["id"], True)  # the user restores the VAD suggestion
    assert run_detect(conn, cfg, job_id, FakeVad()) == "ready_for_review"

    cuts = repo.get_cuts(conn, job_id)
    assert len(cuts) == 3 and [c["kept"] for c in cuts if c["source"] == "vad"] == [1]
    assert spans(conn, job_id)[-1] == ("detect", "ok")


def test_detect_survives_vad_failure(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video()))
    vad = FakeVad(error=RuntimeError("bad audio"))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), vad) == "ready_for_review"
    assert repo.cut_counts(conn, job_id, "source") == {"rules": 2}


def _llm_judges_all(prompt: str) -> str:
    """Fake LLM: keeps every filler, cuts everything else, proposes one retake (words 5-6)."""
    import json

    verdicts = []
    for line in prompt.splitlines():
        if line.startswith("{"):
            cand = json.loads(line)
            keep = cand["reason"] == "filler"
            verdicts.append({"id": cand["id"], "verdict": "keep" if keep else "cut",
                             "confidence": 0.9, "reason": "test"})  # fmt: skip
    retakes = [{"first_word": 5, "last_word": 6, "confidence": 0.8, "reason": "restart"}]
    return json.dumps({"verdicts": verdicts, "retakes": retakes})


def test_llm_review_disabled_keeps_rules_only_tiers(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    job_id = repo.create_job(conn, str(make_video()))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), None, None) == "ready_for_review"
    assert "llm_review" not in [s for s, _ in spans(conn, job_id)]
    assert repo.cut_counts(conn, job_id, "tier") == {"sure": 2}  # rule confidence 0.9 / 0.8
    assert all(c["llm_verdict"] is None for c in repo.get_cuts(conn, job_id))


def test_llm_review_updates_tiers_and_adds_retakes(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    from stuttercut.llm.fake import FakeLLMClient

    video = make_video("bài nói.mp4")
    job_id = repo.create_job(conn, str(video))
    llm = FakeLLMClient(_llm_judges_all)

    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), None, llm) == "ready_for_review"

    assert spans(conn, job_id)[-1] == ("llm_review", "ok")
    cuts = {c["reason"]: c for c in repo.get_cuts(conn, job_id)}
    assert (cuts["filler"]["llm_verdict"], cuts["filler"]["tier"]) == ("keep", "unsure")
    assert cuts["filler"]["rule_confidence"] == 0.9  # the candidate stays, only demoted
    assert (cuts["repeat"]["llm_verdict"], cuts["repeat"]["tier"]) == ("cut", "sure")
    assert cuts["retake"]["source"] == "llm"
    job = repo.get_job(conn, job_id)
    assert job is not None and job["llm_input_tokens"] == 100 and job["llm_cost_usd"] == 0.0
    sent = "\n".join(call["prompt"] for call in llm.calls)
    assert str(video) not in sent and "bài nói" not in sent and "0.65" not in sent  # text only


def test_llm_failure_falls_back_to_rules_only(
    cfg: Config,
    conn: sqlite3.Connection,
    make_video: Callable[..., Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from stuttercut.llm import LLMTimeout
    from stuttercut.llm.fake import FakeLLMClient

    job_id = repo.create_job(conn, str(make_video()))
    llm = FakeLLMClient(LLMTimeout("no answer within 30 s"))

    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), None, llm) == "ready_for_review"

    job = repo.get_job(conn, job_id)
    assert job is not None and job["status"] == "ready_for_review"
    assert spans(conn, job_id)[-1] == ("llm_review", "error")
    assert repo.cut_counts(conn, job_id, "tier") == {"sure": 2}
    assert any(r.levelname == "WARNING" and r.job_id == job_id for r in caplog.records)  # type: ignore[attr-defined]


def _with_llm(cfg: Config, **llm: object) -> Config:
    return replace(cfg, llm=replace(cfg.llm, **llm))  # type: ignore[arg-type]


def test_local_llm_unloads_asr_when_ram_is_low_and_next_job_reloads(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    from stuttercut.llm.fake import FakeLLMClient

    low_ram = _with_llm(cfg, unload_asr_below_gb=1e6)  # any machine is "below"
    asr = FakeTranscriber(FIXTURE)
    first = repo.create_job(conn, str(make_video()))
    assert run_job(conn, low_ram, first, asr, None, FakeLLMClient(_llm_judges_all)) == (
        "ready_for_review"
    )
    assert [s for s, _ in spans(conn, first)][-2:] == ["unload_asr", "llm_review"]
    assert not asr.loaded

    second = repo.create_job(conn, str(make_video()))
    assert run_job(conn, low_ram, second, asr, None, None) == "ready_for_review"
    assert ("load_model", "ok") in spans(conn, second) and asr.loads == 1


@pytest.mark.parametrize(("provider", "below_gb"), [("ollama", 0.0), ("anthropic", 1e6)])
def test_asr_stays_loaded_with_enough_ram_or_a_remote_llm(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path],
    provider: str, below_gb: float,
) -> None:  # fmt: skip
    from stuttercut.llm.fake import FakeLLMClient

    asr = FakeTranscriber(FIXTURE)
    job_id = repo.create_job(conn, str(make_video()))
    run_job(conn, _with_llm(cfg, provider=provider, unload_asr_below_gb=below_gb), job_id, asr,
            None, FakeLLMClient(_llm_judges_all))  # fmt: skip
    assert asr.loaded and "unload_asr" not in [s for s, _ in spans(conn, job_id)]


def test_local_llm_is_released_after_review_even_when_it_fails(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    from stuttercut.llm import LLMTimeout
    from stuttercut.llm.fake import FakeLLMClient

    released: list[bool] = []
    llm = FakeLLMClient(LLMTimeout("30 s"))
    llm.release = lambda: released.append(True)  # type: ignore[attr-defined]
    job_id = repo.create_job(conn, str(make_video()))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURE), None, llm) == "ready_for_review"
    assert released == [True]
