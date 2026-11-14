"""Register new clips: python -m eval.ingest [--data-dir DIR] [--speaker s01]

Scans $STUTTERCUT_DATA_DIR/clips. Each new file gets clip_id = first 8 hex chars of its
SHA-256, a duration from ffprobe and a deterministic split (~70% tune / 30% heldout, from the
hash), and is appended to eval/manifest.csv. Files are never renamed or copied; the mapping
clip_id -> original file name lives in $STUTTERCUT_DATA_DIR/index.csv, outside the repo.
Files whose name is already a manifest clip_id (e.g. c001.mp4) keep that id.
Duplicate content is refused and reported (exit code 1).
"""

import argparse
import csv
import hashlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from eval.env import data_dir
from eval.manifest import COLUMNS, DEFAULT_PATH, load_manifest

MEDIA_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"}
INDEX_COLUMNS = ["clip_id", "sha256", "original_name"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def split_for(sha: str) -> str:
    """Deterministic ~70/30 split from the content hash."""
    return "tune" if int(sha[:8], 16) % 10 < 7 else "heldout"


def ffprobe_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration"]
    cmd += ["-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path.name}:\n{proc.stderr}")
    return float(proc.stdout.strip())


def read_index(root: Path) -> list[dict[str, str]]:
    path = root / "index.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_index(root: Path, rows: list[dict[str, str]]) -> None:
    with (root / "index.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, INDEX_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def find_media(root: Path, clip_id: str) -> Path:
    """clips/<clip_id>.* first, else the original file name recorded in index.csv."""
    matches = sorted(p for p in (root / "clips").glob(f"{clip_id}.*") if p.is_file())
    if matches:
        return matches[0]
    for row in read_index(root):
        if row["clip_id"] == clip_id and (root / "clips" / row["original_name"]).is_file():
            return root / "clips" / row["original_name"]
    raise FileNotFoundError(f"no media file for {clip_id} in {root / 'clips'}")


def ingest(
    root: Path,
    manifest: Path = DEFAULT_PATH,
    speaker: str = "s01",
    probe: Callable[[Path], float] = ffprobe_duration,
) -> dict[str, list[tuple[str, str]]]:
    """Returns {"added": [(clip_id, name)], "duplicates": [(name, existing name)]}."""
    index = read_index(root)
    by_sha = {row["sha256"]: row for row in index}
    taken = {row["clip_id"] for row in index}
    manifest_ids = {c["clip_id"] for c in load_manifest(manifest)}
    files = sorted(
        p for p in (root / "clips").iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXTS
    )
    added: list[tuple[str, str]] = []
    duplicates: list[tuple[str, str]] = []
    new_rows: list[dict[str, str]] = []
    for path in files:
        sha = sha256_file(path)
        if sha in by_sha:
            if by_sha[sha]["original_name"] != path.name:
                duplicates.append((path.name, by_sha[sha]["original_name"]))
            continue
        if path.stem in manifest_ids:  # already named after its clip_id (e.g. c001.mp4)
            clip_id = path.stem
        else:
            n = 8
            while sha[:n] in taken | manifest_ids:
                n += 2
            clip_id = sha[:n]
            new_rows.append(
                {
                    "clip_id": clip_id,
                    "duration_s": f"{probe(path):.1f}",
                    "speaker_id": speaker,
                    "mic": "",
                    "noise": "",
                    "split": split_for(sha),
                    "notes": "",
                }
            )
            added.append((clip_id, path.name))
        row = {"clip_id": clip_id, "sha256": sha, "original_name": path.name}
        index.append(row)
        by_sha[sha] = row
        taken.add(clip_id)

    write_index(root, index)
    if new_rows:
        text = manifest.read_text(encoding="utf-8")
        with manifest.open("a", encoding="utf-8", newline="") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            csv.DictWriter(f, COLUMNS, lineterminator="\n").writerows(new_rows)
        load_manifest(manifest)  # fail loudly if the result is not valid
    return {"added": added, "duplicates": duplicates}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--speaker", default="s01", help="speaker_id for new rows (default s01)")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    result = ingest(data_dir(args.data_dir), args.manifest, args.speaker)
    for clip_id, name in result["added"]:
        print(f"added {clip_id}  <- {name}")
    for name, existing in result["duplicates"]:
        print(f"DUPLICATE {name}: same content as {existing}; not added", file=sys.stderr)
    if not result["added"] and not result["duplicates"]:
        print("no new clips")
    return 1 if result["duplicates"] else 0


if __name__ == "__main__":
    sys.exit(main())
