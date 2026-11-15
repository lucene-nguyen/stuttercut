# LLM review with a local model (Ollama)

The `llm_review` step judges each cut candidate in context and finds retakes the rules missed
(LEARNING-208). By default it runs a local model through [Ollama](https://ollama.com), so
nothing leaves the machine. The Anthropic API is an opt-in alternative (ADR 0001 amendment).

## 1. Install Ollama and pull the model

| OS | Install |
| --- | --- |
| Windows | Download `OllamaSetup.exe` from <https://ollama.com/download> and run it (per-user install, starts in the tray) |
| macOS | Download the app from <https://ollama.com/download>, or `brew install ollama` |

Then, with at least 10 GB free disk (the model is ~5.2 GB; keep 5 GB spare):

```bash
ollama pull qwen3:8b
ollama list                      # qwen3:8b should be listed
```

Ollama listens on `http://127.0.0.1:11434` only.

**Why `qwen3:8b`:** Qwen3 is pretrained on 119 languages including Vietnamese and follows
JSON schemas well; the 8B q4 build fits an 8 GB GPU or a 16 GB Mac next to the app. Llama 3.1
8B does not list Vietnamese as a supported language, and Gemma 3 has no 7–8B size. Another
model is one setting away: `STUTTERCUT_LLM_MODEL=qwen2.5:7b` (after `ollama pull qwen2.5:7b`).

## 2. Turn it on

In `.env`:

```
STUTTERCUT_LLM_ENABLED=true
# STUTTERCUT_LLM_PROVIDER=ollama   (default)
# STUTTERCUT_LLM_MODEL=            (empty = qwen3:8b)
```

Request settings the client always sends: `think: false` (no `<think>` trace: faster, and the
reply is only the JSON), `temperature: 0`, and the reply JSON schema as `format`. The reply is
still validated with pydantic and retried once; on a timeout (30 s), an Ollama error or a
missing model, the job keeps its rules-only cuts.

## 3. Memory

Two models compete for memory: CrisperWhisper (ASR) and the LLM, which runs in Ollama's own
process.

- **Before the review:** if free RAM is below `STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB` (8), the
  worker unloads the ASR model and empties the CUDA/MPS cache (span `unload_asr`). The next job
  loads it again (span `load_model`); the CLI prints that reload time.
- **After the review:** the worker asks Ollama to unload the model at once (`keep_alive: 0`),
  so the next job's ASR gets the RAM/VRAM back. `STUTTERCUT_LLM_KEEP_ALIVE` (30 s) only
  bridges the gap between chunk requests.
- **Context:** `STUTTERCUT_LLM_NUM_CTX` (8192 tokens) must hold one chunk (300 words + 40
  overlap), the candidates, the system prompt and the reply. If it fills up, the review fails
  with a clear error instead of Ollama silently dropping the start of the prompt.

## 4. Check on a clip

```bash
python -m stuttercut.worker.cli "<video>"
```

Look for the `llm_review` span, `llm ollama qwen3:8b: tokens in/out, verdict keep N, new
retakes N`, `llm peak in Ollama: ... MB, of which VRAM ... MB`, and, when the ASR was
unloaded, `asr unloaded before llm_review; reload N s`. Never paste transcript text into
issues or PRs; the CLI prints none.

## Troubleshooting

| Symptom (WARN in the log, `llm_review` span = error) | Fix |
| --- | --- |
| `cannot reach Ollama at http://127.0.0.1:11434` | Start Ollama (tray app, or `ollama serve`) |
| `Ollama error 404 ... (run: ollama pull qwen3:8b)` | Pull the model |
| `no answer within 30 s` | First request includes loading the model; on a slow machine raise `STUTTERCUT_LLM_TIMEOUT_S` |
| `context full (...)` | Raise `STUTTERCUT_LLM_NUM_CTX` or lower `STUTTERCUT_LLM_CHUNK_WORDS` |
