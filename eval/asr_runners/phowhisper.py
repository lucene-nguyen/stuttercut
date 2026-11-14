"""PhoWhisper (VinAI), Vietnamese fine-tune of Whisper, via the transformers pipeline.

Sizes: large (default), medium, small, base, tiny. Word timestamps come from cross-attention
DTW and need ``alignment_heads`` in the model's generation config; without them this runner
fails with a clear error, which is itself a spike finding.
"""

from pathlib import Path

from eval.asr_runners import Word


class PhoWhisperRunner:
    word_timestamps = "cross-attention DTW (transformers)"

    def __init__(self, size: str, device: str) -> None:
        import torch
        from transformers import pipeline

        self.model_id = size if "/" in size else f"vinai/PhoWhisper-{size}"
        self.device = device
        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            dtype=torch.float32 if device == "cpu" else torch.float16,
            device=device,
        )
        if not getattr(self._pipe.model.generation_config, "alignment_heads", None):
            raise RuntimeError(
                f"{self.model_id} has no alignment_heads: word timestamps are not supported"
            )

    def transcribe(self, audio_path: Path) -> list[Word]:
        out = self._pipe(
            str(audio_path),
            chunk_length_s=30,
            return_timestamps="word",
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
        words = []
        for chunk in out["chunks"]:
            start, end = chunk["timestamp"]
            text = chunk["text"].strip()
            if text and start is not None:
                words.append(Word(word=text, start=start, end=end if end is not None else start))
        return words


def load(size: str | None, device: str) -> PhoWhisperRunner:
    return PhoWhisperRunner(size or "large", device)
