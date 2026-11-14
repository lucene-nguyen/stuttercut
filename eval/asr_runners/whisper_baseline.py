"""Baseline: faster-whisper (CTranslate2) with word_timestamps=True.

Sizes: large-v3 (default), turbo, medium, small, ... (faster-whisper aliases) or a repo id.
CTranslate2 has no MPS backend, so on a Mac this runs on CPU.
"""

from pathlib import Path

from eval.asr_runners import Word


class FasterWhisperRunner:
    word_timestamps = "cross-attention DTW (faster-whisper)"

    def __init__(self, size: str, device: str) -> None:
        from faster_whisper import WhisperModel

        self.model_id = size
        self.device = "cuda" if device == "cuda" else "cpu"
        compute_type = "float16" if self.device == "cuda" else "int8"
        self._model = WhisperModel(size, device=self.device, compute_type=compute_type)

    def transcribe(self, audio_path: Path) -> list[Word]:
        segments, _info = self._model.transcribe(
            str(audio_path), language="vi", word_timestamps=True
        )
        return [
            Word(word=w.word.strip(), start=w.start, end=w.end)
            for seg in segments  # a generator: decoding happens here
            for w in seg.words or []
            if w.word.strip()
        ]


def load(size: str | None, device: str) -> FasterWhisperRunner:
    return FasterWhisperRunner(size or "large-v3", device)
