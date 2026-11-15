"""Scripted LLM client for tests: no network."""

from collections.abc import Callable
from typing import Any

from stuttercut.llm import LLMReply

Script = str | Exception | Callable[[str], str]


class FakeLLMClient:
    """Answers each call with the next scripted item: a JSON string, an exception to raise,
    or a function of the prompt that returns the JSON. The last item repeats."""

    model = "fake-llm"

    def __init__(self, *script: Script, tokens: tuple[int, int] = (100, 20)) -> None:
        if not script:
            raise ValueError("give at least one scripted reply")
        self._script = list(script)
        self._tokens = tokens
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> LLMReply:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        item = self._script[min(len(self.calls), len(self._script)) - 1]
        if isinstance(item, Exception):
            raise item
        text = item(prompt) if callable(item) else item
        return LLMReply(text=text, input_tokens=self._tokens[0], output_tokens=self._tokens[1])
