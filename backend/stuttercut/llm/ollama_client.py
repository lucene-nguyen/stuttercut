"""Ollama client (default provider): a local model over Ollama's HTTP API on 127.0.0.1.

Nothing leaves the machine. ``format`` carries the JSON schema so Ollama constrains the
output to it; the reviewer still validates with pydantic and retries once. ``think: false``
skips the reasoning trace of thinking models (qwen3): faster, and the reply is the JSON only.
Memory: ``keep_alive`` only bridges the gap between chunk requests; ``release()`` (called by
the pipeline right after llm_review) unloads the model so the next job's ASR gets the RAM/VRAM.
``num_ctx`` is sized for one chunk (docs/guides/local-llm.md); a full context is an error, because
Ollama would otherwise silently drop the start of the prompt.
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
Get = Callable[[str, float], dict[str, Any]]


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
    def __init__(self, cfg: LlmConfig, post: Post = _post, get: Get = _get) -> None:
        self._cfg = cfg
        self._post = post
        self._get = get
        self._base = cfg.ollama_url.rstrip("/")
        self.model = cfg.model
        self.peak_resident_mb: tuple[int, int] | None = None  # (total, VRAM) seen in Ollama

    def resident(self) -> tuple[int, int] | None:
        """(total MB, VRAM MB) of this model while Ollama keeps it loaded; None if not loaded."""
        try:
            models = self._get(self._base + "/api/ps", 5.0).get("models", [])
        except (OSError, ValueError):
            return None
        for m in models:
            if self._cfg.model in (m.get("name"), m.get("model")):
                return round(m.get("size", 0) / 2**20), round(m.get("size_vram", 0) / 2**20)
        return None

    def release(self) -> None:
        """Unload the model now (keep_alive 0) so the next job's ASR gets the memory."""
        try:
            self._post(self._base + "/api/generate", {"model": self._cfg.model, "keep_alive": 0},
                       self._cfg.timeout_s)  # fmt: skip
        except (OSError, ValueError) as e:
            raise LLMError(f"could not unload {self._cfg.model}: {e}") from e

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
        try:
            out = self._post(self._base + "/api/chat", payload, self._cfg.timeout_s)
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
        reply = LLMReply(
            text=str(out.get("message", {}).get("content", "")),
            input_tokens=int(out.get("prompt_eval_count", 0)),
            output_tokens=int(out.get("eval_count", 0)),
        )
        if reply.input_tokens + reply.output_tokens >= self._cfg.num_ctx:
            raise LLMError(
                f"context full ({reply.input_tokens}+{reply.output_tokens} tokens): "
                "raise STUTTERCUT_LLM_NUM_CTX or lower STUTTERCUT_LLM_CHUNK_WORDS"
            )
        if out.get("done_reason") == "length":
            raise LLMError(f"reply cut at {self._cfg.max_tokens} tokens")
        now = self.resident()
        if now and (self.peak_resident_mb is None or now[0] > self.peak_resident_mb[0]):
            self.peak_resident_mb = now
        return reply
