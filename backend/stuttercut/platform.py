"""Device selection (mps -> cuda -> cpu) and the free-RAM pre-flight for the ASR model."""

import logging

from stuttercut.config import AsrConfig

log = logging.getLogger(__name__)


class InsufficientMemoryError(RuntimeError):
    """Free RAM is below the minimum for any ASR model size."""


def select_device(requested: str = "auto") -> str:
    """Best available torch device; "cpu" when torch is not installed.

    A machine has either MPS or CUDA, so the mps/cuda order only matters for readability.
    """
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def free_ram_gb() -> float:
    import psutil

    return float(psutil.virtual_memory().available) / 2**30


def free_vram_gb() -> float | None:
    """Free memory on the current CUDA device, all processes counted; None without CUDA."""
    import sys

    torch = sys.modules.get("torch")  # only meaningful once the ASR model put torch on CUDA
    if torch is None or not torch.cuda.is_available():
        return None
    free, _total = torch.cuda.mem_get_info()
    return float(free) / 2**30


def preflight_model_size(cfg: AsrConfig, free_gb: float | None = None) -> str:
    """Model size to load given free RAM: configured size, the fallback, or an error."""
    free = free_ram_gb() if free_gb is None else free_gb
    if free < cfg.min_free_gb_any:
        raise InsufficientMemoryError(
            f"only {free:.1f} GB RAM free; need at least {cfg.min_free_gb_any:.1f} GB "
            "(STUTTERCUT_ASR_MIN_FREE_GB_ANY). Close other apps and retry."
        )
    if free < cfg.min_free_gb_large and cfg.model_size != cfg.fallback_size:
        log.warning(
            "low free RAM: using fallback ASR size",
            extra={
                "free_gb": round(free, 1),
                "wanted": cfg.model_size,
                "using": cfg.fallback_size,
                "min_free_gb_large": cfg.min_free_gb_large,
            },
        )
        return cfg.fallback_size
    return cfg.model_size
