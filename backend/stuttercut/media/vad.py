"""Voice activity detection with silero-vad (MIT; model bundled in the package, no network).

Needs the ``asr`` extra (silero-vad, torch). Reads the 16 kHz mono WAV written by extract_audio
with the standard library, so torchaudio is not needed.
"""

import wave
from pathlib import Path
from typing import Protocol

from stuttercut.config import RulesConfig
from stuttercut.rules import Interval


class VoiceDetector(Protocol):
    def voiced(self, wav: Path) -> list[Interval]: ...


class SileroVad:
    def __init__(self, cfg: RulesConfig) -> None:
        import torch

        # Importing silero_vad runs torch.set_num_threads(1) for the whole process, which would
        # leave CrisperWhisper's CPU-side work single-threaded in the same worker (lesson 003).
        threads = torch.get_num_threads()
        from silero_vad import load_silero_vad

        self._model = load_silero_vad()
        torch.set_num_threads(threads)
        self._cfg = cfg

    def voiced(self, wav: Path) -> list[Interval]:
        import numpy as np
        import torch
        from silero_vad import get_speech_timestamps

        with wave.open(str(wav)) as w:
            rate = w.getframerate()
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or rate != 16000:
                raise ValueError(f"{wav.name}: expected 16 kHz mono 16-bit WAV")
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio = torch.from_numpy(pcm.astype(np.float32) / 32768)
        stamps = get_speech_timestamps(
            audio,
            self._model,
            threshold=self._cfg.vad_threshold,
            sampling_rate=rate,
            min_speech_duration_ms=min(self._cfg.vad_min_ms, 250),
            return_seconds=True,
        )
        return [(float(s["start"]), float(s["end"])) for s in stamps]
