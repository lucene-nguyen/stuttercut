"""Fake transcriber for tests: returns a captured transcript from a JSON fixture.

Fixture format (tests/fixtures/*.json; other keys such as "_note" are ignored):
{"verbatim": [{"text": "ờ", "start": 0.5, "end": 0.7}, ...], "intended": [...]}
``passes="verbatim"`` (the app default) returns intended=None, like the real transcriber.

Fault injection for the watchdog tests (it reaches a spawned worker through the fixture file):
"_allocate_mb": N holds N MB while transcribing; "_sleep_s": S makes transcribe take S seconds.
"""

import json
import time
from pathlib import Path

from stuttercut.asr import PASSES, TranscriptPair, Word


class FakeTranscriber:
    device = "cpu"

    def __init__(
        self, fixture: Path, passes: str = "verbatim", error: Exception | None = None
    ) -> None:
        if passes not in PASSES:
            raise ValueError(f"passes must be one of {PASSES}, got {passes!r}")
        self.model_id = f"fake:{fixture.name}"
        self._fixture = fixture
        self._passes = passes
        self._error = error
        self.calls: list[Path] = []
        self.loaded = True
        self.loads = 0  # reloads after unload()

    def load(self) -> None:
        if not self.loaded:
            self.loaded, self.loads = True, self.loads + 1

    def unload(self) -> None:
        self.loaded = False

    def transcribe(self, audio_path: Path) -> TranscriptPair:
        assert self.loaded, "transcribe() after unload() without load()"
        self.calls.append(audio_path)
        if self._error is not None:
            raise self._error
        data = json.loads(self._fixture.read_text(encoding="utf-8"))
        hog = bytearray(int(data.get("_allocate_mb", 0)) * 2**20)  # touched: really resident
        for i in range(0, len(hog), 4096):
            hog[i] = 1
        time.sleep(float(data.get("_sleep_s", 0)))
        del hog
        intended = [Word(**w) for w in data["intended"]] if self._passes == "dual" else None
        return TranscriptPair(verbatim=[Word(**w) for w in data["verbatim"]], intended=intended)
