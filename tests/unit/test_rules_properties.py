"""Property tests (hypothesis) for repeat detection and cut merging."""

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from stuttercut.asr import Word
from stuttercut.config import RulesConfig
from stuttercut.rules import Cut, normalize
from stuttercut.rules.detect import find_repeats
from stuttercut.rules.merge import merge_cuts, protect_kept_words

CFG = RulesConfig()
VOCAB = ["tôi", "sẽ", "nói", "về", "bài", "học", "mới", "hôm", "nay"]


def timed(tokens: list[str]) -> list[Word]:
    return [Word(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(tokens)]


@given(
    phrase=st.lists(st.sampled_from(VOCAB), min_size=1, max_size=3, unique=True),
    copies=st.integers(min_value=2, max_value=4),
    tail=st.lists(st.sampled_from(["xong", "rồi", "nhé"]), max_size=2, unique=True),
)
def test_repeated_phrase_cuts_all_but_last_copy(
    phrase: list[str], copies: int, tail: list[str]
) -> None:
    ws = timed(phrase * copies + tail)
    cuts = find_repeats(ws, CFG)
    last_copy = ws[len(phrase) * (copies - 1) : len(phrase) * copies]
    cut_words = [w for w in ws if any(c.start <= w.start and w.end <= c.end for c in cuts)]
    assert cut_words == ws[: len(phrase) * (copies - 1)]  # every earlier copy, nothing else
    assert not any(c.start < w.end and w.start < c.end for c in cuts for w in last_copy)


@given(st.lists(st.sampled_from(VOCAB), max_size=30))
def test_repeat_cuts_only_cover_words_followed_by_their_copy(tokens: list[str]) -> None:
    ws = timed(tokens)
    norm = [normalize(t) for t in tokens]
    for cut in find_repeats(ws, CFG):
        idx = [i for i, w in enumerate(ws) if cut.start <= w.start and w.end <= cut.end]
        n = len(idx)
        assert 1 <= n <= CFG.repeat_max_n
        i = idx[0]
        assert norm[i : i + n] == norm[i + n : i + 2 * n]


cut_strategy = st.builds(
    lambda s, d, r, c: Cut(s, s + d, r, "rules", c),
    st.floats(min_value=0, max_value=60, allow_nan=False),
    st.floats(min_value=0.01, max_value=3, allow_nan=False),
    st.sampled_from(["filler", "repeat", "pause", "retake"]),
    st.floats(min_value=0, max_value=1, allow_nan=False),
)


@settings(max_examples=200)
@given(st.lists(cut_strategy, max_size=25))
def test_merge_is_sorted_disjoint_and_keeps_the_union(cuts: list[Cut]) -> None:
    gap = 0.05
    merged = merge_cuts(cuts, gap)
    for a, b in pairwise(merged):
        assert b.start - a.end >= gap  # sorted, apart by at least the merge gap
    for c in cuts:  # every original cut lies inside one merged cut
        assert any(m.start <= c.start and c.end <= m.end for m in merged)
    assert merge_cuts(merged, gap) == merged  # idempotent


@settings(max_examples=200)
@given(st.lists(cut_strategy, max_size=15), st.lists(st.sampled_from(VOCAB), max_size=40))
def test_protected_cuts_never_split_a_kept_word(cuts: list[Cut], tokens: list[str]) -> None:
    ws = timed(tokens)
    for cut in protect_kept_words(merge_cuts(cuts, 0.05), ws, 0.03):
        assert cut.end - cut.start >= 0.03
        for w in ws:
            fully_inside = w.start >= cut.start - 0.01 and w.end <= cut.end + 0.01
            disjoint = w.end <= cut.start or w.start >= cut.end
            assert fully_inside or disjoint
