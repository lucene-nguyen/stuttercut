"""Render and XML export on synthetic FFmpeg media (lavfi fixture; no real clips)."""

import json
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import pytest

from stuttercut.asr.fake import FakeTranscriber
from stuttercut.config import Config
from stuttercut.media.audio import FFmpegError
from stuttercut.media.fcpxml import write_xml
from stuttercut.media.render import RenderError, plan, removed_s, render_mp4, video_info
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.pipeline import run_job, run_render
from tests.conftest import FIXTURES

CUTS = [(1.0, 1.5), (2.5, 3.0)]


def durations(path: Path) -> dict[str, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    data = json.loads(out)
    found = {s["codec_type"]: float(s["duration"]) for s in data["streams"]}
    return {**found, "format": float(data["format"]["duration"])}


def test_render_duration_and_av_sync(cfg: Config, make_video: Callable[..., Path]) -> None:
    src = make_video("bài nói thử.mp4", seconds=4.0, fps=30)
    info = video_info(src)
    keeps = plan(CUTS, info.duration_s, cfg.render, info.fps)
    out, encoder = render_mp4(src, keeps, paths.output_dir(cfg), cfg.render, encoder="libx264")
    assert out.name == "bài nói thử_clean.mp4" and encoder == "libx264"
    frame = float(1 / info.fps)
    d = durations(out)
    assert d["video"] == pytest.approx(info.duration_s - removed_s(keeps, info.duration_s),
                                       abs=frame)  # fmt: skip
    assert abs(d["video"] - d["audio"]) <= frame  # A/V sync
    assert [p.name for p in out.parent.iterdir()] == [out.name]  # no temp file left


def test_render_never_overwrites(cfg: Config, make_video: Callable[..., Path]) -> None:
    src = make_video(seconds=2.0)
    out_dir = paths.output_dir(cfg)
    first, _ = render_mp4(src, [(0.0, 1.0)], out_dir, cfg.render, encoder="libx264")
    size = first.stat().st_size
    second, _ = render_mp4(src, [(0.0, 1.5)], out_dir, cfg.render, encoder="libx264")
    assert second.name.endswith("_clean_2.mp4") and first.stat().st_size == size


def test_failed_render_leaves_no_output(cfg: Config, tmp_path: Path) -> None:
    out_dir = paths.output_dir(cfg)

    def disk_full(cmd: list[str]) -> str:
        Path(cmd[-1]).write_bytes(b"partial")  # FFmpeg wrote some, then the disk filled up
        raise FFmpegError("ffmpeg exited with 1", stderr="...: No space left on device")

    with pytest.raises(RenderError) as err:
        render_mp4(tmp_path / "x.mp4", [(0.0, 1.0)], out_dir, cfg.render, encoder="libx264",
                   run=disk_full)  # fmt: skip
    assert err.value.step == "encode" and "disk full" in str(err.value)
    assert "No space left" in err.value.stderr
    assert list(out_dir.iterdir()) == []


def test_hardware_encoder_failure_falls_back_to_libx264(cfg: Config, tmp_path: Path) -> None:
    used: list[str] = []

    def run(cmd: list[str]) -> str:
        enc = cmd[cmd.index("-c:v") + 1]
        used.append(enc)
        if enc != "libx264":
            raise FFmpegError("ffmpeg exited with 1", stderr="OpenEncodeSessionEx failed")
        Path(cmd[-1]).write_bytes(b"mp4")
        return ""

    out, encoder = render_mp4(tmp_path / "x.mp4", [(0.0, 1.0)], paths.output_dir(cfg),
                              cfg.render, encoder="h264_nvenc", run=run)  # fmt: skip
    assert (used, encoder, out.read_bytes()) == (["h264_nvenc", "libx264"], "libx264", b"mp4")


def test_xml_timeline_matches_the_plan(cfg: Config, make_video: Callable[..., Path]) -> None:
    src = make_video("bài nói thử.mp4", seconds=4.0, fps=30)
    info = video_info(src)
    keeps = plan(CUTS, info.duration_s, cfg.render, info.fps)
    out = write_xml(src, keeps, info, paths.output_dir(cfg))
    assert out.name == "bài nói thử_clean.xml"
    root = ET.parse(out).getroot()
    assert root.tag == "xmeml" and root.get("version") == "5"
    frames = [(round(s * info.fps), round(e * info.fps)) for s, e in keeps]
    for kind in ("video", "audio"):
        items = root.findall(f"sequence/media/{kind}/track/clipitem")
        got = [(int(i.findtext("in", "")), int(i.findtext("out", ""))) for i in items]
        assert got == frames
        starts = [int(i.findtext("start", "")) for i in items]
        assert starts == [sum(b - a for a, b in frames[:k]) for k in range(len(frames))]
    url = root.findtext(".//file/pathurl", "")
    assert url.startswith("file://localhost/") and " " not in url
    assert Path(unquote(url.removeprefix("file://localhost/"))).name == src.name
    assert root.findtext("sequence/rate/timebase") == "30"


@pytest.fixture
def conn(cfg: Config) -> sqlite3.Connection:
    return connect(paths.db_path(cfg))


def test_worker_render_both_and_rerender(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    src = make_video("bài nói.mp4", seconds=4.0, fps=30)
    job_id = repo.create_job(conn, str(src))
    fake = FakeTranscriber(FIXTURES / "synthetic_pair.json")
    assert run_job(conn, cfg, job_id, fake) == "ready_for_review"
    assert repo.approve_cuts(conn, job_id, "none") == 0
    n = repo.approve_cuts(conn, job_id, "all")
    assert n == len(repo.get_cuts(conn, job_id)) > 0

    result = run_render(conn, cfg, job_id, "both")
    job = repo.get_job(conn, job_id)
    assert job is not None and (result.status, job["status"]) == ("done", "done")
    assert result.approved == n and result.removed_s > 0 and result.encoder
    assert job["output_path"] == str(result.mp4) and job["xml_path"] == str(result.xml)
    assert result.mp4 and result.mp4.exists() and result.xml and result.xml.exists()
    assert repo.get_spans(conn, job_id)[-1]["step"] == "render"

    again = run_render(conn, cfg, job_id, "mp4")  # re-render from done
    assert again.status == "done" and again.mp4 and again.mp4.name.endswith("_clean_2.mp4")
    assert again.xml is None


def test_worker_render_failure_keeps_cuts_and_retry_works(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    src = make_video("lỗi.mp4", seconds=4.0)
    job_id = repo.create_job(conn, str(src))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURES / "synthetic_pair.json"))
    repo.approve_cuts(conn, job_id, "all")
    before = [dict(c) for c in repo.get_cuts(conn, job_id)]
    hidden = src.rename(src.with_name("moved.mp4"))

    assert run_render(conn, cfg, job_id, "mp4").status == "failed"
    job = repo.get_job(conn, job_id)
    assert job is not None and (job["status"], job["failed_step"]) == ("failed", "render")
    assert [dict(c) for c in repo.get_cuts(conn, job_id)] == before  # reviewed cuts kept
    last = repo.get_spans(conn, job_id)[-1]
    assert (last["step"], last["status"]) == ("render", "error")
    assert list(paths.output_dir(cfg).iterdir()) == []

    hidden.rename(src)
    assert run_render(conn, cfg, job_id, "mp4").status == "done"  # retry from failed at render


def test_render_refuses_a_job_not_reviewed_yet(cfg: Config, conn: sqlite3.Connection) -> None:
    job_id = repo.create_job(conn, "x.mp4")
    with pytest.raises(ValueError, match="queued"):
        run_render(conn, cfg, job_id)


def test_output_locked_briefly_after_writing_is_moved_on_retry(
    cfg: Config, make_video: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows: a scanner holds the fresh temp file for a moment (WinError 32)."""
    src = make_video("khóa.mp4", seconds=2.0, fps=30)
    info = video_info(src)
    real_rename, calls = Path.rename, []

    def flaky_rename(self: Path, target: Path) -> Path:
        calls.append(self.name)
        if len(calls) <= 2:
            raise PermissionError(32, "being used by another process")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    monkeypatch.setattr("stuttercut.media.render.time.sleep", lambda _s: None)
    out = write_xml(src, [(0.0, 1.0)], info, paths.output_dir(cfg))
    assert out.name == "khóa_clean.xml" and len(calls) == 3
    assert [p.name for p in out.parent.iterdir()] == [out.name]  # no .part file left


def test_render_after_an_edge_edit_has_the_planned_duration(
    cfg: Config, conn: sqlite3.Connection, make_video: Callable[..., Path]
) -> None:
    from stuttercut.worker.pipeline import job_plan

    src = make_video("sửa biên.mp4", seconds=10.0, fps=25)
    job_id = repo.create_job(conn, str(src))
    assert run_job(conn, cfg, job_id, FakeTranscriber(FIXTURES / "review_clip.json")) == (
        "ready_for_review"
    )
    filler = repo.get_cuts(conn, job_id)[0]  # "ờ" 1.00-1.30
    repo.set_cut_edges(conn, job_id, filler["id"], 0.9, 1.4)  # wider, edited: no padding
    job = repo.get_job(conn, job_id)
    assert job is not None
    keeps, duration = job_plan(conn, cfg, job)
    # no padding on edited edges; keep-segments still snap outward to whole frames (A/V sync)
    assert keeps[0][1] == pytest.approx(0.92) and keeps[1][0] == pytest.approx(1.4)

    result = run_render(conn, cfg, job_id, "mp4")
    assert result.status == "done" and result.mp4 is not None
    expected = sum(e - s for s, e in keeps)
    d = durations(result.mp4)
    assert d["video"] == pytest.approx(expected, abs=1 / 25)
    assert abs(d["video"] - d["audio"]) <= 1 / 25
    assert result.removed_s == pytest.approx(duration - expected)
