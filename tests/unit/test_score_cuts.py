import json
from pathlib import Path

from eval.score_cuts import load_clips, match, score, to_markdown
from stuttercut.rules import Cut
from stuttercut.storage import repo
from stuttercut.storage.db import connect


def pred(start: float, end: float, reason: str, source: str = "rules") -> dict[str, object]:
    return {"start": start, "end": end, "reason": reason, "source": source}


def label(start: float, end: float, kind: str) -> dict[str, object]:
    return {"start": start, "end": end, "type": kind}


def test_match_needs_same_type_and_both_edges_within_tolerance() -> None:
    preds = [pred(1.00, 1.30, "filler"), pred(5.0, 5.5, "repeat"), pred(9.0, 9.4, "filler")]
    labels = [label(1.10, 1.25, "filler"), label(5.0, 5.5, "filler"), label(9.0, 9.6, "filler")]
    pairs, fps, fns = match(preds, labels, tol=0.15)
    assert [(p["start"], lab["start"]) for p, lab in pairs] == [(1.0, 1.1)]
    assert len(fps) == 2 and len(fns) == 2  # wrong type; end 200 ms off


def test_match_is_one_to_one_closest_first() -> None:
    preds = [pred(1.0, 1.3, "pause"), pred(1.05, 1.3, "pause")]
    pairs, fps, fns = match(preds, [label(1.05, 1.3, "pause")], tol=0.15)
    assert pairs[0][0]["start"] == 1.05 and len(fps) == 1 and fns == []


def test_score_per_reason_source_and_clip() -> None:
    clips = {
        "c001": (
            [pred(1.0, 1.2, "filler"), pred(2.0, 2.3, "filler", "vad"), pred(4.0, 5.0, "pause")],
            [label(1.0, 1.2, "filler"), label(4.05, 5.0, "pause"), label(7.0, 7.4, "repeat")],
        )
    }
    s = score(clips, 0.15)
    assert s["overall"] == {"tp": 2, "fp": 1, "fn": 1, "precision": 0.667, "recall": 0.667,
                            "f1": 0.667}  # fmt: skip
    assert s["by_reason"]["filler"]["precision"] == 0.5
    assert s["by_reason"]["repeat"]["recall"] == 0.0
    assert s["by_reason"]["retake"]["precision"] is None
    assert s["by_source"] == {
        "rules": {"predicted": 2, "tp": 2, "fp": 0, "precision": 1.0},
        "vad": {"predicted": 1, "tp": 0, "fp": 1, "precision": 0.0},
    }
    assert s["clips"]["c001"]["review_effort"] == 2
    assert s["boundary_error_ms"] == 12.5  # (0+0+50+0)/4
    md = to_markdown(s, {"c002": "no labels"})
    assert "| **overall** | 2 | 1 | 1 | 67% | 67% | 67% |" in md and "c002 (no labels)" in md


def test_load_clips_reads_newest_ready_job_and_reports_skips(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "clips").mkdir(parents=True)
    media = root / "clips" / "c001.mp4"
    media.write_bytes(b"x")
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "c001.cuts.json").write_text(
        json.dumps({"clip_id": "c001", "cuts": [label(0.1, 0.3, "filler")]}), "utf-8"
    )
    (labels / "c003.cuts.json").write_text(json.dumps({"clip_id": "c003", "cuts": []}), "utf-8")
    conn = connect(tmp_path / "s.db")
    job = repo.create_job(conn, str(media.resolve()))
    repo.replace_cuts(conn, job, [Cut(0.1, 0.3, "filler", "rules", 0.9)])
    repo.set_status(conn, job, "ready_for_review")

    clips, skipped = load_clips(conn, root, labels, ["c001", "c002", "c003"])

    assert clips == {"c001": ([pred(0.1, 0.3, "filler")], [label(0.1, 0.3, "filler")])}
    assert skipped == {"c002": "no labels", "c003": "media file not found"}
