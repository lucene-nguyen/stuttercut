import json
from pathlib import Path

import pytest

from eval.convert_audacity import parse_labels
from eval.prelabel import (
    candidate_labels,
    format_labels,
    parse_silences,
    pause_labels,
    pick_model,
)

SILENCEDETECT = """\
[silencedetect @ 0x1] silence_start: -0.0021
[silencedetect @ 0x1] silence_end: 0.82 | silence_duration: 0.8221
size=N/A time=00:00:05.00 bitrate=N/A
[silencedetect @ 0x1] silence_start: 2.5
[silencedetect @ 0x1] silence_end: 3.4 | silence_duration: 0.9
[silencedetect @ 0x1] silence_start: 4.6
"""


def test_parse_silences_clamps_and_closes_at_eof() -> None:
    assert parse_silences(SILENCEDETECT, duration=5.0) == [(0.0, 0.82), (2.5, 3.4), (4.6, 5.0)]


def test_pause_labels_trim_150ms_and_drop_short() -> None:
    labels = pause_labels([(0.0, 0.82), (2.5, 3.4), (4.6, 5.0)])
    assert [(round(s, 2), round(e, 2), t) for s, e, t in labels] == [
        (0.15, 0.67, "pause"),
        (2.65, 3.25, "pause"),
    ]


def test_candidates_and_audacity_format() -> None:
    words = [
        {"word": "Ờ,", "start": 0.9, "end": 1.1},
        {"word": "tôi", "start": 1.2, "end": 1.4},
        {"word": "tôi", "start": 1.45, "end": 1.6},
        {"word": "ừm", "start": 2.0, "end": 2.0},  # zero length: skipped
    ]
    text = format_labels([*candidate_labels(words), (0.15, 0.67, "pause")])
    assert text == (
        "0.150000\t0.670000\tpause\n0.900000\t1.100000\tfiller?\n1.200000\t1.400000\trepeat?\n"
    )
    with pytest.raises(ValueError, match="unconfirmed"):  # must be confirmed before converting
        parse_labels(text)


def _report(tmp_path: Path, models: list[str]) -> Path:
    for m in models:
        (tmp_path / m).mkdir()
        (tmp_path / m / "c001.json").write_text("{}", "utf-8")
    return tmp_path


def test_pick_model_by_priority_without_summary(tmp_path: Path) -> None:
    report = _report(tmp_path, ["whisper_baseline", "phowhisper"])
    assert pick_model(report, "c001") == "phowhisper"
    assert pick_model(report, "c999") is None


def test_pick_model_by_summary(tmp_path: Path) -> None:
    report = _report(tmp_path, ["crisperwhisper", "whisper_baseline"])
    models = {
        "crisperwhisper": {"filler_word_recall": 0.4, "recall": {"overall": 0.9}},
        "whisper_baseline": {"filler_word_recall": 0.7, "recall": {"overall": 0.5}},
    }
    (report / "summary.json").write_text(json.dumps({"models": models}), "utf-8")
    assert pick_model(report, "c001") == "whisper_baseline"
