"""Merge overlapping cut candidates and keep cuts out of words that stay."""

from stuttercut.asr import Word
from stuttercut.rules import Cut

_EPS = 0.01  # 10 ms: timestamps are rounded, so "inside" allows this much slack


def merge_cuts(cuts: list[Cut], gap_s: float) -> list[Cut]:
    """Union of the cuts; touching or closer than ``gap_s`` become one cut.

    A merged cut takes reason, source and confidence from its longest part, so a retake that
    contains a filler stays a retake (ties: the more confident part).
    """
    merged: list[Cut] = []
    dominant: list[Cut] = []  # longest original part of each merged cut
    for cut in sorted(cuts, key=lambda c: (c.start, c.end)):
        if merged and cut.start - merged[-1].end < gap_s:
            if (cut.end - cut.start, cut.confidence) > (
                dominant[-1].end - dominant[-1].start,
                dominant[-1].confidence,
            ):
                dominant[-1] = cut
            best = dominant[-1]
            end = max(merged[-1].end, cut.end)
            merged[-1] = Cut(merged[-1].start, end, best.reason, best.source, best.confidence)
        else:
            merged.append(cut)
            dominant.append(cut)
    return merged


def protect_kept_words(cuts: list[Cut], words: list[Word], min_len_s: float) -> list[Cut]:
    """Trim every cut so it never ends or starts inside a word it does not fully contain.

    Words fully inside a cut are being cut; any other word it touches is kept, so the cut
    stops at that word's edge. Cuts shorter than ``min_len_s`` after trimming are dropped.
    """
    out = []
    for cut in cuts:
        start, end = cut.start, cut.end
        for w in words:
            inside = w.start >= start - _EPS and w.end <= end + _EPS
            if inside or w.end <= start or w.start >= end:
                continue
            if w.start < start:  # kept word sticks out on the left
                start = max(start, w.end)
            else:  # kept word sticks out on the right (or the cut sits inside it)
                end = min(end, w.start)
            if end - start < min_len_s:
                break
        if end - start >= min_len_s:
            out.append(Cut(start, end, cut.reason, cut.source, cut.confidence))
    return out
