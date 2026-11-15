"""Anthropic Messages API client (default provider). Key: LLM_API_KEY in .env.

Structured outputs (``output_config.format``) constrain the reply to the JSON schema; the
reviewer still validates it with pydantic. ``fallbacks: "default"`` lets the API re-run a
request on Anthropic's recommended fallback model if a safety classifier declines it.
SDK retries are off: the reviewer retries once on invalid JSON and otherwise falls back to
rules-only, so one call never waits longer than ``timeout_s``.
"""

from typing import Any

from stuttercut.config import LlmConfig
from stuttercut.llm import LLMError, LLMReply, LLMTimeout

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicClient:
    def __init__(self, cfg: LlmConfig, sdk: Any | None = None) -> None:
        if sdk is None:
            import anthropic

            if not cfg.api_key:
                raise LLMError("LLM_API_KEY is not set in .env")
            sdk = anthropic.Anthropic(api_key=cfg.api_key, timeout=cfg.timeout_s, max_retries=0)
        self._sdk: Any = sdk  # request shape is pinned by tests/unit/test_llm.py
        self._cfg = cfg
        self.model = cfg.model

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> LLMReply:
        import anthropic

        try:
            response = self._sdk.beta.messages.create(
                model=self._cfg.model,
                max_tokens=self._cfg.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": self._cfg.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as e:
            raise LLMTimeout(f"no answer within {self._cfg.timeout_s:.0f} s") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMError("the model declined the request (refusal)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LLMReply(
            text=text,
            input_tokens=int(response.usage.input_tokens),
            output_tokens=int(response.usage.output_tokens),
        )
