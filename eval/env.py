"""Settings for eval scripts: environment variables, falling back to the repo's .env file."""

import os
from pathlib import Path

from stuttercut.config import read_dotenv

REPO = Path(__file__).resolve().parent.parent
REPORTS = Path(__file__).parent / "reports"


def get_setting(name: str, dotenv: Path = REPO / ".env") -> str | None:
    """The environment wins over .env; empty values count as unset."""
    return os.environ.get(name) or read_dotenv(dotenv).get(name) or None


def data_dir(override: Path | None = None) -> Path:
    """$STUTTERCUT_DATA_DIR (env or .env) unless a path is given; must exist."""
    raw = override or get_setting("STUTTERCUT_DATA_DIR")
    if not raw:
        raise SystemExit("set STUTTERCUT_DATA_DIR in the environment or .env (or pass --data-dir)")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit(f"STUTTERCUT_DATA_DIR does not exist: {path}")
    return path


def newest_report(reports: Path = REPORTS) -> Path:
    """Newest eval/reports/<date> folder (one that holds a run.json)."""
    runs = sorted(p.parent for p in reports.glob("*/run.json"))
    if not runs:
        raise SystemExit(f"no reports in {reports}: run python -m eval.run_spike first")
    return runs[-1]
