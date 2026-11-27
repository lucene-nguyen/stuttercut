"""Clean preview + cut edges (LEARNING-209 follow-up): PATCH edges, GET /plan, preview audio."""

import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from stuttercut.config import Config
from stuttercut.storage import paths, repo
from stuttercut.worker import pipeline
from tests.contract.conftest import Api, db, upload


def ready_job(api: Api, make_video: Callable[..., Path], name: str = "bài nói.mp4") -> str:
    client, _, _ = api
    return str(upload(client, make_video(name, seconds=10.0, fps=25)).json()["id"])


def cuts(api: Api, job_id: str) -> list[dict[str, Any]]:
    return list(api[0].get(f"/api/jobs/{job_id}").json()["cuts"])


def test_patch_edges_validates_and_approves(api: Api, make_video: Callable[..., Path]) -> None:
    client = api[0]
    job_id = ready_job(api, make_video)
    cut = cuts(api, job_id)[0]  # filler "ờ" 1.00-1.30
    url = f"/api/jobs/{job_id}/cuts/{cut['id']}"
    for bad in ({"start_s": -0.1, "end_s": 1.3}, {"start_s": 1.3, "end_s": 1.3},
                {"start_s": 9.0, "end_s": 10.5}, {"start_s": 1.0, "end_s": 1.01},
                {"start_s": 1.0}, {"kept": True, "start_s": 1.0, "end_s": 1.3}, {}):  # fmt: skip
        res = client.patch(url, json=bad)
        assert res.status_code == 422, (bad, res.text)
    assert client.patch(f"/api/jobs/{job_id}/cuts/99999",
                        json={"start_s": 1.0, "end_s": 1.3}).status_code == 404  # fmt: skip

    res = client.patch(url, json={"start_s": 0.98, "end_s": 1.32})
    assert res.status_code == 200 and res.json()["saved_s"] > 0
    row = next(c for c in cuts(api, job_id) if c["id"] == cut["id"])
    assert (row["start_s"], row["end_s"], row["approved"], row["kept"]) == (0.98, 1.32, 1, 0)
    assert (row["orig_start_s"], row["orig_end_s"]) == (1.0, 1.3)
    assert (row["start_edited"], row["end_edited"]) == (1, 1) and row["decided_at"]
    assert client.patch(url, json={"start_s": 0.98, "end_s": 1.0}).status_code == 200  # 20 ms ok


def test_plan_follows_decisions_and_edited_edges_get_no_padding(
    api: Api, make_video: Callable[..., Path]
) -> None:
    client = api[0]
    job_id = ready_job(api, make_video)
    p = client.get(f"/api/jobs/{job_id}/plan").json()
    assert p == {"keep_segments": [{"start_s": 0.0, "end_s": 10.0}], "fade_ms": 10,
                 "duration_s": 10.0}  # fmt: skip
    cut = cuts(api, job_id)[0]
    client.patch(f"/api/jobs/{job_id}/cuts/{cut['id']}", json={"kept": False})
    padded = client.get(f"/api/jobs/{job_id}/plan").json()["keep_segments"]
    assert padded == [{"start_s": 0.0, "end_s": 1.04}, {"start_s": 1.24, "end_s": 10.0}]  # 25 fps
    client.patch(f"/api/jobs/{job_id}/cuts/{cut['id']}", json={"start_s": 1.0, "end_s": 1.28})
    exact = client.get(f"/api/jobs/{job_id}/plan").json()["keep_segments"]
    # start back on the original edge but end edited: start keeps its padding, end gets none
    assert exact == [{"start_s": 0.0, "end_s": 1.04}, {"start_s": 1.28, "end_s": 10.0}]
    assert client.get("/api/jobs/nope/plan").status_code == 404


def test_preview_audio_is_48k_mono_served_with_range_and_reused(
    api: Api, cfg: Config, make_video: Callable[..., Path]
) -> None:
    client = api[0]
    job_id = ready_job(api, make_video)
    wav = paths.data_dir(cfg) / "jobs" / job_id / "preview.wav"
    assert wav.is_file()  # made by the worker's preview step
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels()) == (48000, 1)
        assert w.getnframes() / w.getframerate() == pytest.approx(10.0, abs=0.05)
    part = client.get(f"/api/jobs/{job_id}/preview-audio", headers={"Range": "bytes=0-43"})
    assert part.status_code == 206 and part.content[:4] == b"RIFF" and len(part.content) == 44
    mtime = wav.stat().st_mtime_ns
    assert client.get(f"/api/jobs/{job_id}/preview-audio").status_code == 200
    assert wav.stat().st_mtime_ns == mtime  # reused, not made again

    wav.unlink()  # a job from before this change: made on first use
    full = client.get(f"/api/jobs/{job_id}/preview-audio")
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav"
    files = client.get(f"/api/jobs/{job_id}/trace").json()["files_mb"]
    assert set(files) == {"preview.mp4", "preview.wav"} and files["preview.wav"] > 0.5


edit = st.tuples(st.sampled_from(["none", "keep", "cut", "edges"]),
                 st.floats(-0.08, 0.08), st.floats(-0.08, 0.08))  # fmt: skip


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(edit, min_size=4, max_size=4))
def test_plan_endpoint_equals_what_render_uses(
    api: Api, cfg: Config, make_video: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
    decisions: list[tuple[str, float, float]],
) -> None:  # fmt: skip
    client = api[0]
    conn = db(cfg)
    job_id = getattr(test_plan_endpoint_equals_what_render_uses, "job", None)
    if job_id is None or repo.get_job(conn, job_id) is None:
        job_id = ready_job(api, make_video, "đề xuất.mp4")
        test_plan_endpoint_equals_what_render_uses.job = job_id  # type: ignore[attr-defined]
    rows = cuts(api, job_id)
    for row, (action, ds, de) in zip(rows, decisions, strict=True):
        url = f"/api/jobs/{job_id}/cuts/{row['id']}"
        client.patch(url, json={"start_s": row["orig_start_s"], "end_s": row["orig_end_s"]})
        if action in ("keep", "cut"):
            client.patch(url, json={"kept": action == "keep"})
        elif action == "edges":
            start = max(0.0, row["orig_start_s"] + ds)
            end = max(start + 0.02, row["orig_end_s"] + de)
            assert client.patch(url, json={"start_s": start, "end_s": end}).status_code == 200
        else:  # back to an undecided suggestion
            with conn:
                conn.execute("UPDATE cut SET approved = 0, kept = 0, decided_at = NULL"
                             " WHERE id = ?", (row["id"],))  # fmt: skip

    shown = [(s["start_s"], s["end_s"]) for s in client.get(f"/api/jobs/{job_id}/plan").json()
             ["keep_segments"]]  # fmt: skip
    used: list[list[tuple[float, float]]] = []

    def fake_render(_src: Path, keeps: Any, out_dir: Path, *_a: Any, **_k: Any) -> Any:
        used.append([(round(s, 6), round(e, 6)) for s, e in keeps])
        return out_dir / "x.mp4", "libx264"

    monkeypatch.setattr(pipeline, "render_mp4", fake_render)
    assert pipeline.run_render(conn, cfg, job_id, "mp4").status == "done"
    assert used == [shown]
