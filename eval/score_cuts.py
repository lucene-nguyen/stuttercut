"""Score the cut detector against hand labels (Test Plan: Accuracy evaluation).

Usage: python -m eval.score_cuts [--tolerance 0.15] [--labels eval/labels] [--out DIR]

For every clip with eval/labels/<clip_id>.cuts.json, takes the newest ``ready_for_review`` job
in the app database whose source is that clip's file ($STUTTERCUT_DATA_DIR/clips, via
index.csv) and compares its active cuts (not kept by the user) with the labels.
A predicted cut matches a label when the types agree and both boundaries are within the
tolerance; matching is one-to-one, closest first. Prints which clips were skipped and why.
Writes cuts_summary.json / .md (metrics only, no text) to eval/reports/<today>/ by default.
"""

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from eval.env import REPORTS, data_dir
from eval.ingest import find_media
from eval.manifest import load_manifest
from stuttercut.config import load_config
from stuttercut.rules import REASONS
from stuttercut.storage import paths
from stuttercut.storage.db import connect

LABELS = Path(__file__).parent / "labels"
Span = dict[str, Any]  # {"start", "end", "type"/"reason", "source"?}


def match(
    preds: list[Span], labels: list[Span], tol: float
) -> tuple[list[tuple[Span, Span]], list[Span], list[Span]]:
    """One-to-one matching: same type, |start| and |end| offsets <= tol, smallest error first.

    Returns (matched (pred, label) pairs, unmatched preds = FP, unmatched labels = FN).
    """
    candidates = sorted(
        (abs(p["start"] - lab["start"]) + abs(p["end"] - lab["end"]), pi, li)
        for pi, p in enumerate(preds)
        for li, lab in enumerate(labels)
        if p["reason"] == lab["type"]
        and abs(p["start"] - lab["start"]) <= tol
        and abs(p["end"] - lab["end"]) <= tol
    )
    used_p: set[int] = set()
    used_l: set[int] = set()
    pairs = []
    for _err, pi, li in candidates:
        if pi not in used_p and li not in used_l:
            used_p.add(pi)
            used_l.add(li)
            pairs.append((preds[pi], labels[li]))
    fps = [p for i, p in enumerate(preds) if i not in used_p]
    fns = [lab for i, lab in enumerate(labels) if i not in used_l]
    return pairs, fps, fns


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": None if p is None else round(p, 3),
        "recall": None if r is None else round(r, 3),
        "f1": None if f1 is None else round(f1, 3),
    }


def score(clips: dict[str, tuple[list[Span], list[Span]]], tol: float) -> dict[str, Any]:
    """clips: clip_id -> (predicted cuts, labelled cuts). Returns the summary dict."""
    pairs_all: list[tuple[Span, Span]] = []
    fps_all: list[Span] = []
    fns_all: list[Span] = []
    per_clip = {}
    for clip_id, (preds, labels) in clips.items():
        pairs, fps, fns = match(preds, labels, tol)
        pairs_all += pairs
        fps_all += fps
        fns_all += fns
        per_clip[clip_id] = {
            **_prf(len(pairs), len(fps), len(fns)),
            "review_effort": len(fps) + len(fns),  # clicks to fix: wrong cuts + missed cuts
        }
    by_reason = {
        r: _prf(
            sum(p["reason"] == r for p, _ in pairs_all),
            sum(p["reason"] == r for p in fps_all),
            sum(lab["type"] == r for lab in fns_all),
        )
        for r in REASONS
    }
    sources = sorted(
        {p.get("source", "?") for p, _ in pairs_all} | {p.get("source", "?") for p in fps_all}
    )
    by_source = {}
    for s in sources:
        tp = sum(p.get("source") == s for p, _ in pairs_all)
        fp = sum(p.get("source") == s for p in fps_all)
        by_source[s] = {"predicted": tp + fp, "tp": tp, "fp": fp,
                        "precision": round(tp / (tp + fp), 3) if tp + fp else None}  # fmt: skip
    offsets = [abs(p[k] - lab[k]) * 1000 for p, lab in pairs_all for k in ("start", "end")]
    return {
        "tolerance_s": tol,
        "clips": per_clip,
        "overall": _prf(len(pairs_all), len(fps_all), len(fns_all)),
        "by_reason": by_reason,
        "by_source": by_source,
        "boundary_error_ms": round(mean(offsets), 1) if offsets else None,
    }


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.0%}"


def to_markdown(summary: dict[str, Any], skipped: dict[str, str]) -> str:
    o = summary["overall"]
    lines = [
        "# Cut detector scores",
        "",
        f"Match = same type and both boundaries within ±{summary['tolerance_s'] * 1000:.0f} ms. "
        f"Mean boundary error of matches: {summary['boundary_error_ms']} ms.",
        "",
        "| Reason | TP | FP | FN | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in [*summary["by_reason"].items(), ("**overall**", o)]:
        lines.append(f"| {name} | {m['tp']} | {m['fp']} | {m['fn']} | {_pct(m['precision'])} "
                     f"| {_pct(m['recall'])} | {_pct(m['f1'])} |")  # fmt: skip
    lines += [
        "",
        "| Source | Predicted | TP | FP | Precision |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for s, m in summary["by_source"].items():
        lines.append(f"| {s} | {m['predicted']} | {m['tp']} | {m['fp']} | {_pct(m['precision'])} |")
    lines += [
        "",
        "| Clip | TP | FP | FN | F1 | Review effort |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for clip, m in summary["clips"].items():
        lines.append(f"| {clip} | {m['tp']} | {m['fp']} | {m['fn']} | {_pct(m['f1'])} "
                     f"| {m['review_effort']} |")  # fmt: skip
    if skipped:
        lines += ["", "Skipped: " + "; ".join(f"{c} ({why})" for c, why in skipped.items())]
    return "\n".join(lines) + "\n"


def load_clips(
    conn: sqlite3.Connection, root: Path, labels_dir: Path, clip_ids: list[str]
) -> tuple[dict[str, tuple[list[Span], list[Span]]], dict[str, str]]:
    clips: dict[str, tuple[list[Span], list[Span]]] = {}
    skipped: dict[str, str] = {}
    for clip_id in clip_ids:
        label_file = labels_dir / f"{clip_id}.cuts.json"
        if not label_file.exists():
            skipped[clip_id] = "no labels"
            continue
        try:
            media = str(find_media(root, clip_id).resolve())
        except FileNotFoundError:
            skipped[clip_id] = "media file not found"
            continue
        job = conn.execute(
            "SELECT id FROM job WHERE source_path = ? AND status = 'ready_for_review'"
            " ORDER BY created_at DESC LIMIT 1",
            (media,),
        ).fetchone()
        if job is None:
            skipped[clip_id] = "no ready_for_review job (run python -m stuttercut.worker.cli)"
            continue
        preds = [
            {"start": r["start_s"], "end": r["end_s"], "reason": r["reason"], "source": r["source"]}
            for r in conn.execute("SELECT * FROM cut WHERE job_id = ? AND kept = 0", (job["id"],))
        ]
        labels = json.loads(label_file.read_text(encoding="utf-8"))["cuts"]
        clips[clip_id] = (preds, labels)
    return clips, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tolerance", type=float, default=0.15, help="seconds (default 0.15)")
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--out", type=Path, default=REPORTS / date.today().isoformat())
    args = parser.parse_args()

    conn = connect(paths.db_path(load_config()))
    clip_ids = [c["clip_id"] for c in load_manifest()]
    clips, skipped = load_clips(conn, data_dir(args.data_dir), args.labels, clip_ids)
    for clip_id, why in skipped.items():
        print(f"skipped {clip_id}: {why}")
    if not clips:
        print("nothing to score: label a clip (docs/guides/labelling-golden-clips.md)")
        return 1
    summary = score(clips, args.tolerance)
    md = to_markdown(summary, skipped)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cuts_summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    (args.out / "cuts_summary.md").write_text(md, "utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
