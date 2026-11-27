"""Render approved cuts into a clean MP4 (LEARNING-210): pure planning + a thin FFmpeg layer.

Planning (``plan``, pure; render, GET /plan and the saved time all use it), in this order:

1. **Group.** Sorted cuts merge into one group when the gap between them is under
   ``cut_merge_ms`` (50), or under ``merge_silent_gap_ms`` (150) with no transcript word in the
   gap. A gap that holds a word is never merged by the silent-gap rule. Merging comes before
   padding, so touching cuts never leave scraps between them.
2. **Pad the group's outer edges** (never at the clip's own start or end). An edge the user moved
   by hand, or the edge of a pause cut (the pause rule already keeps its margin), gets no padding.
   Otherwise: if the nearest kept word on that side is at least 2 x ``cut_padding_ms`` away, the
   edge moves *outward* by the padding, into the silence (the cut word goes fully, the neighbour
   keeps at least the padding); else it moves *inward* (protect the touching neighbour). Inward
   padding never makes a cut shorter than ``min_cut_ms`` (60): the padding shrinks instead. With
   no word data at all, padding goes inward. The clip edge counts as the neighbour when words
   exist but none is on that side.
3. **Frames.** Each cut edge snaps to the *nearest* frame of the source; a cut that rounds to
   less than one frame becomes exactly one frame around its middle, so every approved cut removes
   at least one frame. Snapped cuts that now overlap merge; the keep-segments are the rest, and
   keep-segments shorter than ``min_segment_ms`` are dropped (cut too). Video and audio are cut at
   the same frame times, so lip sync does not drift across joins.

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
# (start, end[, start_edited, end_edited[, pause]]): edited and pause-cut edges get no padding.
PlanCut = (
    tuple[float, float] | tuple[float, float, bool, bool] | tuple[float, float, bool, bool, bool]
)
Word = tuple[float, float]  # (start, end) of a transcript word


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


def _group(
    cuts: Sequence[PlanCut], duration: float, cfg: RenderConfig, words: Sequence[Word]
) -> list[list[float]]:
    """Step 1: [start, end, start_fixed, end_fixed] per group; fixed = no padding (1.0 / 0.0)."""
    merge, silent = cfg.cut_merge_ms / 1000, cfg.merge_silent_gap_ms / 1000
    groups: list[list[float]] = []
    for cut in sorted(cuts):
        s, e = max(cut[0], 0.0), min(cut[1], duration)
        if e <= s:
            continue
        pause = len(cut) == 5 and bool(cut[4])
        s_fixed = float(pause or (len(cut) >= 4 and bool(cut[2])))
        e_fixed = float(pause or (len(cut) >= 4 and bool(cut[3])))
        if groups:
            g = groups[-1]
            gap = s - g[1]
            silent_gap = gap < silent and not any(w0 < s and w1 > g[1] for w0, w1 in words)
            if gap < merge or silent_gap:
                if e >= g[1]:
                    g[1], g[3] = e, e_fixed
                continue
        groups.append([s, e, s_fixed, e_fixed])
    return groups


def _pad(
    g: list[float], duration: float, cfg: RenderConfig, kept: Sequence[Word], have_words: bool
) -> Segment:
    """Step 2: move each free outer edge outward into silence, or inward to protect a word."""
    pad, min_cut = cfg.cut_padding_ms / 1000, cfg.min_cut_ms / 1000
    s, e, s_fixed, e_fixed = g
    ds = de = 0.0
    if s > 0 and not s_fixed:
        prev_end = max((w1 for w0, w1 in kept if w0 < s), default=0.0)
        ds = -pad if have_words and s - prev_end >= 2 * pad else pad
    if e < duration and not e_fixed:
        next_start = min((w0 for w0, w1 in kept if w1 > e), default=duration)
        de = pad if have_words and next_start - e >= 2 * pad else -pad
    short = min_cut - ((e + de) - (s + ds))
    inward = max(ds, 0.0) + max(-de, 0.0)
    if short > 0 and inward > 0:  # inward padding never makes the cut shorter than min_cut
        keep = max(0.0, inward - short) / inward
        ds = ds * keep if ds > 0 else ds
        de = de * keep if de < 0 else de
    return max(0.0, s + ds), min(duration, e + de)


def plan(
    cuts: Sequence[PlanCut],
    duration: float,
    cfg: RenderConfig,
    fps: Fraction | None = None,
    words: Sequence[Word] = (),
) -> list[Segment]:
    """Keep-segments [(start, end)] in source seconds, sorted and disjoint (steps: docstring)."""
    groups = _group(cuts, duration, cfg, words)
    kept = [w for w in words if not any(g[0] <= (w[0] + w[1]) / 2 < g[1] for g in groups)]
    removed = [_pad(g, duration, cfg, kept, bool(words)) for g in groups]
    if fps:
        frame = float(1 / fps)

        def snap(t: float) -> float:
            if t <= 0 or t >= duration:
                return min(max(t, 0.0), duration)
            return min(float(math.floor(t * fps + 0.5 + 1e-9) / fps), duration)

        snapped = []
        for s, e in removed:
            s2, e2 = snap(s), snap(e)
            if e2 - s2 < frame - 1e-9:  # under one frame: exactly one frame around the middle
                s2 = float(math.floor((s + e) / 2 * fps) / fps)
                e2 = min(s2 + frame, duration)
                s2 = max(0.0, e2 - frame)
            snapped.append((s2, e2))
        removed = snapped
    merged: list[list[float]] = []
    for s, e in sorted(removed):
        if merged and s <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keeps, t = [], 0.0
    for s, e in merged:
        keeps.append((t, s))
        t = max(t, e)
    keeps.append((t, duration))
    return [(s, e) for s, e in keeps if e - s >= cfg.min_segment_ms / 1000 - 1e-9]


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
