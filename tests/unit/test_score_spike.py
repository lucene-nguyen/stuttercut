import json
from pathlib import Path
from typing import Any

import pytest

from eval.score_spike import merge_counts, score_clip, score_report, summarize, to_markdown


def w(word: str, start: float, end: float) -> dict[str, Any]:
    return {"word": word, "start": start, "end": end}


def cut(start: float, end: float, kind: str) -> dict[str, Any]:
    return {"start": start, "end": end, "type": kind}


WORDS = [
    w("Tôi", 0.00, 0.30),
    w("ờ,", 0.50, 0.70),  # labelled filler, 50 ms late at the start
    w("tôi", 1.00, 1.20),  # labelled repeat
    w("tôi", 1.25, 1.45),
    w("sẽ", 1.50, 1.70),
    # gap 1.70 .. 2.60 holds the labelled pause
    w("nói", 2.60, 2.90),
    w("Ừm", 4.00, 4.20),  # filler-like word with no label -> hallucinated
]
CUTS = [
    cut(0.45, 0.70, "filler"),
    cut(1.00, 1.20, "repeat"),
    cut(1.85, 2.45, "pause"),
    cut(3.20, 3.60, "retake"),  # nothing transcribed there -> missed
    cut(5.00, 5.30, "filler"),  # nothing transcribed there -> missed
]


def test_score_clip_counts() -> None:
    c = score_clip(WORDS, CUTS, tol=0.15)
    assert c["labels"] == {"filler": 2, "repeat": 1, "retake": 1}
    assert c["captured"] == {"filler": 1, "repeat": 1, "retake": 0}
    assert c["filler_word_captured"] == 1
    assert c["boundary_ms"]["filler"] == pytest.approx([50.0, 0.0])
    assert c["boundary_ms"]["repeat"] == pytest.approx([0.0, 0.0])
    assert (c["pauses"], c["pauses_in_gap"]) == (1, 1)
    assert c["hallucinated_fillers"] == 1


def test_pause_crossed_by_a_word_is_not_in_gap() -> None:
    c = score_clip([w("dài", 1.0, 2.0)], [cut(1.5, 2.5, "pause")])
    assert c["pauses_in_gap"] == 0


def test_neighbour_inside_tolerance_counts_for_capture_but_not_boundary() -> None:
    # The only word ends 100 ms before the filler: captured (±150 ms) but not a boundary match.
    c = score_clip([w("rồi", 0.0, 0.40)], [cut(0.50, 0.70, "filler")])
    assert c["captured"]["filler"] == 1
    assert c["filler_word_captured"] == 0
    assert c["boundary_ms"]["filler"] == []


def test_summarize_and_merge() -> None:
    c = score_clip(WORDS, CUTS)
    s = summarize(merge_counts(c, c), audio_s=120.0, wall_s=30.0)
    assert s["recall"] == {"filler": 0.5, "repeat": 1.0, "retake": 0.0, "overall": 0.5}
    assert s["filler_word_recall"] == 0.5
    assert s["hallucinated_fillers_per_min"] == 1.0  # 2 over 2 minutes
    assert s["boundary_ms"] == {"filler": 25.0, "repeat": 0.0, "overall": 12.5}
    assert s["pause_gap_rate"] == 1.0
    assert s["rtf"] == 0.25


def test_summarize_with_no_labels_gives_none() -> None:
    s = summarize(score_clip(WORDS, []), audio_s=60.0, wall_s=6.0)
    assert s["recall"]["overall"] is None
    assert s["boundary_ms"]["overall"] is None


def test_score_report_end_to_end(tmp_path: Path) -> None:
    report, labels = tmp_path / "report", tmp_path / "labels"
    (report / "whisper_baseline").mkdir(parents=True)
    labels.mkdir()
    result = {
        "clip_id": "c001",
        "model_id": "large-v3",
        "device": "cpu",
        "word_timestamps": "native",
        "audio_s": 60.0,
        "wall_s": 15.0,
        "peak_rss_mb": 2048.4,
        "words": WORDS,
    }
    (report / "whisper_baseline" / "c001.json").write_text(json.dumps(result), "utf-8")
    (report / "whisper_baseline" / "c002.json").write_text(
        json.dumps({**result, "clip_id": "c002"}), "utf-8"
    )
    (labels / "c001.cuts.json").write_text(json.dumps({"clip_id": "c001", "cuts": CUTS}), "utf-8")

    summary = score_report(report, labels)

    m = summary["models"]["whisper_baseline"]
    assert m["clips"] == ["c001"]
    assert m["unlabelled_clips"] == ["c002"]
    assert m["rtf"] == 0.25
    assert m["peak_rss_mb"] == 2048
    md = to_markdown(summary)
    assert "| whisper_baseline | 1 |" in md
    assert "Tôi" not in md  # metrics only, never transcript text
