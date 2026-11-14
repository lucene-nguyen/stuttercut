"""Convert Audacity label exports to eval/labels/<clip_id>.cuts.json.

Usage: python -m eval.convert_audacity [<audacity_dir> <labels_dir>]
(default: $STUTTERCUT_DATA_DIR/audacity -> eval/labels)

Each line of an Audacity export is ``start<TAB>end<TAB>type``. Lines starting with a
backslash are spectral-selection extras and are skipped. A label file may be named after the
clip_id (c001.txt) or after the original video (as recorded in index.csv next to the audacity
folder). Pre-labels (*.prelabel.txt) are skipped, and unconfirmed types ending in "?" are
rejected: check each suggestion in Audacity and remove the "?".
"""

import json
import sys
from pathlib import Path
from typing import Any

from eval.env import data_dir
from eval.ingest import read_index

CUT_TYPES = ("filler", "repeat", "pause", "retake")


def parse_labels(text: str, source: str = "<labels>") -> list[dict[str, Any]]:
    """Parse one Audacity export; raise ValueError listing every bad line."""
    cuts: list[dict[str, Any]] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            errors.append(f"{source}:{n}: expected start<TAB>end<TAB>type, got {raw!r}")
            continue
        try:
            # Some locales export decimal commas.
            start, end = (float(p.replace(",", ".")) for p in parts[:2])
        except ValueError:
            errors.append(f"{source}:{n}: start/end are not numbers: {raw!r}")
            continue
        cut_type = parts[2].strip().lower()
        if cut_type.endswith("?"):
            errors.append(f"{source}:{n}: unconfirmed label {parts[2]!r}: check it, remove the '?'")
        elif cut_type not in CUT_TYPES:
            errors.append(f"{source}:{n}: type {parts[2]!r} not in {CUT_TYPES}")
        elif not 0 <= start < end:
            errors.append(f"{source}:{n}: need 0 <= start < end, got {start} .. {end}")
        else:
            cuts.append({"start": round(start, 3), "end": round(end, 3), "type": cut_type})
    if errors:
        raise ValueError("\n".join(errors))
    return sorted(cuts, key=lambda c: (c["start"], c["end"]))


def resolve_clip_id(stem: str, index: list[dict[str, str]]) -> str:
    """Label file stem -> clip_id: a clip_id as is, or an original video name via index.csv."""
    if not index or stem in {row["clip_id"] for row in index}:
        return stem
    for row in index:
        if Path(row["original_name"]).stem == stem:
            return row["clip_id"]
    raise ValueError(f"{stem}.txt: no clip with this id or original file name in index.csv")


def convert_dir(
    audacity_dir: Path, labels_dir: Path, index: list[dict[str, str]] | None = None
) -> list[Path]:
    """Convert every label *.txt in audacity_dir. Writes nothing if any file is invalid."""
    files = sorted(f for f in audacity_dir.glob("*.txt") if not f.name.endswith(".prelabel.txt"))
    if not files:
        raise ValueError(f"no *.txt label files in {audacity_dir}")
    results: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for f in files:
        try:
            clip_id = resolve_clip_id(f.stem, index or [])
            if clip_id in results:
                raise ValueError(f"{f.name}: a second label file for clip {clip_id}")
            results[clip_id] = parse_labels(f.read_text(encoding="utf-8-sig"), f.name)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        raise ValueError("\n".join(errors))
    labels_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for clip_id, cuts in results.items():
        out = labels_dir / f"{clip_id}.cuts.json"
        payload = {"clip_id": clip_id, "cuts": cuts}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(out)
    return written


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        audacity_dir, labels_dir = Path(argv[0]), Path(argv[1])
    elif not argv:
        audacity_dir, labels_dir = data_dir() / "audacity", Path(__file__).parent / "labels"
    else:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        written = convert_dir(audacity_dir, labels_dir, read_index(audacity_dir.parent))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
