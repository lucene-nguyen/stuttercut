"""Fake transcriber for tests: returns a captured transcript from a JSON fixture.

Fixture format (tests/fixtures/*.json):
{"verbatim": [{"text": "ờ", "start": 0.5, "end": 0.7}, ...], "intended": [...]}
"""

import json
from pathlib import Path

from stuttercut.asr import TranscriptPair, Word


class FakeTranscriber:
    device = "cpu"

    def __init__(self, fixture: Path, error: Exception | None = None) -> None:
        self.model_id = f"fake:{fixture.name}"
        self._fixture = fixture
        self._error = error
        self.calls: list[Path] = []

    def transcribe_dual(self, audio_path: Path) -> TranscriptPair:
        self.calls.append(audio_path)
        if self._error is not None:
            raise self._error
        data = json.loads(self._fixture.read_text(encoding="utf-8"))  # "_note" etc. ignored
        return TranscriptPair(
            verbatim=[Word(**w) for w in data["verbatim"]],
            intended=[Word(**w) for w in data["intended"]],
        )
