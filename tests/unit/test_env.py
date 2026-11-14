from pathlib import Path

import pytest

from eval.env import get_setting, newest_report, read_dotenv


def test_read_dotenv(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nLLM_API_KEY=\nSTUTTERCUT_DATA_DIR="C:\\data dir"\nexport X = 1\n', "utf-8"
    )
    assert read_dotenv(env) == {"LLM_API_KEY": "", "STUTTERCUT_DATA_DIR": r"C:\data dir", "X": "1"}


def test_environment_wins_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("STUTTERCUT_DATA_DIR=from-file\n", "utf-8")
    monkeypatch.delenv("STUTTERCUT_DATA_DIR", raising=False)
    assert get_setting("STUTTERCUT_DATA_DIR", env) == "from-file"
    monkeypatch.setenv("STUTTERCUT_DATA_DIR", "from-env")
    assert get_setting("STUTTERCUT_DATA_DIR", env) == "from-env"


def test_newest_report(tmp_path: Path) -> None:
    for name in ("2026-11-14", "2026-11-20", "2026-11-03"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "run.json").write_text("{}", "utf-8")
    (tmp_path / "2026-12-01").mkdir()  # no run.json: not a report
    assert newest_report(tmp_path).name == "2026-11-20"
