"""CrisperWhisper 2.0 transcriber: verbatim + intended passes with word timestamps.

Needs the ``asr`` extra (crisperwhisper, torch). The model loads once in __init__ and is reused.
``transcribe_dual`` (both modes in one decoder pass) exists only on the ct2 backend, which has
no MPS support; on the transformers backend (CPU/CUDA/MPS) the two modes run as two passes.
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
        self._language = cfg.language
        self._backend = cfg.backend
        self._model = CrisperWhisperModel(
            self.model_id,
            backend=cfg.backend,
            device=device,
            compute_type="float32" if device == "cpu" else "float16",
        )

    def transcribe_dual(self, audio_path: Path) -> TranscriptPair:
        if self._backend == "ct2":
            verbatim, intended = self._model.transcribe_dual(
                str(audio_path),
                language=self._language,
                modes=("verbatim", "intended"),
                word_timestamps=True,
            )
        else:
            verbatim, intended = (
                self._model.transcribe(
                    str(audio_path), language=self._language, mode=mode, word_timestamps=True
                )
                for mode in ("verbatim", "intended")
            )
        return TranscriptPair(verbatim=_words(verbatim), intended=_words(intended))
