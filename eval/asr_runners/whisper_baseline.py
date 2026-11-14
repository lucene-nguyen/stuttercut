"""Baseline: faster-whisper (CTranslate2) with word_timestamps=True.

Sizes: large-v3 (default), turbo, medium, small, ... (faster-whisper aliases) or a repo id.
CTranslate2 has no MPS backend, so on a Mac this runs on CPU.
On Windows + CUDA, CTranslate2 needs CUDA 12 cuBLAS and cuDNN 9 even when torch uses CUDA 13:
install nvidia-cublas-cu12 and nvidia-cudnn-cu12 (see docs/guides/setup-windows.md); their
DLL folders are added to the search path here.
"""

import os
import sys
from pathlib import Path

from eval.asr_runners import Word


def _add_pip_cuda_dlls() -> None:
    """Make pip-installed nvidia-cublas-cu12 / nvidia-cudnn-cu12 DLLs findable on Windows."""
    if sys.platform != "win32":
        return
    import importlib.util

    for module in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            continue
        for pkg_dir in (spec.submodule_search_locations or []) if spec else []:
            bin_dir = Path(pkg_dir) / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                # CTranslate2 loads these lazily with a plain LoadLibrary, which searches PATH.
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


class FasterWhisperRunner:
    word_timestamps = "cross-attention DTW (faster-whisper)"

    def __init__(self, size: str, device: str) -> None:
        from faster_whisper import WhisperModel

        self.model_id = size
        self.device = "cuda" if device == "cuda" else "cpu"
        if self.device == "cuda":
            _add_pip_cuda_dlls()
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
