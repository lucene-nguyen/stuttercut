"""Render approved cuts into a clean MP4 (LEARNING-210): pure planning + a thin FFmpeg layer.

Planning (no I/O): every approved cut shrinks by ``cut_padding_ms`` on both sides (not at the
clip's own start or end, where there is no syllable to protect), cuts closer than
``cut_merge_ms`` merge, the rest of the timeline becomes keep-segments, and segments shorter
than ``min_segment_ms`` are dropped. Boundaries snap outward to the source frame grid, so every
video segment holds exactly as much time as its audio: no lip-sync drift across many joins.

FFmpeg: one filter_complex of trim/atrim + concat (frame-accurate re-encode) with a short audio
fade at every join. The encoder is the first of h264_videotoolbox -> h264_nvenc -> libx264 that
is listed by ``ffmpeg -encoders`` and encodes one test frame; a hardware encoder that still
fails on the real render is retried once with libx264. Output goes to a temp file next to the
target and is moved into place only on success; a failed render leaves nothing behind.
"""

import json
import logging
import math
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from pathlib import Path

from stuttercut.config import RenderConfig
from stuttercut.media.audio import FFmpegError, MediaError, _run

log = logging.getLogger(__name__)

HARDWARE = ("h264_videotoolbox", "h264_nvenc")
_ENCODER_ARGS = {  # visually lossless-ish quality; the source is re-encoded once
    "h264_videotoolbox": ["-q:v", "65"],
    "h264_nvenc": ["-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
    "libx264": ["-preset", "veryfast", "-crf", "18"],
}


class RenderError(FFmpegError):
    """Render failed; ``step`` is the stage (probe, encode, move), ``stderr`` FFmpeg's tail."""

    def __init__(self, step: str, message: str, stderr: str = "") -> None:
        super().__init__(f"{step}: {message}", stderr=stderr[-4000:])
        self.step = step


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    fps: Fraction
    width: int
    height: int
    has_audio: bool


Segment = tuple[float, float]


def video_info(path: Path) -> VideoInfo:
    out = _run(
        [
            *("ffprobe", "-v", "error", "-show_entries"),
            "format=duration:stream=codec_type,r_frame_rate,width,height",
            *("-of", "json", str(path)),
        ]
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name} has no video stream")
    try:
        return VideoInfo(
            duration_s=float(data["format"]["duration"]),
            fps=Fraction(video["r_frame_rate"]),
            width=int(video["width"]),
            height=int(video["height"]),
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
        )
    except (KeyError, ValueError, ZeroDivisionError) as e:
        raise MediaError(f"cannot read the video format of {path.name}", stderr=out) from e


# --- planning (pure) ---------------------------------------------------------------------------


def plan(
    cuts: Sequence[Segment], duration: float, cfg: RenderConfig, fps: Fraction | None = None
) -> list[Segment]:
    """Keep-segments [(start, end)] in source seconds, sorted and disjoint."""
    pad, merge = cfg.cut_padding_ms / 1000, cfg.cut_merge_ms / 1000
    shrunk = []
    for s, e in sorted(cuts):
        s, e = max(s, 0.0), min(e, duration)
        s2 = s if s <= 0 else s + pad  # nothing to protect before the clip start
        e2 = e if e >= duration else e - pad
        if e2 > s2:
            shrunk.append((s2, e2))
    merged: list[list[float]] = []
    for s, e in shrunk:
        if merged and s - merged[-1][1] < merge:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keeps, t = [], 0.0
    for s, e in merged:
        keeps.append((t, s))
        t = max(t, e)
    keeps.append((t, duration))
    if fps:  # outward to whole frames: padding is never eaten; segments that now touch merge
        snapped: list[list[float]] = []
        for s, e in keeps:
            s, e = _frame(s, fps, math.floor), min(_frame(e, fps, math.ceil), duration)
            if snapped and s <= snapped[-1][1]:
                snapped[-1][1] = max(snapped[-1][1], e)
            else:
                snapped.append([s, e])
        keeps = [(s, e) for s, e in snapped]
    return [(s, e) for s, e in keeps if e - s >= cfg.min_segment_ms / 1000 - 1e-9]


def _frame(t: float, fps: Fraction, rounding: Callable[[float], int]) -> float:
    return float(rounding(t * fps - 1e-6 if rounding is math.ceil else t * fps + 1e-6) / fps)


def removed_s(keeps: Sequence[Segment], duration: float) -> float:
    return duration - sum(e - s for s, e in keeps)


def filter_graph(keeps: Sequence[Segment], fade_ms: int) -> str:
    """trim/atrim each keep-segment, fade the audio at every join, concat."""
    fade = fade_ms / 1000
    parts, labels = [], []
    for i, (s, e) in enumerate(keeps):
        audio = f"[0:a]atrim={s:.6f}:{e:.6f},asetpts=PTS-STARTPTS"
        if fade > 0 and i > 0:
            audio += f",afade=t=in:d={fade:.3f}"
        if fade > 0 and i < len(keeps) - 1:
            audio += f",afade=t=out:st={max(e - s - fade, 0):.6f}:d={fade:.3f}"
        parts.append(f"[0:v]trim={s:.6f}:{e:.6f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"{audio}[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(keeps)}:v=1:a=1[v][a]")
    return ";".join(parts)


# --- encoder selection -------------------------------------------------------------------------


def _listed_encoders() -> str:
    return _run(["ffmpeg", "-hide_banner", "-encoders"])


@cache
def _encodes_one_frame(encoder: str) -> bool:
    cmd = [
        *("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"),
        *("-f", "lavfi", "-i", "color=c=gray:s=256x256:d=0.1", "-frames:v", "1"),
        *("-c:v", encoder, *_ENCODER_ARGS[encoder], "-pix_fmt", "yuv420p", "-f", "null", "-"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode == 0


def select_encoder(
    preference: str = "auto",
    listed: Callable[[], str] = _listed_encoders,
    works: Callable[[str], bool] = _encodes_one_frame,
) -> str:
    """First usable encoder; a forced one that does not work falls back to libx264 (WARN)."""
    order = [*HARDWARE, "libx264"] if preference == "auto" else [preference]
    if sys.platform != "darwin" and preference == "auto":
        order.remove("h264_videotoolbox")  # Apple only; skip the probe elsewhere
    names = listed()
    for enc in order:
        if f" {enc} " in names and works(enc):
            return enc
    if preference != "auto":
        log.warning("encoder unavailable, falling back to libx264", extra={"encoder": preference})
    return "libx264"


# --- output files ------------------------------------------------------------------------------


def _retry(op: Callable[[], object], attempts: int = 20, delay_s: float = 0.1) -> None:
    """Windows: a virus scanner or the search indexer briefly locks a file just written
    (WinError 32), so a rename or delete right after the write can fail; try again shortly."""
    for i in range(attempts):
        try:
            op()
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay_s)


def move_into_place(tmp: Path, out_dir: Path, stem: str, suffix: str) -> Path:
    """Rename the finished temp file to a free <stem>_clean<suffix> name; never overwrites."""
    out = free_name(out_dir, stem, suffix)
    _retry(lambda: tmp.rename(out))  # Windows refuses to rename over an existing file anyway
    return out


def discard(tmp: Path) -> None:
    """Remove partial output; a file still locked is logged, not raised over the real error."""
    try:
        _retry(lambda: tmp.unlink(missing_ok=True))
    except OSError:
        log.warning("could not remove partial output", exc_info=True, extra={"file": tmp.name})


# --- FFmpeg ------------------------------------------------------------------------------------


def free_name(directory: Path, stem: str, suffix: str) -> Path:
    """<stem>_clean<suffix>, or _clean_2, _clean_3 ... : never an existing file."""
    path, n = directory / f"{stem}_clean{suffix}", 2
    while path.exists():
        path, n = directory / f"{stem}_clean_{n}{suffix}", n + 1
    return path


def encode_cmd(source: Path, keeps: Sequence[Segment], encoder: str, out: Path,
               cfg: RenderConfig, threads: int) -> list[str]:  # fmt: skip
    # shortcut: the graph is inline (~130 chars per segment), fine to ~200 segments on Windows'
    # 32k command line; write it to a file if 3-minute clips ever need more.
    return [
        *("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"),
        *("-threads", str(threads), "-i", str(source)),
        *("-filter_complex", filter_graph(keeps, cfg.join_fade_ms), "-map", "[v]", "-map", "[a]"),
        *("-c:v", encoder, *_ENCODER_ARGS[encoder], "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(out)),
    ]


Runner = Callable[[list[str]], str]


def render_mp4(
    source: Path,
    keeps: Sequence[Segment],
    out_dir: Path,
    cfg: RenderConfig,
    threads: int = 2,
    encoder: str | None = None,
    run: Runner = _run,
) -> tuple[Path, str]:
    """Encode ``keeps`` of ``source`` to out_dir/<stem>_clean.mp4. Returns (path, encoder)."""
    if not keeps:
        raise RenderError("plan", "every second of the clip is cut; nothing to render")
    encoder = encoder or select_encoder(cfg.encoder)
    tmp = out_dir / f".{source.stem}_clean.part.mp4"
    try:
        try:
            run(encode_cmd(source, keeps, encoder, tmp, cfg, threads))
        except FFmpegError as e:
            if encoder == "libx264":
                raise
            log.warning("hardware encoder failed, retrying with libx264",
                        extra={"encoder": encoder, "ffmpeg_stderr": e.stderr[-2000:]})  # fmt: skip
            encoder = "libx264"
            run(encode_cmd(source, keeps, encoder, tmp, cfg, threads))
        out = move_into_place(tmp, out_dir, source.stem, ".mp4")
    except FFmpegError as e:
        hint = " (disk full?)" if "No space left" in e.stderr else ""
        raise RenderError("encode", f"ffmpeg failed with {encoder}{hint}", e.stderr) from e
    except OSError as e:
        raise RenderError("move", f"cannot write the output in {out_dir}: {e}") from e
    finally:
        discard(tmp)  # partial output of a failed or interrupted render
    return out, encoder
