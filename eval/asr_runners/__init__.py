"""ASR adapters for the LEARNING-205 spike. Each module exposes ``load(size, device) -> Runner``.

Heavy libraries are imported inside ``load`` so tests and scoring never need them.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict


class Word(TypedDict):
    word: str
    start: float
    end: float


class Runner(Protocol):
    model_id: str
    device: str
    word_timestamps: str  # how word times are produced, recorded in the report

    def transcribe(self, audio_path: Path) -> list[Word]: ...


def get_loader(name: str) -> Callable[[str | None, str], Runner]:
    from eval.asr_runners import crisperwhisper, phowhisper, whisper_baseline

    loaders: dict[str, Callable[[str | None, str], Runner]] = {
        "crisperwhisper": crisperwhisper.load,
        "whisper_baseline": whisper_baseline.load,
        "phowhisper": phowhisper.load,
    }
    return loaders[name]


RUNNER_NAMES = ("crisperwhisper", "whisper_baseline", "phowhisper")
