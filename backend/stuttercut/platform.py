"""Device selection: mps -> cuda -> cpu."""


def select_device() -> str:
    """Best available torch device; "cpu" when torch is not installed."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
