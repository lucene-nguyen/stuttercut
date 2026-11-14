"""The cut rules. Each ``find_*`` returns candidates; ``detect`` runs them all and merges.

Sources: ``rules`` = word timings, ``vad`` = voiced audio no word covers, ``diff`` = words in
the verbatim transcript the intended one does not have (only when the intended pass ran).
Confidence guides review order; the human review is the safety net (ADR 0002).
"""

from difflib import SequenceMatcher
from itertools import pairwise

from stuttercut.asr import Word
from stuttercut.config import RulesConfig
from stuttercut.rules import Cut, Interval, normalize
from stuttercut.rules.merge import merge_cuts, protect_kept_words

# Non-lexical tokens CrisperWhisper 2.0 large wrote on Vietnamese clip c001 (746 words):
# "[UH]" x19 and "[UM]" x3; normalize() turns them into "uh" / "um". It wrote no "ờ"/"ừm".


def _norm_set(tokens: tuple[str, ...]) -> frozenset[str]:
    return frozenset(normalize(t) for t in tokens)


def is_filler(text: str, cfg: RulesConfig) -> bool:
    return normalize(text) in _norm_set(cfg.filler_tokens)


def find_fillers(words: list[Word], cfg: RulesConfig) -> list[Cut]:
    """Hesitation words and non-lexical tokens.

    Context rule for ambiguous ones ("à", "ừ" are also answer / question particles: "vậy à",
    "ừ, được"): cut only when isolated, i.e. silence of at least ``ambiguous_isolation_ms``
    on both sides (or a neighbouring filler). Attached to a word, they are kept.
    """
    fillers = _norm_set(cfg.filler_tokens)
    ambiguous = _norm_set(cfg.ambiguous_fillers)
    gap = cfg.ambiguous_isolation_ms / 1000
    cuts = []
    for i, w in enumerate(words):
        token = normalize(w.text)
        if token not in fillers:
            continue
        if token in ambiguous:
            prev, nxt = (
                (words[i - 1] if i else None),
                (words[i + 1] if i + 1 < len(words) else None),
            )
            left_free = prev is None or w.start - prev.end >= gap or normalize(prev.text) in fillers
            right_free = nxt is None or nxt.start - w.end >= gap or normalize(nxt.text) in fillers
            if not (left_free and right_free):
                continue
            cuts.append(Cut(w.start, w.end, "filler", "rules", 0.6))
        else:
            cuts.append(Cut(w.start, w.end, "filler", "rules", 0.9))
    return cuts


def find_repeats(words: list[Word], cfg: RulesConfig) -> list[Cut]:
    """Immediate repeats of 1..repeat_max_n word n-grams; the LAST copy stays.

    "tôi tôi tôi sẽ" -> the first two "tôi" are cut. Longer n-grams win ("đi học đi học").
    Fillers are ignored, and reduplications listed in ``repeat_keep`` ("từ từ") are words.
    """
    fillers = _norm_set(cfg.filler_tokens)
    keep = {tuple(normalize(t) for t in phrase.split()) for phrase in cfg.repeat_keep}
    norm = [normalize(w.text) for w in words]
    cuts = []
    i = 0
    while i < len(words):
        for n in range(cfg.repeat_max_n, 0, -1):
            gram = tuple(norm[i : i + n])
            if (
                len(gram) == n
                and all(gram)
                and not any(t in fillers for t in gram)
                and tuple(norm[i + n : i + 2 * n]) == gram
                and (n > 1 or gram * 2 not in keep)
            ):
                cuts.append(
                    Cut(
                        words[i].start,
                        words[i + n - 1].end,
                        "repeat",
                        "rules",
                        0.9 if n > 1 else 0.8,
                    )
                )
                i += n  # the next copy may itself repeat again; keep scanning from it
                break
        else:
            i += 1
    return cuts


def find_pauses(words: list[Word], voiced: list[Interval] | None, cfg: RulesConfig) -> list[Cut]:
    """Gaps between words longer than ``pause_min_ms``; ``pause_keep_ms`` stays on each side.

    With VAD, a gap that holds more than ``pause_voiced_max_ms`` of speech is not a pause
    (the VAD rule may flag that speech instead); without VAD, confidence is lower.
    """
    keep = cfg.pause_keep_ms / 1000
    cuts = []
    for prev, nxt in pairwise(words):
        if nxt.start - prev.end <= cfg.pause_min_ms / 1000:
            continue
        start, end = prev.end + keep, nxt.start - keep
        if voiced is None:
            cuts.append(Cut(start, end, "pause", "rules", 0.6))
        elif _overlap(start, end, voiced) <= cfg.pause_voiced_max_ms / 1000:
            cuts.append(Cut(start, end, "pause", "rules", 0.9))
    return cuts


def find_retakes(words: list[Word], cfg: RulesConfig) -> list[Cut]:
    """Simple retakes: a phrase restarts with the same first ``retake_min_words`` words
    within ``retake_window_s``, with other words in between and a hesitation right before the
    restart (a filler, or silence >= ``retake_min_hesitation_ms``): "bài đầu tiên là [UH] bài
    đầu tiên chúng ta". The abandoned attempt (first start -> restart) is cut. Low confidence:
    real retakes come from the LLM in LEARNING-208.

    Without the hesitation check, common two-word phrases recurring within a few seconds were
    flagged as retakes (19 on c001, 12 of them with no pause or filler before the "restart").
    """
    n = cfg.retake_min_words
    norm = [normalize(w.text) for w in words]
    fillers = _norm_set(cfg.filler_tokens)
    pause = cfg.retake_min_hesitation_ms / 1000

    def hesitates_before(j: int) -> bool:
        return norm[j - 1] in fillers or words[j].start - words[j - 1].end >= pause

    cuts = []
    i = 0
    while i + n <= len(words):
        opening = norm[i : i + n]
        restart = next(
            (
                j
                for j in range(i + n + 1, len(words) - n + 1)
                if words[j].start - words[i].start <= cfg.retake_window_s
                and norm[j : j + n] == opening
                and hesitates_before(j)
            ),
            None,
        )
        if restart is not None and all(opening):
            cuts.append(Cut(words[i].start, words[restart].start, "retake", "rules", 0.5))
            i = restart
        else:
            i += 1
    return cuts


def find_uncovered_voice(words: list[Word], voiced: list[Interval], cfg: RulesConfig) -> list[Cut]:
    """Speech the VAD hears but no word covers (±``vad_word_margin_ms``), lasting between
    ``vad_min_ms`` and ``vad_max_ms``: likely fillers or repeats the model did not write."""
    margin = cfg.vad_word_margin_ms / 1000
    covered = [(w.start - margin, w.end + margin) for w in words]
    cuts = []
    for seg in voiced:
        for start, end in _subtract(seg, covered):
            if cfg.vad_min_ms / 1000 <= end - start <= cfg.vad_max_ms / 1000:
                cuts.append(Cut(start, end, "filler", "vad", 0.4))
    return cuts


def find_diff(verbatim: list[Word], intended: list[Word], cfg: RulesConfig) -> list[Cut]:
    """Runs of verbatim words the intended transcript does not have, typed by the rules:
    all fillers -> filler; same as the words right after (or a prefix of the next word) ->
    repeat; two or more other words -> retake; a single other word -> filler (low)."""
    fillers = _norm_set(cfg.filler_tokens)
    clear_fillers = fillers - _norm_set(cfg.ambiguous_fillers)
    v = [normalize(w.text) for w in verbatim]
    matcher = SequenceMatcher(a=v, b=[normalize(w.text) for w in intended], autojunk=False)
    cuts = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag not in ("delete", "replace"):
            continue
        # Split the run at clear fillers ("[UH] tôi" = a filler + a repeat, not a retake).
        groups: list[tuple[int, int]] = []
        for k in range(i1, i2):
            if v[k] in clear_fillers:
                groups.append((k, k + 1))
            elif groups and groups[-1][1] == k and v[k - 1] not in clear_fillers:
                groups[-1] = (groups[-1][0], k + 1)
            else:
                groups.append((k, k + 1))
        for g1, g2 in groups:
            run, after = v[g1:g2], v[g2 : g2 + (g2 - g1)]
            if all(t in fillers for t in run):
                reason, conf = "filler", 0.8
            elif run == after or (len(run) == 1 and g2 < len(v) and v[g2].startswith(run[0])):
                reason, conf = "repeat", 0.8
            elif len(run) >= 2:
                reason, conf = "retake", 0.6
            else:
                reason, conf = "filler", 0.4
            cuts.append(Cut(verbatim[g1].start, verbatim[g2 - 1].end, reason, "diff", conf))
    return cuts


def detect(
    verbatim: list[Word],
    cfg: RulesConfig,
    intended: list[Word] | None = None,
    voiced: list[Interval] | None = None,
) -> list[Cut]:
    """All rules, merged (gap < ``merge_gap_ms``) and kept out of words that stay."""
    words = sorted(verbatim, key=lambda w: w.start)
    candidates = [
        *find_fillers(words, cfg),
        *find_repeats(words, cfg),
        *find_pauses(words, voiced, cfg),
        *find_retakes(words, cfg),
    ]
    if voiced:
        candidates += find_uncovered_voice(words, voiced, cfg)
    if intended:
        candidates += find_diff(words, sorted(intended, key=lambda w: w.start), cfg)
    merged = merge_cuts(candidates, cfg.merge_gap_ms / 1000)
    return protect_kept_words(merged, words, cfg.min_cut_ms / 1000)


def _overlap(start: float, end: float, segments: list[Interval]) -> float:
    return sum(max(0.0, min(end, b) - max(start, a)) for a, b in segments)


def _subtract(segment: Interval, holes: list[Interval]) -> list[Interval]:
    """Parts of ``segment`` not inside any of ``holes``."""
    pieces = [segment]
    for a, b in holes:
        nxt = []
        for s, e in pieces:
            if b <= s or a >= e:
                nxt.append((s, e))
                continue
            if a > s:
                nxt.append((s, a))
            if b < e:
                nxt.append((b, e))
        pieces = nxt
    return pieces
