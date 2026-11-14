import json
from pathlib import Path

import pytest

from eval.convert_audacity import convert_dir, main, parse_labels


def test_parses_sorts_and_skips_spectral_lines() -> None:
    text = "3.5\t3.9\tRepeat\n\\t100.0\t2000.0\n1.25\t1.6\tfiller\n\n5,0\t6,2\tpause\n"
    assert parse_labels(text) == [
        {"start": 1.25, "end": 1.6, "type": "filler"},
        {"start": 3.5, "end": 3.9, "type": "repeat"},
        {"start": 5.0, "end": 6.2, "type": "pause"},
    ]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("1.0\t2.0\tcough", "not in"),
        ("2.0\t2.0\tfiller", "start < end"),
        ("3.0\t2.0\tretake", "start < end"),
        ("a\t2.0\tfiller", "not numbers"),
        ("1.0\t2.0", "expected"),
    ],
)
def test_rejects_bad_lines_with_line_number(line: str, message: str) -> None:
    with pytest.raises(ValueError, match=message) as err:
        parse_labels("0.1\t0.2\tfiller\n" + line, "c001.txt")
    assert "c001.txt:2" in str(err.value)


def test_convert_dir_writes_one_json_per_clip(tmp_path: Path) -> None:
    src = tmp_path / "audacity"
    src.mkdir()
    (src / "c001.txt").write_text("0.5\t0.8\tfiller\n", encoding="utf-8")
    (src / "câu 2.txt").write_text("1.0\t2.0\tretake\n", encoding="utf-8")

    written = convert_dir(src, tmp_path / "labels")

    assert [p.name for p in written] == ["c001.cuts.json", "câu 2.cuts.json"]
    data = json.loads((tmp_path / "labels" / "c001.cuts.json").read_text(encoding="utf-8"))
    assert data == {"clip_id": "c001", "cuts": [{"start": 0.5, "end": 0.8, "type": "filler"}]}


def test_invalid_file_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "audacity"
    src.mkdir()
    (src / "c001.txt").write_text("0.5\t0.8\tfiller\n", encoding="utf-8")
    (src / "c002.txt").write_text("0.5\t0.8\tnoise\n", encoding="utf-8")

    assert main([str(src), str(tmp_path / "labels")]) == 1
    assert not (tmp_path / "labels").exists()
