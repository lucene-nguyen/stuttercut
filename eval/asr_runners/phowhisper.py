"""PhoWhisper (VinAI), Vietnamese fine-tune of Whisper, via the transformers pipeline.

Sizes: large (default), medium, small, base, tiny.

Word timing, WhisperX-style: PhoWhisper gives segment timestamps only
(``return_timestamps=True``, chunk 30 s, batch 1, fp16 on GPU), then each segment's words are
force-aligned with a Vietnamese wav2vec2 CTC model (``ALIGNER``). Word-level timestamps from
Whisper cross-attention (``return_timestamps="word"``) were tried first and needed ~20 GB RAM
and RTF 5.3 on an 8 GB GPU (see docs/spikes/2026-11-asr-models.md).
"""

import wave
from pathlib import Path
from typing import Any

import numpy as np

from eval.asr_runners import Word
from eval.asr_runners.ctc_align import align_words

ALIGNER = "nguyenvulebinh/wav2vec2-base-vietnamese-250h"
SR = 16000
PAD_S = 0.2  # Whisper segment edges are loose; give the aligner a little room


def read_wav(path: Path) -> np.ndarray:
    """16-bit mono WAV (as written by run_spike) -> float32 in [-1, 1]."""
    with wave.open(str(path)) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        return (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        )


class PhoWhisperRunner:
    word_timestamps = f"forced alignment ({ALIGNER}, CTC Viterbi) of PhoWhisper segments"

    def __init__(self, size: str, device: str) -> None:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor, pipeline

        self.model_id = size if "/" in size else f"vinai/PhoWhisper-{size}"
        self.device = device
        self._torch = torch
        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            dtype=torch.float32 if device == "cpu" else torch.float16,
            device=device,
            chunk_length_s=30,
            batch_size=1,
        )
        self._processor = Wav2Vec2Processor.from_pretrained(ALIGNER)
        self._aligner = Wav2Vec2ForCTC.from_pretrained(ALIGNER).to(device).eval()
        tok = self._processor.tokenizer
        self._vocab: dict[str, int] = tok.get_vocab()
        self._blank: int = tok.pad_token_id
        self._delimiter: str = tok.word_delimiter_token

    def _emission(self, audio: np.ndarray) -> np.ndarray:
        inputs = self._processor(audio, sampling_rate=SR, return_tensors="pt").input_values
        with self._torch.inference_mode():
            logits = self._aligner(inputs.to(self.device)).logits[0]
        return np.asarray(self._torch.log_softmax(logits.float(), dim=-1).cpu().numpy())

    def transcribe(self, audio_path: Path) -> list[Word]:
        audio = read_wav(audio_path)
        total_s = len(audio) / SR
        out = self._pipe(
            {"raw": audio, "sampling_rate": SR},
            return_timestamps=True,
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
        chunks: list[dict[str, Any]] = out["chunks"]
        words: list[Word] = []
        for i, chunk in enumerate(chunks):
            text_words = chunk["text"].split()
            if not text_words:
                continue
            start, end = chunk["timestamp"]
            if end is None:  # last segment of a clip that ends mid-word
                nxt = chunks[i + 1]["timestamp"][0] if i + 1 < len(chunks) else None
                end = nxt if nxt is not None else total_s
            s = max(0.0, start - PAD_S)
            e = min(total_s, max(end, start) + PAD_S)
            piece = audio[int(s * SR) : int(e * SR)]
            emission = self._emission(piece)
            frame_s = len(piece) / SR / max(1, emission.shape[0])
            aligned = align_words(
                text_words, emission, self._vocab, self._blank, self._delimiter, s, frame_s
            )
            if aligned is None:  # cannot align: spread evenly so the words still have times
                step = (end - start) / len(text_words)
                aligned = [
                    Word(
                        word=w,
                        start=round(start + k * step, 3),
                        end=round(start + (k + 1) * step, 3),
                    )
                    for k, w in enumerate(text_words)
                ]
            words.extend(aligned)
        return words


def load(size: str | None, device: str) -> PhoWhisperRunner:
    return PhoWhisperRunner(size or "large", device)
