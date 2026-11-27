"""Fault injection (Test Plan "Failure modes", LEARNING-235): the real API, its spawned worker
and the watchdog, with the fake transcriber told to hog memory or stall."""

import json
import os
import queue
import signal
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import psutil
import pytest
from fastapi.testclient import TestClient

from stuttercut.api.main import create_app
from stuttercut.asr.fake import FakeTranscriber
from stuttercut.config import Config
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import worker_main
from tests.conftest import FIXTURES


def fixture(tmp_path: Path, **faults: float) -> Path:
    data = json.loads((FIXTURES / "review_clip.json").read_text(encoding="utf-8"))
    path = tmp_path / f"fault-{'-'.join(faults) or 'none'}.json"
    path.write_text(json.dumps({**data, **{f"_{k}": v for k, v in faults.items()}}), "utf-8")
    return path


def configure(cfg: Config, fake: Path, **limits: float) -> Config:
    base = {"watchdog_interval_s": 0.2, "kill_grace_s": 2.0, **limits}
    return replace(cfg, asr=replace(cfg.asr, fake_fixture=fake),
                   limits=replace(cfg.limits, **base))  # fmt: skip


@contextmanager
def running(cfg: Config) -> Iterator[TestClient]:
    with TestClient(create_app(cfg, reveal=lambda _p: None)) as client:
        yield client


def upload(client: TestClient, video: Path) -> str:
    res = client.post("/api/jobs", params={"name": video.name}, content=video.read_bytes())
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def wait_for(fetch: Callable[[], Any], ok: Callable[[Any], bool], timeout_s: float = 90) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = fetch()
        if ok(value):
            return value
        time.sleep(0.2)
    raise AssertionError(f"condition not met within {timeout_s} s; last value: {value}")


def job(client: TestClient, job_id: str) -> dict[str, Any]:
    return dict(client.get(f"/api/jobs/{job_id}").json())


def worker_pid(client: TestClient) -> int:
    stats = wait_for(lambda: client.get("/api/health").json()["worker"],
                     lambda w: w and w.get("alive"))  # fmt: skip
    return int(stats["pid"])


def test_rss_over_limit_kills_the_worker_fails_the_job_and_respawns(
    cfg: Config, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    cfg = configure(cfg, fixture(tmp_path, allocate_mb=400, sleep_s=30), worker_max_rss_gb=0.25)
    video = make_video(seconds=10.0)
    with running(cfg) as client:
        first_pid = worker_pid(client)
        job_id = upload(client, video)
        row = wait_for(lambda: job(client, job_id), lambda j: j["status"] == "failed")
        assert row["failed_step"] == "transcribe" and row["error"].startswith("resource limit")
        assert not psutil.pid_exists(first_pid) or psutil.Process(first_pid).status() == "zombie"

        def respawned(h: dict[str, Any]) -> bool:
            return bool(h["worker"].get("alive") and h["worker"]["pid"] != first_pid)

        health = wait_for(lambda: client.get("/api/health").json(), respawned)
        assert health["status"] == "ok" and health["worker"]["restarts"] == 1  # API stays up
        last = client.get(f"/api/jobs/{job_id}/trace").json()["spans"][-1]
        assert (last["step"], last["status"]) == ("transcribe", "error")


def test_step_timeout_fails_the_job_at_that_step(
    cfg: Config, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    cfg = configure(cfg, fixture(tmp_path, sleep_s=60), step_timeout_base_s=1.0,
                    transcribe_timeout_x=0.1, other_timeout_x=2.0)  # fmt: skip
    with running(cfg) as client:
        job_id = upload(client, make_video(seconds=10.0))
        row = wait_for(lambda: job(client, job_id), lambda j: j["status"] == "failed")
        assert (
            row["failed_step"] == "transcribe"
            and row["error"] == "timeout: transcribe ran over 2 s"
        )


def test_worker_killed_mid_job_fails_it_and_the_next_job_runs(
    cfg: Config, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    stall = fixture(tmp_path, sleep_s=60)
    cfg = configure(cfg, stall)
    video = make_video(seconds=10.0)
    with running(cfg) as client:
        stuck = upload(client, video)
        wait_for(lambda: job(client, stuck), lambda j: j["step"] == "transcribe")
        pid = worker_pid(client)
        # The next job must run: let the fake answer at once from now on.
        stall.write_text((FIXTURES / "review_clip.json").read_text("utf-8"), "utf-8")
        nxt = upload(client, video)
        assert job(client, nxt)["status"] == "queued"  # one job at a time
        os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
        row = wait_for(lambda: job(client, stuck), lambda j: j["status"] == "failed")
        assert row["failed_step"] == "transcribe" and "stopped unexpectedly" in row["error"]
        wait_for(lambda: job(client, nxt), lambda j: j["status"] == "ready_for_review")
        assert psutil.pid_exists(pid) is False or psutil.Process(pid).status() == "zombie"


def test_two_uploads_run_one_after_the_other(
    cfg: Config, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    cfg = configure(cfg, fixture(tmp_path, sleep_s=1.5))
    video = make_video(seconds=10.0)
    with running(cfg) as client:
        a, b = upload(client, video), upload(client, video)
        wait_for(lambda: job(client, a), lambda j: j["step"] == "transcribe")
        assert job(client, b)["status"] == "queued"
        wait_for(lambda: job(client, b), lambda j: j["status"] == "ready_for_review")
        spans = {j: client.get(f"/api/jobs/{j}/trace").json()["spans"] for j in (a, b)}
        a_end = max(s["started_at"] for s in spans[a])
        assert min(s["started_at"] for s in spans[b]) >= a_end  # b started after a finished


def test_api_restart_keeps_review_decisions_and_recovers_jobs(
    cfg: Config, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    cfg = configure(cfg, fixture(tmp_path))
    video = make_video(seconds=10.0)
    with running(cfg) as client:
        reviewed = upload(client, video)
        wait_for(lambda: job(client, reviewed), lambda j: j["status"] == "ready_for_review")
        client.post(f"/api/jobs/{reviewed}/cuts:bulk", json={"action": "approve_sure"})
        cut = job(client, reviewed)["cuts"][0]["id"]
        client.patch(f"/api/jobs/{reviewed}/cuts/{cut}", json={"kept": True})
        before = job(client, reviewed)["cuts"]
    conn = connect(paths.db_path(cfg))  # the API died: one job was mid-step, one was waiting
    interrupted = repo.create_job(conn, str(video))
    repo.set_status(conn, interrupted, "processing")
    repo.set_step(conn, interrupted, "transcribe")
    waiting = repo.create_job(conn, str(video))
    conn.close()

    with running(cfg) as client:
        assert job(client, reviewed)["cuts"] == before  # every toggle kept
        row = job(client, interrupted)
        assert (row["status"], row["failed_step"]) == ("failed", "transcribe")
        assert row["error"].startswith("interrupted")
        wait_for(lambda: job(client, waiting), lambda j: j["status"] == "ready_for_review")


def test_idle_worker_unloads_the_model_and_the_next_job_reloads_it(
    cfg: Config, make_video: Callable[..., Path]
) -> None:
    cfg = replace(cfg, limits=replace(cfg.limits, model_idle_unload_s=0.2))
    fake = FakeTranscriber(FIXTURES / "review_clip.json")
    q: queue.Queue[Any] = queue.Queue()
    conn = connect(paths.db_path(cfg))
    job_id = repo.create_job(conn, str(make_video(seconds=2.0)))

    def feed() -> None:
        time.sleep(0.6)  # idle long enough to unload
        assert not fake.loaded
        q.put(job_id)
        q.put(None)

    import threading

    t = threading.Thread(target=feed)
    t.start()
    worker_main(q, cfg, make_transcriber=lambda _c: fake, make_vad=lambda _c: None,
                make_llm=lambda _c: None)  # fmt: skip
    t.join()
    assert fake.loads == 1 and repo.get_job(conn, job_id)["status"] == "ready_for_review"
    steps = [s["step"] for s in repo.get_spans(conn, job_id)]
    assert "load_model" in steps


def test_reload_preflight_fails_clearly_when_ram_is_short(
    cfg: Config, make_video: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from stuttercut.worker.pipeline import run_job

    fake = FakeTranscriber(FIXTURES / "review_clip.json")
    fake.unload()
    monkeypatch.setattr("stuttercut.platform.free_ram_gb", lambda: 1.0)
    cfg = replace(cfg, asr=replace(cfg.asr, min_free_gb_any=3.0))  # the real default
    conn = connect(paths.db_path(cfg))
    job_id = repo.create_job(conn, str(make_video(seconds=2.0)))
    assert run_job(conn, cfg, job_id, fake) == "failed"
    row = repo.get_job(conn, job_id)
    assert row["failed_step"] == "load_model" and "RAM free" in row["error"]
    assert not fake.loaded
