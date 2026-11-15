"""Ollama client (default provider): a local model over Ollama's HTTP API on 127.0.0.1.

Nothing leaves the machine. ``format`` carries the JSON schema so Ollama constrains the
output to it; the reviewer still validates with pydantic and retries once. ``think: false``
skips the reasoning trace of thinking models (qwen3): faster, and the reply is the JSON only.
Setup: install Ollama, then ``ollama pull <STUTTERCUT_LLM_MODEL>`` (docs/guides).
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from stuttercut.config import LlmConfig
from stuttercut.llm import LLMError, LLMReply, LLMTimeout

Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )  # fmt: skip
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return result


def _get(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return result


class OllamaClient:
    def __init__(self, cfg: LlmConfig, post: Post = _post) -> None:
        self._cfg = cfg
        self._post = post
        self.model = cfg.model

    def resident(self) -> tuple[int, int] | None:
        """(total MB, VRAM MB) of this model while Ollama keeps it loaded; None if not loaded."""
        try:
            models = _get(self._cfg.ollama_url.rstrip("/") + "/api/ps", 5.0).get("models", [])
        except (OSError, ValueError):
            return None
        for m in models:
            if m.get("name") == self._cfg.model or m.get("model") == self._cfg.model:
                return round(m.get("size", 0) / 2**20), round(m.get("size_vram", 0) / 2**20)
        return None

    def complete(self, system: str, prompt: str, schema: dict[str, Any]) -> LLMReply:
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": self._cfg.keep_alive,
            "options": {
                "temperature": 0,
                "num_ctx": self._cfg.num_ctx,
                "num_predict": self._cfg.max_tokens,
            },
        }
        url = self._cfg.ollama_url.rstrip("/") + "/api/chat"
        try:
            out = self._post(url, payload, self._cfg.timeout_s)
        except TimeoutError as e:
            raise LLMTimeout(f"no answer within {self._cfg.timeout_s:.0f} s") from e
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            hint = f" (run: ollama pull {self._cfg.model})" if e.code == 404 else ""
            raise LLMError(f"Ollama error {e.code}: {body}{hint}") from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise LLMTimeout(f"no answer within {self._cfg.timeout_s:.0f} s") from e
            raise LLMError(f"cannot reach Ollama at {self._cfg.ollama_url}: {e.reason}") from e
        if out.get("done_reason") == "length":
            raise LLMError(f"reply cut at {self._cfg.max_tokens} tokens")
        return LLMReply(
            text=str(out.get("message", {}).get("content", "")),
            input_tokens=int(out.get("prompt_eval_count", 0)),
            output_tokens=int(out.get("eval_count", 0)),
        )
