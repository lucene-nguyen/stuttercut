from pathlib import Path

import pytest

from eval.ingest import find_media, ingest, read_index, sha256_file, split_for
from eval.manifest import load_manifest

HEADER = "clip_id,duration_s,speaker_id,mic,noise,split,notes\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "clips").mkdir(parents=True)
    (tmp_path / "manifest.csv").write_text(HEADER + "c001,161,s01,,,tune,pilot", encoding="utf-8")
    return tmp_path


def _clip(root: Path, name: str, content: bytes) -> Path:
    path = root / "data" / "clips" / name
    path.write_bytes(content)
    return path


def test_ingest_adds_hash_ids_keeps_c001_and_refuses_duplicates(root: Path) -> None:
    data, manifest = root / "data", root / "manifest.csv"
    _clip(root, "c001.mp4", b"pilot")
    new = _clip(root, "Bài 1 ghi âm.mp4", b"lesson one")
    _clip(root, "copy of bài 1.mp4", b"lesson one")
    _clip(root, "notes.txt", b"not media")

    result = ingest(data, manifest, probe=lambda p: 12.34)

    clip_id = sha256_file(new)[:8]
    assert result["added"] == [(clip_id, "Bài 1 ghi âm.mp4")]
    assert result["duplicates"] == [("copy of bài 1.mp4", "Bài 1 ghi âm.mp4")]
    rows = {c["clip_id"]: c for c in load_manifest(manifest)}
    assert set(rows) == {"c001", clip_id}
    assert rows[clip_id]["duration_s"] == 12.3
    assert rows[clip_id]["speaker_id"] == "s01"
    assert rows[clip_id]["split"] == split_for(sha256_file(new))
    index = {r["clip_id"]: r["original_name"] for r in read_index(data)}
    assert index == {"c001": "c001.mp4", clip_id: "Bài 1 ghi âm.mp4"}
    assert find_media(data, clip_id) == new


def test_ingest_is_idempotent(root: Path) -> None:
    data, manifest = root / "data", root / "manifest.csv"
    _clip(root, "a.mp4", b"a")
    ingest(data, manifest, probe=lambda p: 1.0)
    before = manifest.read_text(encoding="utf-8")

    assert ingest(data, manifest, probe=lambda p: 1.0) == {"added": [], "duplicates": []}
    assert manifest.read_text(encoding="utf-8") == before


def test_split_is_deterministic_and_roughly_70_30() -> None:
    import hashlib

    splits = [split_for(hashlib.sha256(str(i).encode()).hexdigest()) for i in range(1000)]
    assert splits == [split_for(hashlib.sha256(str(i).encode()).hexdigest()) for i in range(1000)]
    assert 0.65 < splits.count("tune") / 1000 < 0.75


def test_find_media_missing(root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_media(root / "data", "nope")
