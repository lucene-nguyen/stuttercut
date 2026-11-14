"""WhisperX-style word timing: CTC forced alignment of a known transcript to wav2vec2 emissions.

Pure numpy (no torchaudio); the model call lives in the runner. Characters the aligner's
vocabulary lacks (punctuation, symbols) are dropped for alignment; a word with no alignable
character gets its time interpolated from its neighbours.
"""

import unicodedata
from typing import Any

import numpy as np

from eval.asr_runners import Word


def viterbi(emission: np.ndarray, tokens: list[int], blank: int) -> list[tuple[int, int, int]]:
    """Best monotonic CTC path. emission: (frames, vocab) log-probs.

    Returns (token_index, first_frame, last_frame) for every token, or [] if it cannot fit.
    """
    n_frames, n_tokens = emission.shape[0], len(tokens)
    if n_tokens == 0 or n_frames < n_tokens:
        return []
    tok = np.asarray(tokens)
    trellis = np.full((n_frames + 1, n_tokens + 1), -np.inf)
    trellis[0, 0] = 0.0
    trellis[1:, 0] = np.cumsum(emission[:, blank])
    # Staying on token j costs a blank or a repeat of token j (CTC allows "t t" for one "t").
    stay_cost = np.maximum(emission[:, [blank]], emission[:, tok])
    for t in range(n_frames):
        stay = trellis[t, 1:] + stay_cost[t]
        step = trellis[t, :-1] + emission[t, tok]
        trellis[t + 1, 1:] = np.maximum(stay, step)

    # Backtrack: at each frame either emit the next token (step) or stay on the current one.
    first = np.zeros(n_tokens, dtype=int)
    last = np.zeros(n_tokens, dtype=int)
    j = n_tokens
    last[j - 1] = n_frames - 1
    for t in range(n_frames, 0, -1):
        if j == 0:
            break
        stayed = trellis[t - 1, j] + stay_cost[t - 1, j - 1]
        stepped = trellis[t - 1, j - 1] + emission[t - 1, tokens[j - 1]]
        if stepped >= stayed:
            first[j - 1] = t - 1
            j -= 1
            if j > 0:
                last[j - 1] = t - 2
    if j != 0:
        return []
    return [(i, int(first[i]), int(max(first[i], last[i]))) for i in range(n_tokens)]


def align_words(
    words: list[str],
    emission: np.ndarray,
    vocab: dict[str, int],
    blank: int,
    delimiter: str,
    offset_s: float,
    frame_s: float,
) -> list[Word] | None:
    """Times for each word of a segment; None when the transcript cannot be aligned."""
    tokens: list[int] = []
    owner: list[int] = []  # word index per token (-1 for delimiters)
    for wi, word in enumerate(words):
        chars = [c for c in unicodedata.normalize("NFC", word.lower()) if c in vocab]
        if tokens and chars:
            tokens.append(vocab[delimiter])
            owner.append(-1)
        for c in chars:
            tokens.append(vocab[c])
            owner.append(wi)
    path = viterbi(emission, tokens, blank)
    if not path:
        return None

    spans: dict[int, list[int]] = {}
    for ti, f0, f1 in path:
        if owner[ti] >= 0:
            span = spans.setdefault(owner[ti], [f0, f1])
            span[1] = f1
    times: list[Any] = [spans.get(i) for i in range(len(words))]
    out: list[Word] = []
    for i, word in enumerate(words):
        if times[i] is not None:
            start, end = offset_s + times[i][0] * frame_s, offset_s + (times[i][1] + 1) * frame_s
        else:  # nothing alignable (e.g. punctuation only): sit between the neighbours
            prev_end = out[-1]["end"] if out else offset_s
            nxt = next((t for t in times[i + 1 :] if t is not None), None)
            start = prev_end
            end = offset_s + nxt[0] * frame_s if nxt else prev_end
        out.append(Word(word=word, start=round(start, 3), end=round(max(start, end), 3)))
    return out
