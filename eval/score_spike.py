"""Score ASR spike transcripts against labelled cuts.

Usage: python -m eval.score_spike [<report_dir>] [--labels eval/labels] [--tolerance 0.15]
(report_dir defaults to the newest eval/reports/<date> folder)

Reads <report_dir>/<model>/<clip_id>.json (written by run_spike.py) and
eval/labels/<clip_id>.cuts.json, then writes <report_dir>/summary.json and summary.md.
Only metrics are written; no transcript text.
"""

import argparse
import json
import unicodedata
from pathlib import Path
from statistics import mean
from typing import Any

from eval.env import newest_report

FILLER_WORDS = frozenset(unicodedata.normalize("NFC", w) for w in ("ờ", "à", "ừm", "ừ"))
CAPTURE_TYPES = ("filler", "repeat", "retake")
BOUNDARY_TYPES = ("filler", "repeat")


def normalize(word: str) -> str:
    """NFC, lower case, punctuation stripped (so "Ừm," == "ừm")."""
    w = unicodedata.normalize("NFC", word).lower()
    return "".join(ch for ch in w if ch.isalnum())


def overlaps(word: dict[str, Any], start: float, end: float, tol: float = 0.0) -> bool:
    return bool(word["start"] < end + tol and word["end"] > start - tol)


def score_clip(
    words: list[dict[str, Any]], cuts: list[dict[str, Any]], tol: float = 0.15
) -> dict[str, Any]:
    """Raw counts for one clip; aggregate with merge_counts()."""
    c: dict[str, Any] = {
        "labels": dict.fromkeys(CAPTURE_TYPES, 0),
        "captured": dict.fromkeys(CAPTURE_TYPES, 0),
        "filler_word_captured": 0,
        "boundary_ms": {t: [] for t in BOUNDARY_TYPES},
        "pauses": 0,
        "pauses_in_gap": 0,
        "hallucinated_fillers": 0,
    }
    for cut in cuts:
        s, e, kind = cut["start"], cut["end"], cut["type"]
        if kind == "pause":
            c["pauses"] += 1
            # The labelled pause is already trimmed, so no tolerance: no word may cross it.
            c["pauses_in_gap"] += not any(overlaps(w, s, e) for w in words)
            continue
        hits = [w for w in words if overlaps(w, s, e, tol)]
        c["labels"][kind] += 1
        c["captured"][kind] += bool(hits)
        if kind == "filler":
            c["filler_word_captured"] += any(normalize(w["word"]) in FILLER_WORDS for w in hits)
        if kind in BOUNDARY_TYPES:
            # Matching words: midpoint inside the span (+/- tol), so neighbours do not count.
            match = [w for w in hits if s - tol <= (w["start"] + w["end"]) / 2 <= e + tol]
            if match:
                c["boundary_ms"][kind] += [
                    abs(min(w["start"] for w in match) - s) * 1000,
                    abs(max(w["end"] for w in match) - e) * 1000,
                ]
    c["hallucinated_fillers"] = sum(
        normalize(w["word"]) in FILLER_WORDS
        and not any(overlaps(w, cut["start"], cut["end"], tol) for cut in cuts)
        for w in words
    )
    return c


def merge_counts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in a.items():
        if isinstance(value, dict):
            out[key] = merge_counts(value, b[key])
        else:
            out[key] = value + b[key]
    return out


def _ratio(num: float, den: float, digits: int = 3) -> float | None:
    return round(num / den, digits) if den else None


def summarize(counts: dict[str, Any], audio_s: float, wall_s: float) -> dict[str, Any]:
    labels, captured = counts["labels"], counts["captured"]
    boundary = counts["boundary_ms"]
    all_boundary = [x for t in BOUNDARY_TYPES for x in boundary[t]]
    return {
        "recall": {
            **{t: _ratio(captured[t], labels[t]) for t in CAPTURE_TYPES},
            "overall": _ratio(sum(captured.values()), sum(labels.values())),
        },
        "labels": labels,
        "filler_word_recall": _ratio(counts["filler_word_captured"], labels["filler"]),
        "hallucinated_fillers_per_min": _ratio(counts["hallucinated_fillers"], audio_s / 60, 2),
        "boundary_ms": {
            **{t: round(mean(boundary[t]), 1) if boundary[t] else None for t in BOUNDARY_TYPES},
            "overall": round(mean(all_boundary), 1) if all_boundary else None,
        },
        "pause_gap_rate": _ratio(counts["pauses_in_gap"], counts["pauses"]),
        "pauses": counts["pauses"],
        "rtf": _ratio(wall_s, audio_s),
    }


def score_report(report_dir: Path, labels_dir: Path, tol: float = 0.15) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for model_dir in sorted(p for p in report_dir.iterdir() if p.is_dir()):
        total: dict[str, Any] | None = None
        audio_s = wall_s = 0.0
        peak_mb = 0.0
        scored, unlabelled = [], []
        meta: dict[str, Any] = {}
        for result_file in sorted(model_dir.glob("*.json")):
            result = json.loads(result_file.read_text(encoding="utf-8"))
            label_file = labels_dir / f"{result['clip_id']}.cuts.json"
            if not label_file.exists():
                unlabelled.append(result["clip_id"])
                continue
            cuts = json.loads(label_file.read_text(encoding="utf-8"))["cuts"]
            counts = score_clip(result["words"], cuts, tol)
            total = counts if total is None else merge_counts(total, counts)
            audio_s += result["audio_s"]
            wall_s += result["wall_s"]
            peak_mb = max(peak_mb, result["peak_rss_mb"])
            scored.append(result["clip_id"])
            meta = {k: result[k] for k in ("model_id", "device", "word_timestamps")}
        if total is None:
            continue
        models[model_dir.name] = {
            **meta,
            "clips": scored,
            "unlabelled_clips": unlabelled,
            "audio_min": round(audio_s / 60, 2),
            **summarize(total, audio_s, wall_s),
            "peak_rss_mb": round(peak_mb),
        }
    return {"tolerance_s": tol, "models": models}


def _fmt(v: Any, pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:.0%}" if pct else str(v)


def to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# ASR spike summary",
        "",
        f"Tolerance ±{summary['tolerance_s'] * 1000:.0f} ms. Recall = labelled cut has an "
        "overlapping word. Filler-word recall = a filler word (ờ, à, ừm, ừ) overlaps it.",
        "",
        "| Model | Clips | Audio min | Recall filler | Recall repeat | Recall retake | "
        "Recall overall | Filler-word recall | Halluc. fillers/min | Boundary ms "
        "(filler / repeat / all) | Pauses in gap | RTF | Peak RSS MB |",
        "| --- " + "| ---: " * 8 + "| --- " + "| ---: " * 3 + "|",
    ]
    for name, m in summary["models"].items():
        r, b, n = m["recall"], m["boundary_ms"], m["labels"]
        lines.append(
            f"| {name} | {len(m['clips'])} | {m['audio_min']} "
            f"| {_fmt(r['filler'], True)} (n={n['filler']}) "
            f"| {_fmt(r['repeat'], True)} (n={n['repeat']}) "
            f"| {_fmt(r['retake'], True)} (n={n['retake']}) "
            f"| {_fmt(r['overall'], True)} | {_fmt(m['filler_word_recall'], True)} "
            f"| {_fmt(m['hallucinated_fillers_per_min'])} "
            f"| {_fmt(b['filler'])} / {_fmt(b['repeat'])} / {_fmt(b['overall'])} "
            f"| {_fmt(m['pause_gap_rate'], True)} (n={m['pauses']}) "
            f"| {_fmt(m['rtf'])} | {m['peak_rss_mb']} |"
        )
    lines += [
        "",
        "Models: "
        + ", ".join(
            f"{k} = `{m['model_id']}` on {m['device']} (word timestamps: {m['word_timestamps']})"
            for k, m in summary["models"].items()
        ),
    ]
    return "\n".join(lines) + "\n"


LABELS = Path(__file__).parent / "labels"


def write_summary(report_dir: Path, labels_dir: Path = LABELS, tol: float = 0.15) -> dict[str, Any]:
    """Score and write summary.md/json; writes nothing when no clip has labels yet."""
    summary = score_report(report_dir, labels_dir, tol)
    if summary["models"]:
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
        (report_dir / "summary.md").write_text(to_markdown(summary), "utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report_dir", type=Path, nargs="?", help="default: newest report")
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--tolerance", type=float, default=0.15, help="seconds (default 0.15)")
    args = parser.parse_args()
    report_dir = args.report_dir or newest_report()
    if not write_summary(report_dir, args.labels, args.tolerance)["models"]:
        raise SystemExit(f"nothing to score in {report_dir} (no labelled clips?)")
    print(f"wrote {report_dir / 'summary.md'} and summary.json")


if __name__ == "__main__":
    main()
