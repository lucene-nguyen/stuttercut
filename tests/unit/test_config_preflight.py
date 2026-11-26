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


def test_asr_passes_default_and_override() -> None:
    assert load_config(env={}, dotenv=Path("missing.env")).asr.passes == "verbatim"
    cfg = load_config(env={"STUTTERCUT_ASR_PASSES": "dual"}, dotenv=Path("missing.env"))
    assert cfg.asr.passes == "dual"


@pytest.mark.parametrize(
    ("name", "value"), [("STUTTERCUT_ASR_PASSES", "both"), ("STUTTERCUT_ASR_BACKEND", "onnx")]
)
def test_bad_choice_names_the_variable(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        load_config(env={name: value}, dotenv=Path("missing.env"))


def test_fake_transcriber_follows_passes(tmp_path: Path) -> None:
    from stuttercut.asr.fake import FakeTranscriber
    from tests.conftest import FIXTURES

    fixture = FIXTURES / "synthetic_pair.json"
    assert FakeTranscriber(fixture).transcribe(tmp_path / "a.wav").intended is None
    dual = FakeTranscriber(fixture, passes="dual").transcribe(tmp_path / "a.wav")
    assert dual.intended is not None and len(dual.intended) == 6
    with pytest.raises(ValueError, match="passes"):
        FakeTranscriber(fixture, passes="intended")


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


def test_rules_thresholds_from_env() -> None:
    env = {
        "STUTTERCUT_PAUSE_MIN_MS": "800",
        "STUTTERCUT_FILLER_TOKENS": " ờ, [UH] ,,ừm ",
        "STUTTERCUT_REPEAT_KEEP": "từ từ,dần dần",
    }
    rules = load_config(env=env, dotenv=Path("missing.env")).rules
    assert rules.pause_min_ms == 800 and rules.pause_keep_ms == 150
    assert rules.filler_tokens == ("ờ", "[UH]", "ừm")
    assert rules.repeat_keep == ("từ từ", "dần dần")


def test_llm_defaults_off_and_env_overrides() -> None:
    off = load_config(env={}, dotenv=Path("missing.env")).llm
    assert (off.enabled, off.provider, off.model, off.timeout_s) == (
        False,
        "ollama",
        "qwen3:8b",
        30.0,
    )
    env = {
        "STUTTERCUT_LLM_ENABLED": "yes",
        "LLM_API_KEY": "secret-123",
        "STUTTERCUT_LLM_WEIGHT": "0.5",
    }
    on = load_config(env=env, dotenv=Path("missing.env")).llm
    assert on.enabled and on.weight == 0.5 and on.api_key == "secret-123"
    assert "secret-123" not in repr(on)


@pytest.mark.parametrize(
    ("env", "model"),
    [
        ({"STUTTERCUT_LLM_PROVIDER": "anthropic"}, "claude-sonnet-5-5"),
        ({"STUTTERCUT_LLM_PROVIDER": "ollama", "STUTTERCUT_LLM_MODEL": "qwen2.5:7b"}, "qwen2.5:7b"),
    ],
)
def test_llm_model_defaults_per_provider(env: dict[str, str], model: str) -> None:
    assert load_config(env=env, dotenv=Path("missing.env")).llm.model == model


def test_unknown_llm_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="STUTTERCUT_LLM_PROVIDER"):
        load_config(env={"STUTTERCUT_LLM_PROVIDER": "openai"}, dotenv=Path("missing.env"))


def test_bad_llm_values_do_not_echo_the_key() -> None:
    with pytest.raises(ValueError, match="STUTTERCUT_LLM_ENABLED"):
        load_config(env={"STUTTERCUT_LLM_ENABLED": "maybe"}, dotenv=Path("missing.env"))


def test_step_timeouts_scale_with_clip_length() -> None:
    from stuttercut.config import LimitsConfig

    lim = LimitsConfig()
    assert lim.step_timeout_s("transcribe", 180) == 60 + 1.5 * 180  # 5.5 min for 3 min
    assert lim.step_timeout_s("render", 120) == 180
    assert lim.step_timeout_s("detect", 100) == 110
    assert lim.step_timeout_s("load_model", 180) == 300  # not scaled
    assert lim.step_timeout_s("transcribe", None) == 60 + 1.5 * 180  # unknown length: 3 min
    on = load_config(
        env={"STUTTERCUT_WORKER_MAX_RSS_GB": "10", "STUTTERCUT_MODEL_IDLE_UNLOAD_S": "0"}
    )
    assert (on.limits.worker_max_rss_gb, on.limits.model_idle_unload_s) == (10.0, 0.0)
