"""Transcriber interface: one audio file -> verbatim words, plus intended words (ADR 0002).

The intended pass is optional (``STUTTERCUT_ASR_PASSES``): ``verbatim`` (default) leaves
``TranscriptPair.intended`` as None; ``dual`` fills it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PASSES = ("verbatim", "dual")


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds
    end: float  # seconds


@dataclass(frozen=True)
class TranscriptPair:
    verbatim: list[Word]
    intended: list[Word] | None  # None when the intended pass did not run


class Transcriber(Protocol):
    model_id: str
    device: str

    def transcribe(self, audio_path: Path) -> TranscriptPair: ...
