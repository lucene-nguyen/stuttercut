"""CrisperWhisper 2.0 transcriber: verbatim pass, optional intended pass, word timestamps.

Needs the ``asr`` extra (crisperwhisper, torch). The model loads once in __init__ and is reused.
``passes="dual"`` adds the intended transcript: on the ct2 backend (CPU/CUDA) both modes share
one decoder pass (``transcribe_dual``); on transformers (CPU/CUDA/MPS) it is a second full pass,
which roughly doubles transcribe time (lesson 002). Default is verbatim only.
"""

import gc
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
        self._model: Any = None
        self._cls = CrisperWhisperModel
        self.load()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is None:
            self._model = self._cls(
                self.model_id,
                backend=self._cfg.backend,
                device=self.device,
                compute_type="float32" if self.device == "cpu" else "float16",
            )

    def unload(self) -> None:
        """Drop the model and return its memory to the OS / GPU (before a local LLM runs)."""
        import torch

        self._model = None
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        elif self.device == "mps":
            torch.mps.empty_cache()

    def _pass(self, audio_path: Path, mode: str) -> Any:
        self.load()  # no-op unless unloaded
        return self._model.transcribe(
            str(audio_path), language=self._cfg.language, mode=mode, word_timestamps=True
        )

    def transcribe(self, audio_path: Path) -> TranscriptPair:
        if self._cfg.passes == "verbatim":
            return TranscriptPair(
                verbatim=_words(self._pass(audio_path, "verbatim")), intended=None
            )
        if self._cfg.backend == "ct2":
            self.load()
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
