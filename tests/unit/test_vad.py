"""SileroVad wrapper with fake torch/silero modules (no model, no torch needed)."""

import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from stuttercut.config import RulesConfig
from stuttercut.media.vad import SileroVad


@pytest.fixture
def fake_libs(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(threads=8, calls=[])

    def set_threads(n: int) -> None:
        state.threads = n

    def load_model() -> str:
        set_threads(1)  # what importing the real silero_vad does to the whole process
        return "model"

    def speech(audio: object, model: str, **kw: object) -> list[dict[str, float]]:
        state.calls.append(kw)
        return [{"start": 0.5, "end": 1.25}]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        get_num_threads=lambda: state.threads, set_num_threads=set_threads,
        from_numpy=lambda a: a,
    ))  # fmt: skip
    monkeypatch.setitem(sys.modules, "silero_vad", SimpleNamespace(
        load_silero_vad=load_model, get_speech_timestamps=speech,
    ))  # fmt: skip
    return state


def _wav(path: Path, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * rate)
    return path


def test_loading_silero_keeps_torch_thread_count(fake_libs: SimpleNamespace) -> None:
    SileroVad(RulesConfig())
    assert fake_libs.threads == 8


def test_voiced_returns_seconds_with_config(fake_libs: SimpleNamespace, tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    vad = SileroVad(RulesConfig(vad_threshold=0.4, vad_min_ms=150))
    assert vad.voiced(_wav(tmp_path / "audio.wav")) == [(0.5, 1.25)]
    assert fake_libs.calls[0]["threshold"] == 0.4
    assert fake_libs.calls[0]["min_speech_duration_ms"] == 150
    assert fake_libs.calls[0]["return_seconds"] is True


def test_voiced_rejects_wrong_format(fake_libs: SimpleNamespace, tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    with pytest.raises(ValueError, match="16 kHz mono"):
        SileroVad(RulesConfig()).voiced(_wav(tmp_path / "a.wav", rate=8000))
