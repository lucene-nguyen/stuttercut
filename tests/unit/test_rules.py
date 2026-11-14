"""One test group per rule. Times in seconds; words are synthetic, not real transcripts."""

import pytest

from stuttercut.asr import Word
from stuttercut.config import RulesConfig
from stuttercut.rules import Cut, normalize
from stuttercut.rules.detect import (
    detect,
    find_diff,
    find_fillers,
    find_pauses,
    find_repeats,
    find_retakes,
    find_uncovered_voice,
    is_filler,
)
from stuttercut.rules.merge import merge_cuts, protect_kept_words

CFG = RulesConfig()


def words(*spec: str, start: float = 0.0, dur: float = 0.2, gap: float = 0.05) -> list[Word]:
    """words("tôi", "sẽ") -> back-to-back words; "|0.8" inserts a 0.8 s silence."""
    out, t = [], start
    for item in spec:
        if item.startswith("|"):
            t += float(item[1:])
            continue
        out.append(Word(item, round(t, 3), round(t + dur, 3)))
        t += dur + gap
    return out


def spans(cuts: list[Cut]) -> list[tuple[float, float, str]]:
    return [(round(c.start, 3), round(c.end, 3), c.reason) for c in cuts]


# --- normalize / fillers -------------------------------------------------------------------


def test_normalize_keeps_tones_and_folds_case_brackets_unicode() -> None:
    decomposed = "Tối"  # "Tối" typed with combining marks
    assert normalize("[UH]") == "uh"
    assert normalize("Tôi,") == "tôi"
    assert normalize(decomposed) == "tối" != normalize("tôi")


def test_crisperwhisper_nonlexical_tokens_are_fillers() -> None:
    assert is_filler("[UH]", CFG) and is_filler("[UM]", CFG) and is_filler("Ờ,", CFG)
    assert not is_filler("tôi", CFG)


def test_clear_fillers_are_cut_with_high_confidence() -> None:
    ws = words("[UH]", "tôi", "ờ", "đi")
    cuts = find_fillers(ws, CFG)
    assert [(c.start, c.reason, c.source, c.confidence) for c in cuts] == [
        (0.0, "filler", "rules", 0.9),
        (0.5, "filler", "rules", 0.9),
    ]


def test_meaningful_a_attached_to_words_is_kept() -> None:
    # "vậy à" (question particle) and "à, ra vậy" (realisation): no silence around "à".
    assert find_fillers(words("vậy", "à"), CFG) == []
    assert find_fillers(words("à", "ra", "vậy", start=1.0), CFG) == []


def test_isolated_a_is_cut_with_lower_confidence() -> None:
    ws = words("tôi", "|0.3", "à", "|0.3", "nghĩ")
    (cut,) = find_fillers(ws, CFG)
    assert (cut.reason, cut.confidence) == ("filler", 0.6)


def test_ambiguous_next_to_another_filler_counts_as_isolated() -> None:
    ws = words("tôi", "|0.3", "ừ", "ờ", "|0.3", "nói")
    assert [c.confidence for c in find_fillers(ws, CFG)] == [0.6, 0.9]


def test_filler_list_is_configurable() -> None:
    cfg = RulesConfig(filler_tokens=("kiểu",), ambiguous_fillers=())
    assert len(find_fillers(words("kiểu", "ờ"), cfg)) == 1


# --- repeats -------------------------------------------------------------------------------


def test_single_word_repeat_keeps_last_copy() -> None:
    ws = words("tôi", "tôi", "tôi", "sẽ")
    assert spans(find_repeats(ws, CFG)) == [(0.0, 0.2, "repeat"), (0.25, 0.45, "repeat")]


def test_longest_ngram_wins_and_case_punctuation_ignored() -> None:
    ws = words("đi", "học", "Đi", "học,", "về")
    (cut,) = find_repeats(ws, CFG)
    assert (cut.start, cut.end, cut.confidence) == (0.0, 0.45, 0.9)


def test_reduplicated_words_and_fillers_are_not_repeats() -> None:
    assert find_repeats(words("từ", "từ", "thôi"), CFG) == []
    assert find_repeats(words("ờ", "ờ", "thôi"), CFG) == []
    assert find_repeats(words("ma", "má", "mà"), CFG) == []  # tones differ: different words


# --- pauses --------------------------------------------------------------------------------


def test_pause_keeps_breathing_room_and_needs_min_gap() -> None:
    ws = words("tôi", "|1.0", "sẽ", "|0.5", "nói")
    (cut,) = find_pauses(ws, None, CFG)
    assert (round(cut.start, 3), round(cut.end, 3), cut.confidence) == (0.35, 1.1, 0.6)


def test_pause_confirmed_or_rejected_by_vad() -> None:
    ws = words("tôi", "|1.0", "sẽ")
    assert find_pauses(ws, [(0.0, 0.2), (1.3, 1.5)], CFG)[0].confidence == 0.9  # silent gap
    assert find_pauses(ws, [(0.5, 0.9)], CFG) == []  # 400 ms of speech in the gap


# --- retakes -------------------------------------------------------------------------------


def test_retake_cuts_abandoned_attempt_up_to_restart() -> None:
    ws = words("bài", "đầu", "tiên", "chúng", "|0.4", "bài", "đầu", "tiên", "là")
    (cut,) = find_retakes(ws, CFG)
    assert (cut.reason, cut.start, cut.end, cut.confidence) == ("retake", 0.0, ws[4].start, 0.5)


def test_no_retake_outside_window_or_for_plain_repeat() -> None:
    far = words("bài", "đầu", "nói", "|5.0", "bài", "đầu")
    assert find_retakes(far, CFG) == []
    assert find_retakes(words("bài", "đầu", "bài", "đầu"), CFG) == []  # that is a repeat


# --- VAD -----------------------------------------------------------------------------------


def test_uncovered_voice_between_words_becomes_low_confidence_filler() -> None:
    ws = [Word("tôi", 0.0, 0.3), Word("đi", 1.0, 1.3)]
    cuts = find_uncovered_voice(ws, [(0.0, 1.3)], CFG)
    assert [(round(c.start, 2), round(c.end, 2), c.source, c.confidence) for c in cuts] == [
        (0.38, 0.92, "vad", 0.4)
    ]


def test_uncovered_voice_too_short_or_too_long_is_ignored() -> None:
    ws = [Word("tôi", 0.0, 0.3), Word("đi", 0.5, 0.8), Word("về", 3.0, 3.2)]
    assert find_uncovered_voice(ws, [(0.0, 0.8)], CFG) == []  # 40 ms hole only
    assert find_uncovered_voice(ws, [(0.8, 3.0)], CFG) == []  # 2 s: too long for a filler


# --- diff ----------------------------------------------------------------------------------


def test_diff_types_extra_verbatim_words() -> None:
    v = words(
        "[UH]", "tôi", "tôi", "sẽ", "cài", "cài", "đặt", "bài", "một", "à", "không", "bài", "hai"
    )
    i = words("tôi", "sẽ", "cài", "đặt", "bài", "hai")
    got = {(c.reason, round(c.start, 2)) for c in find_diff(v, i, CFG)}
    assert ("filler", 0.0) in got  # [UH]
    assert ("repeat", 0.25) in got or ("repeat", 0.5) in got  # tôi tôi
    assert any(r == "retake" for r, _ in got)  # "bài một à không" abandoned


def test_diff_single_unknown_word_is_low_confidence_filler() -> None:
    v, i = words("tôi", "kiểu", "đi"), words("tôi", "đi")
    (cut,) = find_diff(v, i, CFG)
    assert (cut.reason, cut.confidence) == ("filler", 0.4)


# --- merge and detect ----------------------------------------------------------------------


def test_merge_takes_reason_of_longest_part() -> None:
    cuts = [Cut(0.0, 2.0, "retake", "rules", 0.5), Cut(0.5, 0.7, "filler", "rules", 0.9),
            Cut(2.03, 2.2, "filler", "vad", 0.4), Cut(3.0, 3.2, "pause", "rules", 0.9)]  # fmt: skip
    assert spans(merge_cuts(cuts, 0.05)) == [(0.0, 2.2, "retake"), (3.0, 3.2, "pause")]


def test_protect_trims_cuts_out_of_kept_words() -> None:
    ws = [Word("tôi", 0.0, 0.3), Word("đi", 0.4, 0.7)]
    cut = Cut(0.2, 0.5, "filler", "vad", 0.4)
    assert spans(protect_kept_words([cut], ws, 0.03)) == [(0.3, 0.4, "filler")]
    inside_word = Cut(0.05, 0.25, "filler", "vad", 0.4)
    assert protect_kept_words([inside_word], ws, 0.03) == []


def test_detect_end_to_end_without_and_with_extra_sources() -> None:
    ws = words("ờ", "tôi", "tôi", "sẽ", "|1.0", "nói")
    plain = detect(ws, CFG)
    assert [c.reason for c in plain] == ["filler", "pause"]  # ờ + tôi merge (gap < 50 ms)
    assert detect([], CFG) == []
    with_intended = detect(ws, CFG, intended=words("tôi", "sẽ", "nói"), voiced=[(0.0, 2.0)])
    assert all(c.end > c.start for c in with_intended)


@pytest.mark.parametrize("reason", ["filler", "repeat", "pause", "retake"])
def test_cut_reasons_are_known(reason: str) -> None:
    from stuttercut.rules import REASONS

    assert reason in REASONS


def test_retake_needs_hesitation_before_restart() -> None:
    fluent = words("bài", "đầu", "tiên", "chúng", "bài", "đầu", "tiên", "là")  # no pause
    assert find_retakes(fluent, CFG) == []
    with_filler = words("bài", "đầu", "tiên", "chúng", "[UH]", "bài", "đầu", "tiên", "là")
    assert len(find_retakes(with_filler, CFG)) == 1
