"""API contract: the routes the Upload & jobs and Review screens use (design doc "API design").

The worker runs in-process (InlineWorker) with the fake transcriber and synthetic FFmpeg media,
so every request is deterministic; tests/integration/test_api_worker.py covers the real process.
"""

import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stuttercut.api.main import create_app
from stuttercut.asr.fake import FakeTranscriber
from stuttercut.config import Config
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import Message, handle
from tests.conftest import FIXTURES

FIXTURE = FIXTURES / "review_clip.json"


class InlineWorker:
    """Runs each message at once in this process (the real one is a separate process)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg, self.msgs, self.paused = cfg, [], False
        self.transcriber = FakeTranscriber(FIXTURE)

    def start(self) -> None: ...

    def stop(self, timeout_s: float = 5.0) -> None: ...

    def put(self, msg: Message) -> None:
        self.msgs.append(msg)
        if not self.paused:
            conn = connect(paths.db_path(self.cfg))
            handle(conn, self.cfg, msg, self.transcriber)
            conn.close()


@pytest.fixture
def api(cfg: Config) -> Iterator[tuple[TestClient, InlineWorker, list[Path]]]:
    worker, revealed = InlineWorker(cfg), []
    app = create_app(cfg, worker=worker, reveal=revealed.append)
    app.state.sse_interval_s = 0.01
    with TestClient(app) as client:
        yield client, worker, revealed


def upload(client: TestClient, video: Path, options: dict[str, Any] | None = None) -> Any:
    params: dict[str, str] = {"name": video.name}
    if options is not None:
        params["options"] = json.dumps(options)
    return client.post("/api/jobs", params=params, content=video.read_bytes())


def db(cfg: Config) -> sqlite3.Connection:
    return connect(paths.db_path(cfg))


Api = tuple[TestClient, InlineWorker, list[Path]]


def test_upload_runs_the_job_and_lists_it(api: Api, make_video: Callable[..., Path]) -> None:
    client, worker, _ = api
    res = upload(client, make_video("bài nói thử.mp4", seconds=10.0, fps=25))
    assert res.status_code == 201, res.text
    job_id = res.json()["id"]
    assert worker.msgs == [("process", job_id)]
    (row,) = client.get("/api/jobs").json()
    assert (row["id"], row["name"], row["status"]) == (
        job_id,
        "bài nói thử.mp4",
        "ready_for_review",
    )
    assert row["cut_count"] == 4 and row["saved_s"] == 0  # nothing approved yet
    detail = client.get(f"/api/jobs/{job_id}").json()
    assert [w["text"] for w in detail["words"]][:3] == ["Xin", "chào", "ờ"]
    assert sorted(c["tier"] for c in detail["cuts"]) == ["sure", "sure", "unsure", "unsure"]
    assert {"id", "start_s", "end_s", "reason", "source", "kept", "approved", "decided_at"} <= set(
        detail["cuts"][0]
    )


@pytest.mark.parametrize(("seconds", "audio", "message"), [
    (241.0, True, "is 4:01 long. Choose a video of 3 minutes or less."),
    (2.0, False, "has no sound"),
])  # fmt: skip
def test_invalid_upload_is_422_and_creates_nothing(
    api: Api,
    cfg: Config,
    make_video: Callable[..., Path],
    seconds: float,
    audio: bool,
    message: str,
) -> None:
    client, worker, _ = api
    res = upload(client, make_video("dài quá.mp4", seconds=seconds, audio=audio))
    assert res.status_code == 422 and message in res.json()["detail"]
    assert client.get("/api/jobs").json() == [] and worker.msgs == []
    assert list((paths.data_dir(cfg) / "uploads").iterdir()) == []


def test_not_a_video_and_bad_options_are_422(api: Api, tmp_path: Path) -> None:
    client, _, _ = api
    fake = tmp_path / "notes.mp4"
    fake.write_text("hello")
    assert "not a video" in upload(client, fake).json()["detail"]
    res = client.post("/api/jobs", params={"name": "a.mp4", "options": '{"pause_min_ms": 5}'},
                      content=b"x")  # fmt: skip
    assert res.status_code == 422 and "options" in res.json()["detail"]


def test_options_switch_reasons_off(api: Api, make_video: Callable[..., Path]) -> None:
    client, _, _ = api
    job_id = upload(client, make_video(seconds=10.0), {"pause": False, "filler": False}).json()[
        "id"
    ]
    reasons = {c["reason"] for c in client.get(f"/api/jobs/{job_id}").json()["cuts"]}
    assert reasons == {"repeat"}


def test_decisions_are_saved_with_a_timestamp(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    job_id = upload(client, make_video(seconds=10.0)).json()["id"]
    cuts = client.get(f"/api/jobs/{job_id}").json()["cuts"]
    sure = [c["id"] for c in cuts if c["tier"] == "sure"]
    res = client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "approve_sure"})
    assert res.json()["changed"] == 2 and res.json()["saved_s"] > 0
    res = client.patch(f"/api/jobs/{job_id}/cuts/{sure[0]}", json={"kept": True})
    assert res.status_code == 200
    rows = {c["id"]: c for c in client.get(f"/api/jobs/{job_id}").json()["cuts"]}
    assert (rows[sure[0]]["kept"], rows[sure[0]]["approved"]) == (1, 0)
    assert (rows[sure[1]]["kept"], rows[sure[1]]["approved"]) == (0, 1)
    assert rows[sure[0]]["decided_at"] and rows[sure[1]]["decided_at"]
    assert all(c["decided_at"] is None for c in rows.values() if c["tier"] == "unsure")
    assert client.patch(f"/api/jobs/{job_id}/cuts/99999", json={"kept": True}).status_code == 404

    res = client.post(f"/api/jobs/{job_id}/cuts", json={"start_s": 7.7, "end_s": 8.0,
                                                        "reason": "filler"})  # fmt: skip
    assert res.status_code == 201
    user = [c for c in client.get(f"/api/jobs/{job_id}").json()["cuts"] if c["source"] == "user"]
    assert [(u["start_s"], u["approved"], u["kept"]) for u in user] == [(7.7, 1, 0)]
    bad = {"start_s": 2, "end_s": 1, "reason": "filler"}
    assert client.post(f"/api/jobs/{job_id}/cuts", json=bad).status_code == 422
    assert client.post(f"/api/jobs/{job_id}/cuts",
                       json={**bad, "end_s": 3, "reason": "cough"}).status_code == 422  # fmt: skip
    client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "keep_all"})
    left = client.get(f"/api/jobs/{job_id}").json()["cuts"]
    assert [c["source"] for c in left if c["approved"]] == ["user"]  # hand-marked cut stays


def test_render_both_to_a_folder_then_reveal(
    api: Api, tmp_path: Path, make_video: Callable[..., Path]
) -> None:
    client, worker, revealed = api
    job_id = upload(client, make_video("bài nói.mp4", seconds=10.0, fps=25)).json()["id"]
    client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "approve_sure"})
    folder = tmp_path / "xuất ra"
    res = client.post(f"/api/jobs/{job_id}/render", json={"format": "both", "folder": str(folder)})
    assert res.status_code == 202, res.text
    assert worker.msgs[-1] == ("render", job_id, "both", str(folder))
    row = client.get(f"/api/jobs/{job_id}").json()
    assert row["status"] == "done"
    assert (
        Path(row["output_path"]).parent == folder
        and Path(row["xml_path"]).name == "bài nói_clean.xml"
    )
    assert client.post(f"/api/jobs/{job_id}/reveal").status_code == 204
    assert revealed == [Path(row["output_path"])]
    bad = client.post(f"/api/jobs/{job_id}/render", json={"format": "gif"})
    assert bad.status_code == 422
    assert (
        client.post(f"/api/jobs/{job_id}/render", json={"folder": "relative/dir"}).status_code
        == 422
    )


def test_render_before_review_is_409(api: Api, make_video: Callable[..., Path]) -> None:
    client, worker, _ = api
    worker.paused = True  # the job stays queued
    job_id = upload(client, make_video(seconds=2.0)).json()["id"]
    assert client.post(f"/api/jobs/{job_id}/render", json={}).status_code == 409
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_failed_render_keeps_cuts_and_retry_renders(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client, _, _ = api
    video = make_video("lỗi.mp4", seconds=10.0)
    job_id = upload(client, video).json()["id"]
    client.post(f"/api/jobs/{job_id}/cuts:bulk", json={"action": "approve_sure"})
    source = Path(repo.get_job(db(cfg), job_id)["source_path"])
    hidden = source.rename(source.with_name("moved.mp4"))
    client.post(f"/api/jobs/{job_id}/render", json={"format": "mp4"})
    row = client.get(f"/api/jobs/{job_id}").json()
    assert (row["status"], row["failed_step"]) == ("failed", "render")
    assert sum(c["approved"] for c in row["cuts"]) == 2  # reviewed cuts kept
    hidden.rename(source)
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 202
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"


def test_preview_supports_range_requests(api: Api, make_video: Callable[..., Path]) -> None:
    client, _, _ = api
    job_id = upload(client, make_video(seconds=3.0)).json()["id"]
    full = client.get(f"/api/jobs/{job_id}/preview")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    part = client.get(f"/api/jobs/{job_id}/preview", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.content == full.content[:100]
    assert client.get("/api/jobs/nope/preview").status_code == 404


def test_events_stream_ends_with_the_final_state(api: Api, make_video: Callable[..., Path]) -> None:
    client, worker, _ = api
    worker.paused = True
    job_id = upload(client, make_video(seconds=10.0)).json()["id"]
    worker.paused = False
    worker.put(worker.msgs[0])  # the worker ran: spans written, status ready_for_review
    with client.stream("GET", f"/api/jobs/{job_id}/events") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(res.iter_text())
    kinds = [
        line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event:")
    ]
    assert kinds[:4] == ["step_done"] * 4 and kinds[-1] == "ready"
    last = json.loads(body.strip().splitlines()[-1].removeprefix("data: "))
    assert last["status"] == "ready_for_review"
    assert client.get("/api/jobs/nope/events").status_code == 404


def test_upload_too_large_is_413(cfg: Config, make_video: Callable[..., Path]) -> None:
    small = replace(cfg, media=replace(cfg.media, max_upload_mb=0))
    app = create_app(small, worker=InlineWorker(small), reveal=lambda _p: None)
    with TestClient(app) as client:
        assert upload(client, make_video(seconds=1.0)).status_code == 413
        assert client.get("/api/jobs").json() == []
