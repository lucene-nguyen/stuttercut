"""Render planning, filter graph and encoder choice: pure code, no FFmpeg."""

import itertools
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stuttercut.config import RenderConfig
from stuttercut.media.render import filter_graph, free_name, plan, removed_s, select_encoder

CFG = RenderConfig()
PAD, MERGE, SILENT, MIN = 0.04, 0.05, 0.15, 0.08
F30 = Fraction(30)

cut_st = st.tuples(st.floats(0, 60), st.floats(0.001, 5)).map(lambda t: (t[0], t[0] + t[1]))
cuts_st = st.lists(cut_st, max_size=30)


@given(cuts_st, st.floats(1, 70))
def test_keeps_are_sorted_disjoint_long_enough_and_inside_the_clip(
    cuts: list[tuple[float, float]], duration: float
) -> None:
    keeps = plan(cuts, duration, CFG)
    for s, e in keeps:
        assert 0 <= s < e <= duration and e - s >= MIN - 1e-9
    for (_, e1), (s2, _) in itertools.pairwise(keeps):
        assert e1 <= s2
    assert removed_s(keeps, duration) == pytest.approx(duration - sum(e - s for s, e in keeps))


def test_filter_graph_fades_only_at_joins() -> None:
    g = filter_graph([(0.0, 1.0), (2.0, 3.5), (4.0, 5.0)], 10)
    assert g.count("afade=t=in") == 2 and g.count("afade=t=out") == 2
    assert "[0:v]trim=2.000000:3.500000,setpts=PTS-STARTPTS[v1]" in g
    assert "afade=t=out:st=1.490000:d=0.010" in g  # fade ends exactly at the join
    assert g.endswith("[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]")
    assert "afade" not in filter_graph([(0.0, 1.0)], 10)


LISTED = " V....D libx264  x\n V....D h264_nvenc  x\n V....D h264_videotoolbox  x\n"


@pytest.mark.parametrize(("preference", "works", "expected"), [
    ("auto", {"h264_nvenc", "libx264"}, "h264_nvenc"),
    ("auto", {"libx264"}, "libx264"),  # hardware listed but the test frame fails
    ("h264_videotoolbox", {"libx264"}, "libx264"),  # forced, unavailable: falls back
    ("h264_nvenc", {"h264_nvenc", "libx264"}, "h264_nvenc"),
    ("libx264", {"libx264"}, "libx264"),
])  # fmt: skip
def test_encoder_selection_and_fallback(preference: str, works: set[str], expected: str) -> None:
    assert select_encoder(preference, lambda: LISTED, lambda e: e in works) == expected


def test_encoder_not_listed_is_not_probed() -> None:
    probed: list[str] = []
    select_encoder("auto", lambda: " V....D libx264  x\n", lambda e: probed.append(e) or True)
    assert probed == ["libx264"]


def test_free_name_never_overwrites(tmp_path: Path) -> None:
    assert free_name(tmp_path, "bài nói", ".mp4").name == "bài nói_clean.mp4"
    (tmp_path / "bài nói_clean.mp4").touch()
    (tmp_path / "bài nói_clean_2.mp4").touch()
    assert free_name(tmp_path, "bài nói", ".mp4").name == "bài nói_clean_3.mp4"


def test_render_config_rejects_unknown_encoder() -> None:
    with pytest.raises(ValueError, match="STUTTERCUT_ENCODER"):
        RenderConfig(encoder="h265")


# --- planning: merge before padding, pad into silence, nearest frame (PR #13 review, part 2) ---


def r3(keeps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(round(a, 3), round(b, 3)) for a, b in keeps]


def test_touching_cuts_merge_before_padding() -> None:
    # padding per cut used to leave scraps (1.233, 1.367) and (1.533, 1.7)
    assert r3(plan([(1.0, 1.3), (1.3, 1.6), (1.65, 2.0)], 10, CFG, F30)) == [
        (0, 1.033),
        (1.967, 10),
    ]


def test_silent_gaps_merge_but_a_word_in_the_gap_is_kept() -> None:
    assert r3(plan([(1.0, 1.3), (1.42, 1.8)], 10, CFG, F30)) == [(0, 1.033), (1.767, 10)]
    keeps = plan([(1.0, 1.3), (1.42, 1.8)], 10, CFG, F30, words=[(1.31, 1.41)])
    assert len(keeps) == 3 and keeps[1][0] <= 1.31 and keeps[1][1] >= 1.41  # two cuts, word kept


@pytest.mark.parametrize("ms", [30, 70, 120, 200])
def test_short_cuts_are_still_cut_at_least_one_frame(ms: int) -> None:
    keeps = plan([(3.0, 3.0 + ms / 1000)], 10, CFG, F30)
    assert len(keeps) == 2
    assert keeps[1][0] - keeps[0][1] >= 1 / 30 - 1e-9


def test_padding_goes_into_silence_or_off_a_touching_word() -> None:
    from stuttercut.media.render import _group, _pad

    far = [(0.5, 0.80), (2.25, 2.6)]  # 200 / 250 ms of silence: room to pad outward
    near = [(0.5, 0.98), (2.02, 2.6)]  # 20 ms: protect the neighbours, pad inward
    for words, expected in ((far, (0.96, 2.04)), (near, (1.04, 1.96))):
        (group,) = _group([(1.0, 2.0)], 10, CFG, words)
        assert _pad(group, 10, CFG, words, True) == pytest.approx(expected)
    assert r3(plan([(1.0, 2.0)], 10, CFG, F30, far)) == [(0, 0.967), (2.033, 10)]  # nearest frames


def test_edited_and_pause_edges_get_no_padding() -> None:
    assert r3(plan([(1.0, 1.3, True, False), (1.3, 1.6, False, True)], 10, CFG, F30)) == [
        (0, 1.0), (1.6, 10),
    ]  # fmt: skip
    assert r3(plan([(2.0, 3.0, False, False, True)], 10, CFG, F30)) == [(0, 2.0), (3.0, 10)]
    assert r3(plan([(2.0, 3.0)], 10, CFG, F30)) == [(0, 2.033), (2.967, 10)]


def test_clip_start_is_not_padded_and_the_keep_starts_at_the_nearest_frame() -> None:
    (keep,) = plan([(0.0, 0.5)], 10, CFG, F30)
    assert keep == (pytest.approx(round(0.46 * 30) / 30), 10)  # 14/30 = 0.467


# Generated timelines: words (150 to 600 ms) and cuts (5 ms to 1 s) placed in order, never
# overlapping a word; gaps of 0 to 300 ms, so cuts touch and nearly touch.
item = st.tuples(st.sampled_from(["word", "cut"]), st.floats(0.0, 1.0), st.floats(0.0, 0.3))
fps_st = st.sampled_from([Fraction(25), F30, Fraction(30000, 1001)])


Spans = list[tuple[float, float]]


def timeline(items: list[tuple[str, float, float]]) -> tuple[Spans, Spans, float]:
    words, cuts, t = [], [], 0.3
    for kind, length, gap in items:
        start = t + gap
        end = start + (0.15 + 0.45 * length if kind == "word" else 0.005 + length)
        (words if kind == "word" else cuts).append((start, end))
        t = end
    return words, cuts, t + 0.5


def removed(keeps: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    out, t = [], 0.0
    for s, e in keeps:
        if s > t:
            out.append((t, s))
        t = e
    return out + ([(t, duration)] if t < duration else [])


@given(st.lists(item, max_size=25), fps_st)
def test_no_keep_inside_a_mergeable_gap(
    items: list[tuple[str, float, float]], fps: Fraction
) -> None:
    words, cuts, duration = timeline(items)
    keeps = plan(cuts, duration, CFG, fps, words)
    end = None
    for s, e in sorted(cuts):
        if end is not None and s > end:
            silent = s - end < SILENT and not any(w0 < s and w1 > end for w0, w1 in words)
            if s - end < MERGE or silent:
                # a keep entirely inside the gap = the scraps bug
                assert not any(ks >= end - 1e-9 and ke <= s + 1e-9 for ks, ke in keeps), (end, s)
        end = e if end is None else max(end, e)


@given(st.lists(item, max_size=25), fps_st)
def test_every_cut_removes_at_least_one_frame(
    items: list[tuple[str, float, float]], fps: Fraction
) -> None:
    words, cuts, duration = timeline(items)
    gone = removed(plan(cuts, duration, CFG, fps, words), duration)
    frame, near = float(1 / fps), PAD + 2 / float(fps)
    for s, e in cuts:
        assert any(b - a >= frame - 1e-9 and a < e + near and b > s - near for a, b in gone), (s, e)


@given(st.lists(item, max_size=25), fps_st)
def test_no_kept_word_loses_more_than_one_frame(
    items: list[tuple[str, float, float]], fps: Fraction
) -> None:
    words, cuts, duration = timeline(items)
    gone = removed(plan(cuts, duration, CFG, fps, words), duration)
    for w0, w1 in words:
        lost = sum(max(0.0, min(b, w1) - max(a, w0)) for a, b in gone)
        assert lost <= float(1 / fps) + 1e-9, (w0, w1, lost)
