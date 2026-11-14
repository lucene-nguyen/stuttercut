"""Convert Audacity label exports to eval/labels/<clip_id>.cuts.json.

Usage: python -m eval.convert_audacity <audacity_dir> <labels_dir>

Each line of an Audacity export is ``start<TAB>end<TAB>type``. Lines starting with a
backslash are spectral-selection extras and are skipped.
"""

import json
import sys
from pathlib import Path
from typing import Any

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
        if cut_type not in CUT_TYPES:
            errors.append(f"{source}:{n}: type {parts[2]!r} not in {CUT_TYPES}")
        elif not 0 <= start < end:
            errors.append(f"{source}:{n}: need 0 <= start < end, got {start} .. {end}")
        else:
            cuts.append({"start": round(start, 3), "end": round(end, 3), "type": cut_type})
    if errors:
        raise ValueError("\n".join(errors))
    return sorted(cuts, key=lambda c: (c["start"], c["end"]))


def convert_dir(audacity_dir: Path, labels_dir: Path) -> list[Path]:
    """Convert every *.txt in audacity_dir. Writes nothing if any file is invalid."""
    files = sorted(audacity_dir.glob("*.txt"))
    if not files:
        raise ValueError(f"no *.txt label files in {audacity_dir}")
    results = {f.stem: parse_labels(f.read_text(encoding="utf-8-sig"), f.name) for f in files}
    labels_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for clip_id, cuts in results.items():
        out = labels_dir / f"{clip_id}.cuts.json"
        payload = {"clip_id": clip_id, "cuts": cuts}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(out)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        written = convert_dir(Path(argv[0]), Path(argv[1]))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
