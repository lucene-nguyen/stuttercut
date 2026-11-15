"""LLM client interface for the cut review (LEARNING-208).

Privacy (ADR 0001): a client receives only a system prompt, the transcript text with word
indices and candidate metadata. Never audio, video, timestamps of the recording, file paths
or clip names.
"""

from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The LLM call failed (network, API error, refusal); the caller falls back to rules."""


class LLMTimeout(LLMError):
    pass


@dataclass(frozen=True)
class LLMReply:
    text: str  # the JSON document the model wrote
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> LLMReply:
        """One request; ``schema`` is the JSON schema the reply must follow."""
        ...
