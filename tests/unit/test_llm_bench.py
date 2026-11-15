"""eval/llm_bench: case parsing and scoring with a fake LLM (no network)."""

import json

from eval.llm_bench import judge, load_cases, parse, score
from stuttercut.config import LlmConfig
from stuttercut.llm.fake import FakeLLMClient

CFG = LlmConfig(enabled=True)


def test_parse_marks_words_and_wordless_slots() -> None:
    words, span = parse("giá {của nó} là")
    assert [w.text for w in words] == ["giá", "của", "nó", "là"] and span == (0.5, 1.4)
    words, span = parse("giá {~} là")
    assert [w.text for w in words] == ["giá", "là"] and span == (0.5, 0.9)
    assert parse("không có gì") == (parse("không có gì")[0], None)


def test_every_case_parses_and_covers_the_categories() -> None:
    cases = load_cases()
    assert len(cases) >= 30 and len({c.id for c in cases}) == len(cases)
    assert {c.category for c in cases} == {
        "filler_hesitation", "filler_meaningful", "repeat_true", "repeat_intentional",
        "retake_candidate", "retake_found", "vad_no_text",
    }  # fmt: skip
    for c in cases:
        assert c.expected in (
            {"found", "none"} if c.category == "retake_found" else {"cut", "keep"}
        )
        assert (c.span is None) == (c.expected == "none"), c.id
        if c.category == "vad_no_text":
            (row,) = c.rows()
            assert row["source"] == "vad" and not any(
                row["start_s"] <= w.start < row["end_s"] for w in c.words
            )


def test_judge_and_score_with_a_fake_llm() -> None:
    cases = {c.id: c for c in load_cases()}
    cut_all = json.dumps({"verdicts": [{"id": 1, "verdict": "cut", "confidence": 0.9,
                                        "reason": "r"}], "retakes": []})  # fmt: skip
    retake = json.dumps({"verdicts": [], "retakes": [
        {"first_word": 0, "last_word": 2, "confidence": 0.9, "reason": "restart"}]})  # fmt: skip
    assert judge(cases["m1"], FakeLLMClient(cut_all), CFG, 0.7) == ("cut", "0.90 r")
    assert judge(cases["f1"], FakeLLMClient(retake), CFG, 0.7) == ("found", "restart")
    assert judge(cases["n1"], FakeLLMClient(retake), CFG, 0.7)[0] == "found"  # a false retake
    assert judge(cases["f1"], FakeLLMClient("not json"), CFG, 0.7)[0] == "error"

    picked = [cases["h1"], cases["m1"]]
    s = score(picked, {"h1": ["cut", "cut"], "m1": ["cut", "keep"]})
    assert s["filler_hesitation"] == {"n": 1, "accuracy": 1.0, "stable": 1.0}
    assert s["all"] == {"n": 2, "accuracy": 0.75, "stable": 0.5}
