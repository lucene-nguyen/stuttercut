"""Draft labels for Audacity: python -m eval.prelabel <clip_id> [--model NAME] [--force]

Writes $STUTTERCUT_DATA_DIR/audacity/<clip_id>.prelabel.txt (Audacity label format):
- "pause": FFmpeg silencedetect (> 600 ms below -35 dB), trimmed 150 ms each side as in the
  labelling guide;
- "filler?" / "repeat?": filler words (ờ, à, ừm, ừ) and earlier copies of immediate repeats
  from the best transcript in the newest report.
Import it in Audacity (File > Import > Labels), fix and confirm each suggestion (remove "?"),
then export your labels as <clip_id>.txt. convert_audacity skips *.prelabel.txt files.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from eval.env import data_dir, newest_report
from eval.ingest import ffprobe_duration, find_media
from eval.score_spike import is_filler, repeat_indices

SILENCE_DB = -35
MIN_PAUSE_S = 0.6
PAUSE_PAD_S = 0.15
# Without a summary, prefer verbatim models: they are the ones expected to keep disfluencies.
MODEL_PRIORITY = ("crisperwhisper", "phowhisper", "whisper_baseline")

_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: (-?[\d.]+)")


def parse_silences(stderr: str, duration: float) -> list[tuple[float, float]]:
    """(start, end) pairs from silencedetect output; an unterminated silence ends at EOF."""
    silences = []
    start: float | None = None
    for line in stderr.splitlines():
        if m := _START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None and start < duration:
        silences.append((start, duration))
    return silences


def pause_labels(silences: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    return [
        (s + PAUSE_PAD_S, e - PAUSE_PAD_S, "pause") for s, e in silences if e - s >= MIN_PAUSE_S
    ]


def candidate_labels(words: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    repeats = repeat_indices(words)
    labels = []
    for i, w in enumerate(words):
        if w["end"] <= w["start"]:
            continue  # zero-length words cannot be labelled
        if is_filler(w["word"]):
            labels.append((w["start"], w["end"], "filler?"))
        elif i in repeats:
            labels.append((w["start"], w["end"], "repeat?"))
    return labels


def format_labels(labels: list[tuple[float, float, str]]) -> str:
    return "".join(f"{s:.6f}\t{e:.6f}\t{t}\n" for s, e, t in sorted(labels))


def pick_model(report_dir: Path, clip_id: str) -> str | None:
    """Best model with a transcript for this clip: by summary scores if any, else priority."""
    have = [p.name for p in report_dir.iterdir() if (p / f"{clip_id}.json").exists()]
    if not have:
        return None
    summary_file = report_dir / "summary.json"
    if summary_file.exists():
        scores = json.loads(summary_file.read_text(encoding="utf-8"))["models"]
        scored = [m for m in have if m in scores]
        if scored:
            return max(
                scored,
                key=lambda m: (
                    scores[m]["filler_word_recall"] or 0,
                    scores[m]["recall"]["overall"] or 0,
                ),
            )
    return min(have, key=lambda m: MODEL_PRIORITY.index(m) if m in MODEL_PRIORITY else 99)


def silencedetect(media: Path) -> str:
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(media), "-vn"]
    cmd += ["-af", f"silencedetect=noise={SILENCE_DB}dB:d={MIN_PAUSE_S}", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg silencedetect failed for {media.name}:\n{proc.stderr}")
    return proc.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clip_id")
    parser.add_argument("--report", type=Path, help="default: newest eval/reports folder")
    parser.add_argument("--model", help="transcript to use (default: best available)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing prelabel")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    root = data_dir(args.data_dir)
    out = root / "audacity" / f"{args.clip_id}.prelabel.txt"
    if out.exists() and not args.force:
        print(f"{out} exists (it may hold your edits); pass --force to overwrite", file=sys.stderr)
        return 1
    media = find_media(root, args.clip_id)
    labels = pause_labels(parse_silences(silencedetect(media), ffprobe_duration(media)))
    n_pauses = len(labels)

    report = args.report or newest_report()
    model = args.model or pick_model(report, args.clip_id)
    transcript = report / str(model) / f"{args.clip_id}.json"
    if model and transcript.exists():
        words = json.loads(transcript.read_text(encoding="utf-8"))["words"]
        labels += candidate_labels(words)
    else:
        print(f"no transcript for {args.clip_id} in {report}: pauses only", file=sys.stderr)

    out.parent.mkdir(exist_ok=True)
    out.write_text(format_labels(labels), encoding="utf-8")
    kinds = [t for *_, t in labels]
    print(
        f"wrote {out}: {n_pauses} pause, {kinds.count('filler?')} filler?, "
        f"{kinds.count('repeat?')} repeat? (transcript: {model or 'none'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
