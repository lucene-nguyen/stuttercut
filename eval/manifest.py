"""Load and validate eval/manifest.csv (columns: see docs/guides/labelling-golden-clips.md)."""

import csv
from pathlib import Path
from typing import Any

COLUMNS = ["clip_id", "duration_s", "speaker_id", "mic", "noise", "split", "notes"]
SPLITS = ("tune", "heldout")
DEFAULT_PATH = Path(__file__).parent / "manifest.csv"


def load_manifest(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    """Return one dict per clip; raise ValueError listing every problem."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}, got {reader.fieldnames}")
        rows = list(reader)

    errors: list[str] = []
    seen: set[str] = set()
    clips = []
    for n, row in enumerate(rows, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # blank line
        clip_id = (row["clip_id"] or "").strip()
        where = f"{path.name}:{n}"
        if not clip_id:
            errors.append(f"{where}: clip_id is empty")
        elif clip_id in seen:
            errors.append(f"{where}: duplicate clip_id {clip_id}")
        seen.add(clip_id)
        try:
            duration = float(row["duration_s"])
            if duration <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(
                f"{where}: duration_s must be a positive number, got {row['duration_s']!r}"
            )
            duration = 0.0
        if not (row["speaker_id"] or "").strip():
            errors.append(f"{where}: speaker_id is empty")
        if row["split"] not in SPLITS:
            errors.append(f"{where}: split must be one of {SPLITS}, got {row['split']!r}")
        clips.append({**row, "clip_id": clip_id, "duration_s": duration})
    if errors:
        raise ValueError("\n".join(errors))
    return clips
