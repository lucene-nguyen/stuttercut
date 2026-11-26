"""The API with its real worker process (spawned), fake transcriber, synthetic media."""

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from stuttercut.api.main import create_app
from stuttercut.config import Config
from tests.conftest import FIXTURES


def wait_for(client: TestClient, job_id: str, status: str, timeout_s: float = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        row: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if row["status"] == status:
            return row
        assert row["status"] != "failed", row
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} not {status} within {timeout_s} s")


def test_upload_review_render_through_the_worker_process(
    cfg: Config, make_video: Callable[..., Path]
) -> None:
    cfg = replace(cfg, asr=replace(cfg.asr, fake_fixture=FIXTURES / "review_clip.json"))
    video = make_video("bài nói.mp4", seconds=10.0, fps=25)
    with TestClient(create_app(cfg, reveal=lambda _p: None)) as client:
        res = client.post("/api/jobs", params={"name": video.name}, content=video.read_bytes())
        job_id = res.json()["id"]
        row = wait_for(client, job_id, "ready_for_review")
        assert row["cut_count"] == 4
        client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "approve_sure"})
        client.post(f"/api/jobs/{job_id}/render", json={"format": "mp4"})
        done = wait_for(client, job_id, "done")
        assert Path(done["output_path"]).name == "bài nói_clean.mp4"
