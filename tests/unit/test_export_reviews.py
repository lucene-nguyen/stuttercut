"""eval.export_reviews: review decisions -> eval/labels/<clip>.cuts.json."""

import json
from pathlib import Path

from eval.export_reviews import clip_of, export
from stuttercut.rules import Cut
from stuttercut.storage import repo
from stuttercut.storage.db import connect


def test_clip_of_uses_the_stem_or_the_index() -> None:
    index = [{"clip_id": "c002", "original_name": "bài 2 cài đặt.mp4"}]
    assert clip_of("/u/x/c001.mp4", {"c001", "c002"}, index) == "c001"
    assert clip_of("/u/y/bài 2 cài đặt.mp4", {"c001", "c002"}, index) == "c002"
    assert clip_of("/u/z/other.mp4", {"c001"}, index) is None


def test_export_writes_approved_and_hand_marked_cuts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "s.db")
    job = repo.create_job(conn, str(tmp_path / "c001.mp4"))
    repo.replace_cuts(conn, job, [Cut(0.1, 0.3, "filler", "rules", 0.9),
                                  Cut(1.0, 1.4, "repeat", "rules", 0.8),
                                  Cut(2.0, 2.2, "filler", "vad", 0.4)])  # fmt: skip
    a, b, _undecided = (c["id"] for c in repo.get_cuts(conn, job))
    repo.decide(conn, job, [a], keep=False)
    repo.decide(conn, job, [b], keep=True)
    repo.add_user_cut(conn, job, 3.0, 3.5, "retake")
    other = repo.create_job(conn, str(tmp_path / "not-in-manifest.mp4"))
    repo.replace_cuts(conn, other, [Cut(0.1, 0.3, "filler", "rules", 0.9)])
    repo.decide(conn, other, [repo.get_cuts(conn, other)[0]["id"]], keep=False)
    labels = tmp_path / "labels"
    labels.mkdir()

    result = export(conn, labels, {"c001"}, [])

    data = json.loads((labels / "c001.cuts.json").read_text(encoding="utf-8"))
    assert [{k: c[k] for k in ("start", "end", "type")} for c in data["cuts"]] == [
        {"start": 0.1, "end": 0.3, "type": "filler"}, {"start": 3.0, "end": 3.5, "type": "retake"},
    ]  # fmt: skip
    assert data["cuts"][0]["orig_start"] == 0.1 and data["cuts"][0]["edited"] is False
    assert data["source"] == "review" and data["job_id"] == job
    assert result["c001"].startswith("2 cuts") and "not a clip" in result[other]


def test_export_never_replaces_other_labels_without_force(tmp_path: Path) -> None:
    conn = connect(tmp_path / "s.db")
    job = repo.create_job(conn, str(tmp_path / "c001.mp4"))
    repo.add_user_cut(conn, job, 1.0, 1.5, "filler")
    labels = tmp_path / "labels"
    labels.mkdir()
    audacity = {"clip_id": "c001", "cuts": [{"start": 9.0, "end": 9.5, "type": "pause"}]}
    (labels / "c001.cuts.json").write_text(json.dumps(audacity), "utf-8")

    assert "skipped" in export(conn, labels, {"c001"}, [])["c001"]
    assert json.loads((labels / "c001.cuts.json").read_text("utf-8")) == audacity
    export(conn, labels, {"c001"}, [], force=True)
    assert json.loads((labels / "c001.cuts.json").read_text("utf-8"))["source"] == "review"


def test_export_keeps_original_and_edited_edges(tmp_path: Path) -> None:
    conn = connect(tmp_path / "s.db")
    job = repo.create_job(conn, str(tmp_path / "c001.mp4"))
    repo.replace_cuts(conn, job, [Cut(1.0, 1.4, "filler", "rules", 0.9)])
    cut_id = repo.get_cuts(conn, job)[0]["id"]
    repo.set_cut_edges(conn, job, cut_id, 0.95, 1.4)  # start moved by hand, end unchanged
    labels = tmp_path / "labels"
    labels.mkdir()
    export(conn, labels, {"c001"}, [])
    (cut,) = json.loads((labels / "c001.cuts.json").read_text("utf-8"))["cuts"]
    assert cut == {"start": 0.95, "end": 1.4, "type": "filler", "orig_start": 1.0,
                   "orig_end": 1.4, "edited": True}  # fmt: skip
