import sys
from types import SimpleNamespace

import pytest

from stuttercut.platform import select_device


def _fake_torch(mps: bool, cuda: bool) -> SimpleNamespace:
    return SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        cuda=SimpleNamespace(is_available=lambda: cuda),
    )


@pytest.mark.parametrize(
    ("mps", "cuda", "expected"),
    [(True, True, "mps"), (False, True, "cuda"), (False, False, "cpu")],
)
def test_select_device_order(
    monkeypatch: pytest.MonkeyPatch, mps: bool, cuda: bool, expected: str
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(mps, cuda))
    assert select_device() == expected


def test_select_device_without_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise ImportError
    assert select_device() == "cpu"
