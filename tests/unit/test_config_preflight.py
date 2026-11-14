import logging
from pathlib import Path

import pytest

from stuttercut.config import AsrConfig, load_config
from stuttercut.platform import InsufficientMemoryError, preflight_model_size


def test_defaults_match_design() -> None:
    cfg = load_config(env={}, dotenv=Path("missing.env"))
    assert (cfg.asr.model_size, cfg.asr.fallback_size) == ("large", "turbo")
    assert (cfg.asr.min_free_gb_large, cfg.asr.min_free_gb_any) == (6.0, 3.0)
    assert cfg.media.max_duration_s == 180.0
    assert (cfg.log.max_bytes, cfg.log.backup_count) == (5 * 1024 * 1024, 3)
    assert cfg.home is None


def test_env_overrides_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("STUTTERCUT_ASR_MODEL_SIZE=turbo\nSTUTTERCUT_MAX_DURATION_S=60\n", "utf-8")
    cfg = load_config(env={"STUTTERCUT_MAX_DURATION_S": "90"}, dotenv=dotenv)
    assert cfg.asr.model_size == "turbo"
    assert cfg.media.max_duration_s == 90.0


def test_bad_number_names_the_variable() -> None:
    with pytest.raises(ValueError, match="STUTTERCUT_ASR_MIN_FREE_GB_ANY"):
        load_config(env={"STUTTERCUT_ASR_MIN_FREE_GB_ANY": "lots"}, dotenv=Path("missing.env"))


@pytest.mark.parametrize(("free_gb", "expected"), [(16.0, "large"), (6.0, "large"), (5.9, "turbo")])
def test_preflight_picks_size(free_gb: float, expected: str) -> None:
    assert preflight_model_size(AsrConfig(), free_gb=free_gb) == expected


def test_preflight_warns_on_fallback(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="stuttercut.platform"):
        preflight_model_size(AsrConfig(), free_gb=4.0)
    assert caplog.records[0].levelname == "WARNING"
    assert caplog.records[0].using == "turbo"  # type: ignore[attr-defined]


def test_preflight_fails_below_minimum() -> None:
    with pytest.raises(InsufficientMemoryError, match=r"2.9 GB"):
        preflight_model_size(AsrConfig(), free_gb=2.9)


def test_preflight_keeps_turbo_when_configured() -> None:
    assert preflight_model_size(AsrConfig(model_size="turbo"), free_gb=4.0) == "turbo"
