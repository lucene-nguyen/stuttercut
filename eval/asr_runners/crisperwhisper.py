"""CrisperWhisper 2.0 (nyralabs), verbatim mode, transformers backend (CPU / CUDA / MPS).

Sizes: large (default), turbo, medium, small, or a full model id.
"""

from pathlib import Path

from eval.asr_runners import Word


class CrisperWhisperRunner:
    word_timestamps = "cross-attention (crisperwhisper)"

    def __init__(self, size: str, device: str) -> None:
        from crisperwhisper import CrisperWhisperModel

        self.model_id = size if "/" in size else f"nyralabs/CrisperWhisper2.0_{size}"
        self.device = device
        self._model = CrisperWhisperModel(
            self.model_id,
            backend="transformers",
            device=device,
            compute_type="float32" if device == "cpu" else "float16",
        )

    def transcribe(self, audio_path: Path) -> list[Word]:
        result = self._model.transcribe(
            str(audio_path), language="vi", mode="verbatim", word_timestamps=True
        )
        return [
            Word(word=w.word.strip(), start=w.start, end=w.end)
            for w in result.words or []
            if w.start is not None and w.end is not None and w.word.strip()
        ]


def load(size: str | None, device: str) -> CrisperWhisperRunner:
    return CrisperWhisperRunner(size or "large", device)
