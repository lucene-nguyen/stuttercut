"""Transcriber interface: one audio file -> verbatim and intended word lists (ADR 0002)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds
    end: float  # seconds


@dataclass(frozen=True)
class TranscriptPair:
    verbatim: list[Word]
    intended: list[Word]


class Transcriber(Protocol):
    model_id: str
    device: str

    def transcribe_dual(self, audio_path: Path) -> TranscriptPair: ...
