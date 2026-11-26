"""Export review decisions from the app to eval/labels/<clip_id>.cuts.json (LEARNING-209).

Usage: python -m eval.export_reviews [--labels eval/labels] [--force]

A reviewed job (at least one decision saved in the Review screen) becomes the labels of its
clip: every cut the user approved or marked by hand (and did not keep) is a label
{"start", "end", "type"}; kept and undecided suggestions are not. The clip is the job's file
name: "<clip_id>.<ext>", or the original name recorded in $STUTTERCUT_DATA_DIR/index.csv.
The newest reviewed job per clip wins. A label file made another way (Audacity) is never
overwritten unless --force. Then: python -m eval.score_cuts.
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from eval.env import get_setting
from eval.ingest import read_index
from eval.manifest import load_manifest
from stuttercut.config import load_config
from stuttercut.storage import paths
from stuttercut.storage.db import connect

LABELS = Path(__file__).parent / "labels"
SOURCE = "review"  # marks a label file written by this script


def clip_of(source_path: str, clip_ids: set[str], index: list[dict[str, str]]) -> str | None:
    name = Path(source_path).name
    if Path(name).stem in clip_ids:
        return Path(name).stem
    return next((r["clip_id"] for r in index if r.get("original_name") == name), None)


def reviewed_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Jobs with at least one saved decision, newest first."""
    return list(
        conn.execute(
            "SELECT * FROM job WHERE id IN (SELECT job_id FROM cut WHERE decided_at IS NOT NULL)"
            " ORDER BY created_at DESC"
        )
    )


def labels_of(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT start_s, end_s, reason FROM cut WHERE job_id = ? AND approved = 1 AND kept = 0"
        " ORDER BY start_s",
        (job_id,),
    )
    return [{"start": round(r["start_s"], 3), "end": round(r["end_s"], 3), "type": r["reason"]}
            for r in rows]  # fmt: skip


def export(
    conn: sqlite3.Connection,
    labels_dir: Path,
    clip_ids: set[str],
    index: list[dict[str, str]],
    force: bool = False,
) -> dict[str, str]:
    """Returns {clip_id or job id: what happened}."""
    done: dict[str, str] = {}
    for job in reviewed_jobs(conn):
        clip = clip_of(job["source_path"], clip_ids, index)
        if clip is None:
            done[job["id"]] = (
                f"skipped: {Path(job['source_path']).name} is not a clip in the manifest"
            )
            continue
        if clip in done:
            continue  # an older review of the same clip
        out = labels_dir / f"{clip}.cuts.json"
        if out.exists() and not force:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if existing.get("source") != SOURCE:
                done[clip] = f"skipped: {out.name} holds other labels (use --force to replace)"
                continue
        cuts = labels_of(conn, job["id"])
        payload = {"clip_id": clip, "source": SOURCE, "job_id": job["id"], "cuts": cuts}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        done[clip] = f"{len(cuts)} cuts from job {job['id']}"
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--force", action="store_true", help="replace label files made another way")
    args = parser.parse_args()
    conn = connect(paths.db_path(load_config()))
    data = get_setting("STUTTERCUT_DATA_DIR")
    index = read_index(Path(data)) if data and Path(data).is_dir() else []
    clip_ids = {c["clip_id"] for c in load_manifest()}
    args.labels.mkdir(parents=True, exist_ok=True)
    result = export(conn, args.labels, clip_ids, index, args.force)
    for key, what in result.items():
        print(f"{key}: {what}")
    if not result:
        print("no reviewed jobs: review a clip in the app first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
