"""Settings for eval scripts: environment variables, falling back to the repo's .env file."""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORTS = Path(__file__).parent / "reports"


def read_dotenv(path: Path = REPO / ".env") -> dict[str, str]:
    """Minimal KEY=VALUE parser: ignores blanks and comments, strips matching quotes."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.removeprefix("export ").strip()] = value
    return values


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
