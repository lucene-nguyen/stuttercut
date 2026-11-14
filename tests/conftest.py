"""Shared fixtures: config isolated in tmp_path, synthetic media made by FFmpeg (lavfi).

Media tests skip cleanly when ffmpeg/ffprobe are not on PATH.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from stuttercut.config import Config, load_config

FIXTURES = Path(__file__).parent / "fixtures"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """Default config with all state under tmp_path; ignores the developer's env and .env."""
    return load_config(env={"STUTTERCUT_HOME": str(tmp_path / "home")}, dotenv=tmp_path / "none")


@pytest.fixture
def make_video(tmp_path: Path) -> Callable[..., Path]:
    """make_video(name, seconds=2.0, audio=True) -> a tiny MP4 made from test patterns."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not on PATH")

    def make(name: str = "clip thử nghiệm.mp4", seconds: float = 2.0, audio: bool = True) -> Path:
        out = tmp_path / name
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        cmd += ["-f", "lavfi", "-i", f"testsrc=size=64x48:rate=10:duration={seconds}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
        subprocess.run([*cmd, str(out)], check=True, capture_output=True)
        return out

    return make
