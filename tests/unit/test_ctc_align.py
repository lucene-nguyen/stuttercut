import numpy as np

from eval.asr_runners.ctc_align import align_words, viterbi

VOCAB = {"<pad>": 0, "|": 1, "t": 2, "ô": 3, "i": 4, "ờ": 5}
BLANK = 0


def emission_for(frames: list[str]) -> np.ndarray:
    """Log-probs where each frame strongly prefers the given symbol."""
    em = np.full((len(frames), len(VOCAB)), np.log(0.01))
    for t, sym in enumerate(frames):
        em[t, VOCAB[sym]] = np.log(0.9)
    return em


def test_viterbi_finds_token_spans() -> None:
    em = emission_for(["<pad>", "t", "t", "<pad>", "ô", "<pad>"])
    assert viterbi(em, [2, 3], BLANK) == [(0, 1, 3), (1, 4, 5)]


def test_viterbi_fails_when_tokens_do_not_fit() -> None:
    assert viterbi(emission_for(["t"]), [2, 3], BLANK) == []


def test_align_words_gives_times_and_interpolates_unalignable() -> None:
    frames = ["<pad>", "ờ", "<pad>", "|", "t", "ô", "i", "<pad>", "<pad>"]
    words = align_words(
        ["Ờ,", "...", "tôi"],
        emission_for(frames),
        VOCAB,
        BLANK,
        "|",
        offset_s=10.0,
        frame_s=0.02,
    )
    assert words is not None
    assert [w["word"] for w in words] == ["Ờ,", "...", "tôi"]
    assert (words[0]["start"], words[0]["end"]) == (
        10.02,
        10.06,
    )  # ờ frames 1..2 (span ends before the next token)
    assert words[2]["start"] == 10.08  # t starts at frame 4
    assert words[1]["start"] == words[0]["end"] and words[1]["end"] == words[2]["start"]
    assert all(w["start"] <= w["end"] for w in words)
