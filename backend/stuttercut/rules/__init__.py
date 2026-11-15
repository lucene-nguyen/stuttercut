"""Cut detection rules (pure functions, no I/O). Entry point: ``rules.detect.detect``.

Words come from the verbatim transcript (+ optional intended words, ADR 0002); voiced segments
come from a VAD. Output: ``Cut`` candidates for human review; nothing is cut without approval.
"""

import unicodedata
from dataclasses import dataclass

REASONS = ("filler", "repeat", "pause", "retake")
SOURCES = ("rules", "vad", "diff", "llm")

Interval = tuple[float, float]  # (start, end) in seconds


@dataclass(frozen=True)
class Cut:
    start: float
    end: float
    reason: str  # one of REASONS
    source: str  # one of SOURCES
    confidence: float  # 0..1, how sure the rule is; low = check this one first in review


def tier(confidence: float, sure_min: float) -> str:
    """Review tier shown to the user: "sure" at or above ``sure_min``, else "unsure"."""
    return "sure" if confidence >= sure_min else "unsure"


def normalize(text: str) -> str:
    """NFC, lower case, letters and digits only: "[UH]" -> "uh", "Tôi," -> "tôi".

    Tone marks are kept (NFC only unifies how they are encoded): in Vietnamese "ma", "má" and
    "mà" are different words, so stripping them would invent repeats.
    """
    return "".join(ch for ch in unicodedata.normalize("NFC", text).lower() if ch.isalnum())
