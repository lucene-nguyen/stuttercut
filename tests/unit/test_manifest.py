from pathlib import Path

import pytest

from eval.manifest import DEFAULT_PATH, load_manifest

HEADER = "clip_id,duration_s,speaker_id,mic,noise,split,notes\n"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "manifest.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_repo_manifest_is_valid() -> None:
    load_manifest(DEFAULT_PATH)


def test_loads_rows(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "c001,142,s01,laptop,quiet,tune,\nc002,95.5,s01,headset,noisy,heldout,x\n"
    )
    clips = load_manifest(path)
    assert [c["clip_id"] for c in clips] == ["c001", "c002"]
    assert clips[1]["duration_s"] == 95.5


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("c001,142,s01,laptop,quiet,train,\n", "split"),
        ("c001,-1,s01,laptop,quiet,tune,\n", "duration_s"),
        ("c001,142,,laptop,quiet,tune,\n", "speaker_id"),
        (",142,s01,laptop,quiet,tune,\n", "clip_id is empty"),
        ("c001,142,s01,laptop,quiet,tune,\nc001,90,s01,laptop,quiet,tune,\n", "duplicate"),
    ],
)
def test_rejects_bad_rows(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_manifest(_write(tmp_path, body))


def test_rejects_wrong_header(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text("clip,duration\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        load_manifest(path)
