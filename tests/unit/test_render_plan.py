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
PAD, MERGE, MIN = 0.04, 0.05, 0.08

cut_st = st.tuples(st.floats(0, 60), st.floats(0.001, 5)).map(lambda t: (t[0], t[0] + t[1]))
cuts_st = st.lists(cut_st, max_size=30)


def shrunk(cuts: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    out = []
    for s, e in cuts:
        s, e = max(s, 0), min(e, duration)
        s2, e2 = (s if s <= 0 else s + PAD), (e if e >= duration else e - PAD)
        if e2 > s2:
            out.append((s2, e2))
    return out


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


@given(cuts_st, st.floats(1, 70))
def test_padded_cuts_are_removed_and_far_points_are_kept(
    cuts: list[tuple[float, float]], duration: float
) -> None:
    keeps = plan(cuts, duration, CFG)
    pads = shrunk(cuts, duration)
    for cs, ce in pads:  # nothing inside a (shrunk) cut survives
        assert all(min(e, ce) - max(s, cs) <= 1e-9 for s, e in keeps)
    margin = MIN + MERGE
    for k in range(200):  # a point well away from every cut is kept
        t = duration * k / 200
        if (
            all(t < cs - margin or t > ce + margin for cs, ce in pads)
            and margin < t < duration - margin
        ):
            assert any(s <= t <= e for s, e in keeps), t


@given(cut_st, st.floats(1, 70))
def test_padding_shrinks_a_cut_on_both_sides(cut: tuple[float, float], duration: float) -> None:
    s, e = cut
    if not (s > 0 and e < duration and e - s > 2 * PAD + MIN):
        return
    keeps = plan([cut], duration, CFG)
    assert any(ks <= s + PAD - 1e-9 and ke == pytest.approx(s + PAD) for ks, ke in keeps) or (
        s + PAD < MIN  # the leading keep-segment was too short and dropped
    )
    assert any(ks == pytest.approx(e - PAD) for ks, _ in keeps) or duration - (e - PAD) < MIN


def test_merging_and_minimum_segment() -> None:
    assert plan([], 10.0, CFG) == [(0.0, 10.0)]
    # shrunk to (1.04, 1.96) and (1.99, 2.96): 30 ms apart (< 50 ms), so one cut
    assert plan([(1.0, 2.0), (1.95, 3.0)], 10.0, CFG) == [(0.0, 1.04), (2.96, 10.0)]
    # 190 ms apart after padding: a keep-segment survives
    assert plan([(1.0, 2.0), (2.11, 3.0)], 10.0, CFG) == [(0.0, 1.04), (1.96, 2.15), (2.96, 10.0)]
    # 60 ms apart: not merged (>= 50 ms) but shorter than 80 ms, so dropped
    assert plan([(1.0, 2.0), (1.98, 3.0)], 10.0, CFG) == [(0.0, 1.04), (2.96, 10.0)]
    # cuts at the clip edges are not padded there
    assert plan([(0.0, 1.0), (9.0, 10.0)], 10.0, CFG) == [(0.96, 9.04)]
    assert plan([(0.0, 10.0)], 10.0, CFG) == []


@given(
    cuts_st, st.floats(1, 70), st.sampled_from([Fraction(25), Fraction(30000, 1001), Fraction(10)])
)
def test_boundaries_snap_to_the_frame_grid(
    cuts: list[tuple[float, float]], duration: float, fps: Fraction
) -> None:
    keeps = plan(cuts, duration, CFG, fps)
    for s, e in keeps:
        for t in (s, e):
            assert t == duration or abs(t * fps - round(t * fps)) < 1e-6
    for (_, e1), (s2, _) in itertools.pairwise(keeps):
        assert e1 < s2
    unsnapped = plan(cuts, duration, CFG)  # snapping only ever keeps more
    for s, e in unsnapped:
        if e - s >= MIN + 2 / float(fps):
            assert any(ks <= s + 1e-9 and e <= ke + 1e-9 for ks, ke in keeps)


def test_snapping_keeps_the_padding() -> None:
    # 30 fps: the keep-segment ends at 1.04 s (padding) -> frame 32 (1.067 s), never 1.033 s
    assert plan([(1.0, 2.0)], 10.0, CFG, Fraction(30))[0] == (0.0, pytest.approx(32 / 30))


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


def test_edited_edges_get_no_padding() -> None:
    both = plan([(1.0, 2.0, True, True)], 10.0, CFG)
    assert both == [(0.0, 1.0), (2.0, 10.0)]
    start_only = plan([(1.0, 2.0, True, False)], 10.0, CFG)
    assert start_only == [(0.0, 1.0), (pytest.approx(1.96), 10.0)]
    assert plan([(1.0, 2.0, False, False)], 10.0, CFG) == plan([(1.0, 2.0)], 10.0, CFG)
