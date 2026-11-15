"""LLM review: client contract, parsing, chunking, merge/tier logic. No network."""

import io
import json
import urllib.error
from email.message import Message
from itertools import pairwise
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from hypothesis import given
from hypothesis import strategies as st

from stuttercut.asr import Word
from stuttercut.config import LlmConfig
from stuttercut.llm import LLMError, LLMTimeout
from stuttercut.llm.anthropic_client import FALLBACK_BETA, AnthropicClient
from stuttercut.llm.fake import FakeLLMClient
from stuttercut.llm.ollama_client import OllamaClient
from stuttercut.llm.review import (
    SCHEMA,
    InvalidReply,
    assign,
    build_prompt,
    chunk_ranges,
    combine,
    review,
    to_candidates,
)

CFG = LlmConfig(enabled=True, api_key="test-key", chunk_words=8, chunk_overlap_words=3)
CLAUDE = LlmConfig(enabled=True, provider="anthropic", api_key="test-key")


def words(*texts: str) -> list[Word]:
    return [Word(t, i * 0.5, i * 0.5 + 0.4) for i, t in enumerate(texts)]


def row(cut_id: int, start: float, end: float, reason: str, source: str = "rules",
        conf: float = 0.9) -> dict[str, Any]:  # fmt: skip
    return {"id": cut_id, "start_s": start, "end_s": end, "reason": reason, "source": source,
            "confidence": conf, "rule_confidence": conf, "kept": 0}  # fmt: skip


def reply(verdicts: list[dict[str, Any]], retakes: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"verdicts": verdicts, "retakes": retakes or []})


WORDS = words("[UH]", "tôi", "tôi", "sẽ", "nói", "vậy", "à")
ROWS = [row(1, 0.0, 0.4, "filler"), row(2, 0.5, 0.9, "repeat", conf=0.8),
        row(3, 3.0, 3.4, "filler", "rules", 0.6)]  # fmt: skip


# --- Anthropic client contract ---------------------------------------------------------------


class FakeSdk:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def response(text: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
    )


def test_anthropic_request_shape_and_usage() -> None:
    sdk = FakeSdk(response('{"verdicts": [], "retakes": []}'))
    out = AnthropicClient(CLAUDE, sdk=sdk).complete("system text", "0\ttôi", SCHEMA)
    assert (out.text, out.input_tokens, out.output_tokens) == (
        '{"verdicts": [], "retakes": []}',
        1200,
        150,
    )
    k = sdk.kwargs
    assert k["model"] == "claude-sonnet-5-5" and k["system"] == "system text"
    assert k["messages"] == [{"role": "user", "content": "0\ttôi"}]  # text only
    assert k["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert k["betas"] == [FALLBACK_BETA] and k["fallbacks"] == "default"
    assert "temperature" not in k and "thinking" not in k


def test_anthropic_errors_map_to_llm_errors() -> None:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(LLMTimeout):
        AnthropicClient(CLAUDE, sdk=FakeSdk(anthropic.APITimeoutError(request=req))).complete(
            "s", "p", SCHEMA
        )
    with pytest.raises(LLMError, match="connection"):
        AnthropicClient(CLAUDE, sdk=FakeSdk(anthropic.APIConnectionError(request=req))).complete(
            "s", "p", SCHEMA
        )
    with pytest.raises(LLMError, match="refusal"):
        AnthropicClient(CLAUDE, sdk=FakeSdk(response("", stop="refusal"))).complete(
            "s", "p", SCHEMA
        )


def test_anthropic_needs_a_key() -> None:
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        AnthropicClient(LlmConfig(enabled=True, provider="anthropic", api_key=""))


# --- Ollama client contract ------------------------------------------------------------------


class FakePost:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def __call__(self, url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((url, payload, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_ollama_request_shape_and_usage() -> None:
    text = '{"verdicts": [], "retakes": []}'
    post = FakePost({"message": {"role": "assistant", "content": text}, "done_reason": "stop",
                     "prompt_eval_count": 900, "eval_count": 40})  # fmt: skip
    client = OllamaClient(CFG, post=post)
    out = client.complete("system text", "0	tôi", SCHEMA)
    assert (out.text, out.input_tokens, out.output_tokens) == (
        '{"verdicts": [], "retakes": []}', 900, 40,
    )  # fmt: skip
    ((url, payload, timeout),) = post.calls
    assert url == "http://127.0.0.1:11434/api/chat" and timeout == 30.0
    assert client.model == payload["model"] == "qwen3:8b"
    assert payload["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "0	tôi"},
    ]  # text only
    assert payload["format"] == SCHEMA and payload["stream"] is False and payload["think"] is False
    assert payload["options"]["temperature"] == 0 and payload["options"]["num_ctx"] == 8192


@pytest.mark.parametrize(
    ("error", "kind", "match"),
    [
        (TimeoutError("timed out"), LLMTimeout, "30 s"),
        (urllib.error.URLError(TimeoutError("timed out")), LLMTimeout, "30 s"),
        (urllib.error.URLError(ConnectionRefusedError(10061, "refused")), LLMError, "reach Ollama"),
        (urllib.error.HTTPError("u", 404, "nf", Message(), io.BytesIO(b'{"error":"not found"}')),
         LLMError, "ollama pull qwen3:8b"),
    ],
)  # fmt: skip
def test_ollama_errors_map_to_llm_errors(error: Exception, kind: type, match: str) -> None:
    with pytest.raises(kind, match=match):
        OllamaClient(CFG, post=FakePost(error)).complete("s", "p", SCHEMA)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, None),  # disabled
        ({"STUTTERCUT_LLM_ENABLED": "true"}, "OllamaClient"),  # local: no key needed
        ({"STUTTERCUT_LLM_ENABLED": "true", "STUTTERCUT_LLM_PROVIDER": "anthropic"}, None),
    ],
)
def test_load_llm_picks_the_provider(env: dict[str, str], expected: str | None) -> None:
    from pathlib import Path

    from stuttercut.config import load_config
    from stuttercut.worker.main import load_llm

    llm = load_llm(load_config(env=env, dotenv=Path("missing.env")))
    assert (type(llm).__name__ if llm else None) == expected


def test_ollama_truncated_reply_is_an_error() -> None:
    post = FakePost({"message": {"content": '{"verdicts": ['}, "done_reason": "length"})
    with pytest.raises(LLMError, match="8000 tokens"):
        OllamaClient(CFG, post=post).complete("s", "p", SCHEMA)


# --- chunking and request ----------------------------------------------------------------------


@given(st.integers(min_value=0, max_value=500), st.integers(min_value=2, max_value=60), st.data())
def test_chunks_cover_everything_with_overlap(n: int, size: int, data: st.DataObject) -> None:
    overlap = data.draw(st.integers(min_value=0, max_value=size - 1))
    ranges = chunk_ranges(n, size, overlap)
    covered = {i for s, e in ranges for i in range(s, e)}
    assert covered == set(range(n))
    assert all(0 < e - s <= size for s, e in ranges)
    for (_s1, e1), (s2, _e2) in pairwise(ranges):
        assert e1 - s2 == overlap


def test_chunk_ranges_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_ranges(10, 5, 5)


def test_candidates_by_word_index_and_prompt_has_no_times_or_paths() -> None:
    rows = [*ROWS, row(4, 2.4, 2.45, "pause")]
    cands = to_candidates(rows, WORDS)
    assert [(c.id, c.first, c.last, c.after) for c in cands] == [
        (1, 0, 0, -1), (2, 1, 1, 0), (3, 6, 6, 5), (4, None, None, 4),
    ]  # fmt: skip
    prompt = build_prompt(WORDS, (0, 7), cands)
    assert "0\t[UH]" in prompt and '"silence_after_word": 4' in prompt
    for forbidden in ("0.4", "3.0", "start_s", ".mp4", "C:/", "c001"):
        assert forbidden not in prompt


def test_candidate_goes_to_first_chunk_holding_its_context() -> None:
    cands = to_candidates([row(1, 3.0, 4.4, "retake")], words(*["x"] * 20))  # words 6..8
    groups = assign(cands, chunk_ranges(20, 8, 3))  # (0,8) (5,13) (10,18) (15,20)
    assert [len(g) for g in groups] == [0, 1, 0, 0]


# --- parsing, retries, merge ------------------------------------------------------------------


def test_valid_reply_updates_confidence_and_tier() -> None:
    llm = FakeLLMClient(reply([
        {"id": 1, "verdict": "cut", "confidence": 0.95, "reason": "hesitation"},
        {"id": 2, "verdict": "cut", "confidence": 0.9, "reason": "repeat"},
        {"id": 3, "verdict": "keep", "confidence": 0.9, "reason": "question particle"},
        {"id": 99, "verdict": "cut", "confidence": 1.0, "reason": "unknown id"},
    ]))  # fmt: skip
    out = review(WORDS, ROWS, llm, CFG, sure_min=0.7)
    assert [(u[0], u[1], u[2], u[3]) for u in out.updates] == [
        (1, 0.93, "sure", "cut"), (2, 0.86, "sure", "cut"), (3, 0.3, "unsure", "keep"),
    ]  # fmt: skip
    assert out.ignored == 1 and out.requests == 1
    assert (out.input_tokens, out.output_tokens) == (100, 20)
    assert out.cost_usd(CLAUDE) == round(100 / 1e6 * 2 + 20 / 1e6 * 10, 5)
    assert out.cost_usd(CFG) == 0.0  # ollama: local, free


def test_malformed_reply_is_retried_once() -> None:
    llm = FakeLLMClient(
        "not json", reply([{"id": 1, "verdict": "cut", "confidence": 1, "reason": "x"}])
    )
    out = review(WORDS, ROWS[:1], llm, CFG, 0.7)
    assert len(llm.calls) == 2 and out.requests == 2 and len(out.updates) == 1


@pytest.mark.parametrize("bad", [
    "{}",
    reply([{"id": 1, "verdict": "maybe", "confidence": 1, "reason": "x"}]),
    reply([{"id": 1, "verdict": "cut", "confidence": 1.5, "reason": "x"}]),
    reply([{"id": 1, "verdict": "cut", "confidence": 1, "reason": "x", "extra": 1}]),
])  # fmt: skip
def test_invalid_twice_raises(bad: str) -> None:
    with pytest.raises(InvalidReply):
        review(WORDS, ROWS[:1], FakeLLMClient(bad), CFG, 0.7)


def test_timeout_propagates_for_the_caller_to_fall_back() -> None:
    with pytest.raises(LLMTimeout):
        review(WORDS, ROWS, FakeLLMClient(LLMTimeout("30 s")), CFG, 0.7)


def test_llm_retakes_become_new_cuts_and_bad_ones_are_dropped() -> None:
    ws = words("bài", "đầu", "tiên", "chúng", "[UH]", "bài", "đầu", "tiên", "là")
    retakes = [
        {"first_word": 0, "last_word": 3, "confidence": 0.9, "reason": "restarted"},
        {"first_word": 0, "last_word": 3, "confidence": 0.9, "reason": "duplicate"},
        {"first_word": 7, "last_word": 2, "confidence": 0.9, "reason": "reversed"},
        {"first_word": 40, "last_word": 41, "confidence": 0.9, "reason": "out of range"},
    ]
    cfg = LlmConfig(enabled=True, api_key="k", chunk_words=300, chunk_overlap_words=40)
    out = review(ws, [], FakeLLMClient(reply([], retakes)), cfg, 0.7)
    ((cut, tier_, why),) = out.new_cuts
    assert (cut.start, cut.end, cut.reason, cut.source, tier_) == (
        0.0,
        2.0,
        "retake",
        "llm",
        "sure",
    )
    assert why == "restarted" and out.ignored == 3


def test_llm_retake_duplicating_a_rule_candidate_is_skipped() -> None:
    ws = words("bài", "đầu", "tiên", "chúng", "[UH]", "bài")
    rows = [row(7, 0.0, 2.0, "retake", conf=0.5)]
    r = reply([{"id": 7, "verdict": "cut", "confidence": 0.9, "reason": "x"}],
              [{"first_word": 0, "last_word": 3, "confidence": 0.9, "reason": "same"}])  # fmt: skip
    out = review(ws, rows, FakeLLMClient(r), LlmConfig(enabled=True, api_key="k"), 0.7)
    assert out.new_cuts == [] and len(out.updates) == 1


def test_long_transcript_is_sent_in_overlapping_chunks() -> None:
    ws = words(*[f"w{i}" for i in range(20)])
    llm = FakeLLMClient(reply([]))
    review(ws, [], llm, CFG, 0.7)
    assert len(llm.calls) == 4  # 8-word chunks, 3 words shared
    assert "4\tw4" in llm.calls[0]["prompt"] and "5\tw5" in llm.calls[1]["prompt"]


prob = st.floats(min_value=0, max_value=1, allow_nan=False)


@given(prob, prob, prob)
def test_combine_bounds_and_keep_never_beats_cut(rule: float, c: float, w: float) -> None:
    cut, keep = combine(rule, "cut", c, w), combine(rule, "keep", c, w)
    assert 0 <= keep <= 1 and 0 <= cut <= 1
    if c >= 0.5:
        assert keep <= cut + 1e-9  # a confident "keep" never raises it above the "cut" verdict


@given(prob, prob)
def test_combine_extremes_of_weight(rule: float, c: float) -> None:
    assert combine(rule, "cut", c, 0.0) == round(rule, 3)  # weight 0: rules only
    assert combine(rule, "keep", c, 1.0) == round(1 - c, 3)  # weight 1: LLM only


@given(st.lists(st.tuples(st.sampled_from(["cut", "keep"]), prob), min_size=1, max_size=5))
def test_review_never_drops_a_candidate(verdicts: list[tuple[str, float]]) -> None:
    rows = [row(i, i * 0.5, i * 0.5 + 0.4, "filler") for i in range(len(verdicts))]
    ws = words(*["ờ"] * len(verdicts))
    r = reply(
        [
            {"id": i, "verdict": v, "confidence": c, "reason": "r"}
            for i, (v, c) in enumerate(verdicts)
        ]
    )
    out = review(ws, rows, FakeLLMClient(r), LlmConfig(enabled=True, api_key="k"), 0.7)
    assert sorted(u[0] for u in out.updates) == list(range(len(verdicts)))
