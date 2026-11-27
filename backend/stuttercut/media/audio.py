"""FFmpeg wrappers: probe a video and extract 16 kHz mono WAV for the ASR model."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from stuttercut.config import MediaConfig


class MediaError(Exception):
    """Base class: the video cannot be used. ``stderr`` holds FFmpeg's output when it ran."""

    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


class NoAudioStreamError(MediaError):
    pass


class TooLongError(MediaError):
    def __init__(self, duration_s: float, max_s: float) -> None:
        super().__init__(f"video is {duration_s:.1f} s long; the limit is {max_s:.0f} s")
        self.duration_s = duration_s
        self.max_s = max_s


class FFmpegError(MediaError):
    pass


@dataclass(frozen=True)
class Probe:
    duration_s: float
    has_audio: bool


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as e:
        raise FFmpegError(f"{cmd[0]} not found on PATH") from e
    if proc.returncode != 0:
        raise FFmpegError(f"{cmd[0]} exited with {proc.returncode}", stderr=proc.stderr)
    return proc.stdout


def probe(path: Path) -> Probe:
    out = _run(
        [
            *("ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type"),
            *("-of", "json", str(path)),
        ]
    )
    data = json.loads(out)
    try:
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError) as e:
        raise MediaError(f"cannot read the duration of {path.name}", stderr=out) from e
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return Probe(duration, has_audio)


def extract_audio(video: Path, wav: Path, cfg: MediaConfig) -> float:
    """Validate the video and write ``wav``; returns the video duration in seconds."""
    info = probe(video)
    if not info.has_audio:
        raise NoAudioStreamError(f"{video.name} has no audio stream")
    if info.duration_s > cfg.max_duration_s:
        raise TooLongError(info.duration_s, cfg.max_duration_s)
    _run(
        [
            *("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
            *("-threads", str(cfg.ffmpeg_threads), "-i", str(video), "-vn", "-ac", "1"),
            *("-ar", str(cfg.sample_rate), "-c:a", "pcm_s16le", str(wav)),
        ]
    )
    return info.duration_s


def make_preview(video: Path, out: Path, cfg: MediaConfig) -> None:
    """480p H.264 proxy for the review screen (small, seeks fast, plays in every browser)."""
    tmp = out.with_name(f".{out.name}.part.mp4")
    try:
        _run(
            [
                *("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
                *("-threads", str(cfg.ffmpeg_threads), "-i", str(video)),
                *("-vf", f"scale=-2:'min({cfg.preview_height},ih)'", "-c:v", "libx264"),
                *("-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"),
                *("-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-f", "mp4", str(tmp)),
            ]
        )
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)


def make_preview_audio(video: Path, out: Path, cfg: MediaConfig) -> None:
    """48 kHz mono WAV for the review screen's clean preview (Web Audio). Not the 16 kHz ASR
    audio: the preview must sound like the render."""
    tmp = out.with_name(f".{out.name}.part.wav")
    try:
        _run(
            [
                *("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
                *("-threads", str(cfg.ffmpeg_threads), "-i", str(video), "-vn", "-ac", "1"),
                *("-ar", str(cfg.preview_sample_rate), "-c:a", "pcm_s16le", "-f", "wav", str(tmp)),
            ]
        )
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
