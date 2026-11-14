import json
from pathlib import Path
from typing import Any

from eval.compare_html import build_page, write_pages
from eval.score_spike import repeat_indices


def w(word: str, start: float, end: float) -> dict[str, Any]:
    return {"word": word, "start": start, "end": end}


def result(words: list[dict[str, Any]]) -> dict[str, Any]:
    return {"model_id": "m", "device": "cpu", "rtf": 0.1, "peak_rss_mb": 100.0, "words": words}


def test_repeat_indices_marks_earlier_copies_only() -> None:
    words = [w("Tôi", 0, 1), w("tôi,", 1, 2), w("tôi", 2, 3), w("sẽ", 3, 4)]
    assert repeat_indices(words) == {0, 1}


def test_build_page_highlights_and_escapes() -> None:
    words = [w("ừm", 0.5, 0.7), w("tôi", 1.0, 1.2), w("tôi", 1.25, 1.4), w("<b>", 2.0, 2.1)]
    page = build_page(
        "c001", {"phowhisper": result(words), "crisperwhisper": None}, "file:///c/a%20b.mp4"
    )

    assert '<span class="w f" data-s="0.50" data-e="0.70" title="0.50 s">ừm</span>' in page
    assert '<span class="w r" data-s="1.00"' in page
    assert '<span class="w" data-s="1.25"' in page  # last copy is kept, not highlighted
    assert "&lt;b&gt;" in page and "<b>" not in page
    assert '<audio controls preload="metadata" src="file:///c/a%20b.mp4">' in page
    assert "no result" in page


def test_write_pages_one_per_clip_without_audio(tmp_path: Path) -> None:
    for model in ("whisper_baseline", "phowhisper"):
        (tmp_path / model).mkdir()
        (tmp_path / model / "c001.json").write_text(json.dumps(result([w("à", 0, 1)])), "utf-8")
    (tmp_path / "phowhisper" / "c002.json").write_text(json.dumps(result([])), "utf-8")

    pages = write_pages(tmp_path, root=None)

    assert [p.name for p in pages] == ["c001.html", "c002.html"]
    assert "audio not found" in pages[0].read_text(encoding="utf-8")


def test_write_pages_can_limit_models(tmp_path: Path) -> None:
    for model in ("crisperwhisper", "phowhisper"):
        (tmp_path / model).mkdir()
        (tmp_path / model / "c001.json").write_text(json.dumps(result([w("à", 0, 1)])), "utf-8")

    page = write_pages(tmp_path, root=None, only=["crisperwhisper"])[0].read_text("utf-8")

    assert "<h2>crisperwhisper</h2>" in page and "phowhisper" not in page
