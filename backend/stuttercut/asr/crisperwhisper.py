"""CrisperWhisper 2.0 transcriber: verbatim pass, optional intended pass, word timestamps.

Needs the ``asr`` extra (crisperwhisper, torch). The model loads once in __init__ and is reused.
``passes="dual"`` adds the intended transcript: on the ct2 backend (CPU/CUDA) both modes share
one decoder pass (``transcribe_dual``); on transformers (CPU/CUDA/MPS) it is a second full pass,
which roughly doubles transcribe time (lesson 002). Default is verbatim only.
"""

from pathlib import Path
from typing import Any

from stuttercut.asr import TranscriptPair, Word
from stuttercut.config import AsrConfig


def _words(result: Any) -> list[Word]:
    return [
        Word(text=w.word.strip(), start=float(w.start), end=float(w.end))
        for w in result.words or []
        if w.start is not None and w.end is not None and w.word.strip()
    ]


class CrisperWhisperTranscriber:
    def __init__(self, size: str, device: str, cfg: AsrConfig) -> None:
        from crisperwhisper import CrisperWhisperModel

        if cfg.threads > 0:
            import torch

            torch.set_num_threads(cfg.threads)
        self.model_id = size if "/" in size else f"nyralabs/CrisperWhisper2.0_{size}"
        self.device = device
        self._cfg = cfg
        self._model = CrisperWhisperModel(
            self.model_id,
            backend=cfg.backend,
            device=device,
            compute_type="float32" if device == "cpu" else "float16",
        )

    def _pass(self, audio_path: Path, mode: str) -> Any:
        return self._model.transcribe(
            str(audio_path), language=self._cfg.language, mode=mode, word_timestamps=True
        )

    def transcribe(self, audio_path: Path) -> TranscriptPair:
        if self._cfg.passes == "verbatim":
            return TranscriptPair(
                verbatim=_words(self._pass(audio_path, "verbatim")), intended=None
            )
        if self._cfg.backend == "ct2":
            verbatim, intended = self._model.transcribe_dual(
                str(audio_path),
                language=self._cfg.language,
                modes=("verbatim", "intended"),
                word_timestamps=True,
            )
        else:
            verbatim = self._pass(audio_path, "verbatim")
            intended = self._pass(audio_path, "intended")
        return TranscriptPair(verbatim=_words(verbatim), intended=_words(intended))
