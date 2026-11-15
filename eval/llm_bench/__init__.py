"""LLM review bench on hand-written sentences (no real voices, no clips).

Usage: python -m eval.llm_bench [--provider ollama|anthropic] [--model NAME] [--runs 3]

Each row of cases.csv is one synthetic Vietnamese sentence. ``{...}`` marks the candidate words,
``{~}`` a wordless sound the voice detector heard (a VAD candidate). For category retake_found
there is no candidate: ``{...}`` marks the abandoned attempt the LLM should list as a retake
(expected "found"), or nothing is marked (expected "none"). Every case goes through the real
review code (prompt, schema, validation) as its own chunk, ``--runs`` times, and the bench
prints accuracy per category and how many cases got the same answer in every run.
The sentences are synthetic, so only they (never transcript text) reach the provider.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stuttercut.asr import Word
from stuttercut.config import LlmConfig
from stuttercut.llm import LLMClient, LLMError
from stuttercut.llm.review import review

CASES = Path(__file__).parent / "cases.csv"
_REASON = {  # category -> (cut reason, source, rule confidence) as the detector would send it
    "filler_hesitation": ("filler", "rules", 0.9),
    "filler_meaningful": ("filler", "rules", 0.6),
    "repeat_true": ("repeat", "rules", 0.8),
    "repeat_intentional": ("repeat", "rules", 0.8),
    "retake_candidate": ("retake", "rules", 0.6),
    "vad_no_text": ("filler", "vad", 0.4),
}
_AMBIGUOUS = {"à", "ừ"}  # the rules give these a lower confidence (0.6)


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    expected: str  # cut | keep | found | none
    words: list[Word]
    span: tuple[float, float] | None  # the marked time range
    note: str

    def rows(self) -> list[dict[str, Any]]:
        """The candidate row the review gets (none for retake_found)."""
        if self.category == "retake_found" or self.span is None:
            return []
        reason, source, conf = _REASON[self.category]
        inside = [w.text for w in self.words if self.span[0] <= w.start and w.end <= self.span[1]]
        if reason == "filler" and set(inside) <= _AMBIGUOUS and inside:
            conf = 0.6
        start, end = self.span
        return [{"id": 1, "start_s": start, "end_s": end, "reason": reason, "source": source,
                 "confidence": conf, "rule_confidence": conf, "kept": 0}]  # fmt: skip


def parse(sentence: str) -> tuple[list[Word], tuple[float, float] | None]:
    """Words 0.4 s long with 0.1 s gaps; ``{~}`` takes a 0.4 s slot with no word."""
    words: list[Word] = []
    span: list[float] = []
    t = 0.0
    for tok in sentence.split():
        opens, closes = tok.startswith("{"), tok.endswith("}")
        text = tok.strip("{}")
        if opens:
            span.append(t)
        if text != "~":
            words.append(Word(text, t, t + 0.4))
        if closes:
            span.append(t + 0.4)
        t += 0.5
    if len(span) not in (0, 2):
        raise ValueError(f"need one {{...}} span: {sentence!r}")
    return words, (span[0], span[1]) if span else None


def load_cases(path: Path = CASES) -> list[Case]:
    with path.open(encoding="utf-8", newline="") as f:
        out = []
        for r in csv.DictReader(f):
            words, span = parse(r["sentence"])
            out.append(Case(r["id"], r["category"], r["expected"], words, span, r["note"]))
    return out


def judge(case: Case, client: LLMClient, cfg: LlmConfig, sure_min: float) -> tuple[str, str]:
    """(answer, LLM reason) for one case: cut/keep, found/none, missing or error."""
    try:
        out = review(case.words, case.rows(), client, cfg, sure_min)
    except LLMError as e:
        return "error", str(e)[:80]
    if case.category == "retake_found":
        if not out.new_cuts:
            return "none", ""
        s = case.span
        hits = [
            why for c, _t, why in out.new_cuts if s is None or min(c.end, s[1]) > max(c.start, s[0])
        ]
        return ("found", hits[0]) if hits else ("misplaced", out.new_cuts[0][2])
    if not out.updates:
        return "missing", ""
    ((_id, _final, _tier, verdict, conf, why),) = out.updates
    return verdict, f"{conf:.2f} {why}"


def score(cases: list[Case], answers: dict[str, list[str]]) -> dict[str, dict[str, float]]:
    """Per category: n cases, accuracy over all runs, share of cases with one answer in all runs."""
    by_cat: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_cat[c.category].append(c)
    by_cat["all"] = list(cases)
    out = {}
    for cat, group in by_cat.items():
        runs = [a for c in group for a in answers[c.id]]
        right = sum(a == c.expected for c in group for a in answers[c.id])
        out[cat] = {
            "n": len(group),
            "accuracy": round(right / len(runs), 3),
            "stable": round(sum(len(set(answers[c.id])) == 1 for c in group) / len(group), 3),
        }
    return out
