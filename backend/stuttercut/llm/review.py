"""LLM review of cut candidates: judge each candidate in context, find retakes (LEARNING-208).

What is sent (ADR 0001): the verbatim words with their indices, and each candidate as a word
range (or "after word i" for silent ones) with its reason, source and rule confidence. No
timestamps, audio, file paths or clip names. Long transcripts go in overlapping chunks.

Combining (documented in docs/lessons and the PR):
    p_cut = c            if the LLM says "cut" with confidence c
          = 1 - c        if it says "keep"
    final = (1 - w) * rule_confidence + w * p_cut          (w = STUTTERCUT_LLM_WEIGHT, 0.6)
    tier  = "sure" if final >= STUTTERCUT_TIER_SURE_MIN (0.7) else "unsure"
A "keep" verdict lowers the confidence but never removes the candidate: the human decides.
Retakes the LLM finds become new cuts (source=llm) with the LLM's confidence, unless they
duplicate an existing candidate (> 50% overlap).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stuttercut.asr import Word
from stuttercut.config import LlmConfig
from stuttercut.llm import LLMClient, LLMError
from stuttercut.rules import Cut, tier

log = logging.getLogger(__name__)

_EPS = 0.01

SYSTEM_PROMPT = """\
You review automatic cut suggestions for a Vietnamese video editor that removes stutters.
You get a verbatim Vietnamese transcript (one word per line, "index<TAB>word"; [UH] and [UM]
mark hesitation sounds) and candidate cuts found by rules or a voice detector.

For EVERY candidate, decide in context whether removing it keeps the meaning and sounds
natural:
- "cut": a hesitation (ờ, ừm, [UH], [UM]), an earlier copy of a repeated word or phrase
  ("tôi tôi sẽ" -> cut the first "tôi"), a false start, or a long silence.
- "keep": the words carry meaning, e.g. "à" as a particle ("vậy à", "à, ra vậy"), "ừ" as a
  real answer, an intentional repetition for emphasis, or a short natural pause.
Give a confidence from 0 to 1 and a short reason (under 15 words, English).

Also list RETAKES the rules missed: an abandoned attempt that the speaker restarts right
after ("bài đầu tiên chúng ta ... [UH] bài đầu tiên là ..."). Return the word-index range of
the abandoned attempt only (not the restart), with a confidence and a short reason. Return an
empty list when there are none. Use only indices shown in this chunk.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["cut", "keep"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "verdict", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
        "retakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_word": {"type": "integer"},
                    "last_word": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["first_word", "last_word", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts", "retakes"],
    "additionalProperties": False,
}


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    verdict: Literal["cut", "keep"]
    confidence: float = Field(ge=0, le=1)
    reason: str


class Retake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_word: int
    last_word: int
    confidence: float = Field(ge=0, le=1)
    reason: str


class ReviewReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdicts: list[Verdict]
    retakes: list[Retake]


class InvalidReply(LLMError):
    """The model's reply did not match the schema twice in a row."""


@dataclass(frozen=True)
class Candidate:
    id: int
    reason: str
    source: str
    rule_confidence: float
    first: int | None  # word range when the cut covers words
    last: int | None
    after: int  # index of the word before a silent candidate (-1 = clip start)

    @property
    def span(self) -> tuple[int, int]:
        """Word indices the candidate needs as context (inclusive)."""
        if self.first is not None and self.last is not None:
            return self.first, self.last
        return max(self.after, 0), self.after + 1


@dataclass
class ReviewOutcome:
    updates: list[tuple[int, float, str, str, float, str]] = field(default_factory=list)
    # (cut_id, final confidence, tier, verdict, llm confidence, reason)
    new_cuts: list[tuple[Cut, str, str]] = field(default_factory=list)  # (cut, tier, reason)
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    ignored: int = 0  # verdicts for unknown ids, out-of-range retakes, duplicates

    def cost_usd(self, cfg: LlmConfig) -> float:
        if cfg.provider == "ollama":
            return 0.0  # local model
        return round(
            self.input_tokens / 1e6 * cfg.price_in_per_mtok
            + self.output_tokens / 1e6 * cfg.price_out_per_mtok,
            5,
        )


def combine(rule_confidence: float, verdict: str, llm_confidence: float, weight: float) -> float:
    """Final confidence in [0, 1] (formula in the module docstring)."""
    p_cut = llm_confidence if verdict == "cut" else 1 - llm_confidence
    return round(min(1.0, max(0.0, (1 - weight) * rule_confidence + weight * p_cut)), 3)


def chunk_ranges(n_words: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """[start, end) word ranges of at most ``size`` words; neighbours share ``overlap``."""
    if not 0 <= overlap < size:
        raise ValueError(f"need 0 <= overlap < size, got overlap={overlap}, size={size}")
    if n_words <= 0:
        return []
    ranges, start = [], 0
    while True:
        end = min(start + size, n_words)
        ranges.append((start, end))
        if end == n_words:
            return ranges
        start = end - overlap


def to_candidates(rows: list[Any], words: list[Word]) -> list[Candidate]:
    """CUT rows -> candidates addressed by word index (no times leave the machine)."""
    out = []
    for r in rows:
        inside = [
            i for i, w in enumerate(words)
            if w.start >= r["start_s"] - _EPS and w.end <= r["end_s"] + _EPS
        ]  # fmt: skip
        before = [i for i, w in enumerate(words) if w.end <= r["start_s"] + _EPS]
        rule_conf = r["rule_confidence"] if r["rule_confidence"] is not None else r["confidence"]
        out.append(Candidate(
            id=int(r["id"]), reason=r["reason"], source=r["source"],
            rule_confidence=float(rule_conf),
            first=inside[0] if inside else None, last=inside[-1] if inside else None,
            after=before[-1] if before else -1,
        ))  # fmt: skip
    return out


def assign(candidates: list[Candidate], ranges: list[tuple[int, int]]) -> list[list[Candidate]]:
    """Each candidate goes to the first chunk that holds all of its context words."""
    groups: list[list[Candidate]] = [[] for _ in ranges]
    for c in candidates:
        lo, hi = c.span
        idx = next(
            (k for k, (s, e) in enumerate(ranges) if s <= lo and hi < e),
            next((k for k, (s, e) in enumerate(ranges) if s <= lo < e), len(ranges) - 1),
        )
        groups[idx].append(c)
    return groups


def build_prompt(words: list[Word], rng: tuple[int, int], candidates: list[Candidate]) -> str:
    s, e = rng
    lines = [f"Transcript words {s}-{e - 1} (index<TAB>word):"]
    lines += [f"{i}\t{words[i].text}" for i in range(s, e)]
    lines += ["", "Candidates (one JSON object per line):"]
    for c in candidates:
        where: dict[str, Any] = (
            {"words": [c.first, c.last]} if c.first is not None else {"silence_after_word": c.after}
        )
        lines.append(json.dumps({"id": c.id, "reason": c.reason, "source": c.source,
                                 "rule_confidence": c.rule_confidence, **where},
                                ensure_ascii=False))  # fmt: skip
    if not candidates:
        lines.append("(none in this chunk; only look for retakes)")
    return "\n".join(lines)


def ask(client: LLMClient, system: str, prompt: str, outcome: ReviewOutcome) -> ReviewReply:
    """One chunk; retries once when the reply is not valid JSON for the schema."""
    error = ""
    for _attempt in range(2):
        reply = client.complete(system, prompt, SCHEMA)
        outcome.requests += 1
        outcome.input_tokens += reply.input_tokens
        outcome.output_tokens += reply.output_tokens
        try:
            return ReviewReply.model_validate_json(reply.text)
        except ValidationError as e:
            error = str(e).splitlines()[0]
            log.warning("LLM reply rejected, retrying once", extra={"error": error})
    raise InvalidReply(f"invalid LLM reply twice: {error}")


def review(
    words: list[Word],
    rows: list[Any],
    client: LLMClient,
    cfg: LlmConfig,
    sure_min: float,
) -> ReviewOutcome:
    """Judge every candidate row (CUT rows not kept) and look for retakes, chunk by chunk."""
    system = cfg.prompt_file.read_text(encoding="utf-8") if cfg.prompt_file else SYSTEM_PROMPT
    outcome = ReviewOutcome()
    candidates = to_candidates(rows, words)
    ranges = chunk_ranges(len(words), cfg.chunk_words, cfg.chunk_overlap_words)
    retakes: set[tuple[int, int]] = set()
    for rng, group in zip(ranges, assign(candidates, ranges), strict=True):
        reply = ask(client, system, build_prompt(words, rng, group), outcome)
        by_id = {c.id: c for c in group}
        for v in reply.verdicts:
            cand = by_id.pop(v.id, None)
            if cand is None:
                outcome.ignored += 1
                continue
            final = combine(cand.rule_confidence, v.verdict, v.confidence, cfg.weight)
            outcome.updates.append(
                (cand.id, final, tier(final, sure_min), v.verdict, v.confidence, v.reason[:200])
            )
        for r in reply.retakes:
            if not rng[0] <= r.first_word <= r.last_word < rng[1] or (
                (r.first_word, r.last_word) in retakes
            ):
                outcome.ignored += 1
                continue
            retakes.add((r.first_word, r.last_word))
            nxt = r.last_word + 1
            end = words[nxt].start if nxt < len(words) else words[r.last_word].end
            cut = Cut(words[r.first_word].start, end, "retake", "llm", round(r.confidence, 3))
            if _duplicates(cut, rows):
                outcome.ignored += 1
                continue
            outcome.new_cuts.append((cut, tier(cut.confidence, sure_min), r.reason[:200]))
    return outcome


def _duplicates(cut: Cut, rows: list[Any]) -> bool:
    length = cut.end - cut.start
    return any(min(cut.end, r["end_s"]) - max(cut.start, r["start_s"]) > length / 2 for r in rows)
