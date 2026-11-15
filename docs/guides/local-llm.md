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

- **Before the review:** the worker unloads the ASR model and empties the CUDA/MPS cache
  (span `unload_asr`) when the LLM would not fit next to it. On CUDA: free VRAM (all
  processes) < `STUTTERCUT_LLM_EXPECTED_GB` (6) + `STUTTERCUT_LLM_VRAM_MARGIN_GB` (1). On MPS
  and CPU (shared memory): free RAM < `STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB` (8). The next job
  loads it again (span `load_model`); the CLI prints that reload time.
- **Loading the LLM:** an empty request loads the model first (span `llm_load`,
  `STUTTERCUT_LLM_LOAD_TIMEOUT_S` = 120 s), so each chunk request gets the full
  `STUTTERCUT_LLM_TIMEOUT_S` (30 s).
- **After the review:** the worker asks Ollama to unload the model at once (`keep_alive: 0`),
  so the next job's ASR gets the RAM/VRAM back. `STUTTERCUT_LLM_KEEP_ALIVE` (30 s) only
  bridges the gap between chunk requests.
- **Context and chunks:** `STUTTERCUT_LLM_NUM_CTX` (6144 tokens) must hold one chunk
  (`STUTTERCUT_LLM_CHUNK_WORDS` 150 + 30 overlap), the candidates, the system prompt and the
  reply. 150 words keeps a dense chunk well under 30 s on an 8B model (about 0.9 s per
  candidate on an RTX 4060); 300-word chunks took up to 30 s and timed out. If the context
  fills up, the review fails with a clear error instead of Ollama silently dropping the start of the prompt.

## 4. How verdicts change the tiers

The merge is asymmetric: the LLM can only lower a cut's confidence, never lift it to `sure`.

- `cut`: the rule confidence stays as it is.
- `keep`: `min(rule, 0.4 * rule + 0.6 * (1 - LLM confidence))`, and always below
  `STUTTERCUT_TIER_SURE_MIN` (0.7), so the cut is shown as `unsure`. It is never removed.
- Retakes the LLM finds enter as `unsure`.

Why: qwen3:8b calls almost everything "cut", including meaningful "à"/"ừ" (bench below), so a
"cut" verdict carries no information, while a wrong "keep" only costs a second look.

## 5. Check on a clip

```bash
python -m stuttercut.worker.cli "<video>"
```

Look for the `llm_review` span, `llm ollama qwen3:8b: tokens in/out, verdict keep N, new
retakes N`, `llm peak in Ollama: ... MB, of which VRAM ... MB`, and, when the ASR was
unloaded, `asr unloaded before llm_review; reload N s`. Never paste transcript text into
issues or PRs; the CLI prints none.

## Performance on c001 (161 s, 746 words, 48 candidates; RTX 4060 8 GB, 2026-11-15)

| | ASR unloaded (default) | ASR kept on the GPU |
| --- | --- | --- |
| `unload_asr` | 0.3 s (free VRAM 0.0 → 6.9 GB) | — |
| `llm_load` | 2.6 s (35 s on the very first load from disk) | 5.8 s |
| `llm_review` (6 chunks) | 48 s | 91 s (model 0.5 GB on CPU) |
| Ollama peak | 5.6 GB, all VRAM | 6.0 GB, 5.5 GB VRAM |
| GPU peak, all processes | 7.8 GB of 8 GB | 7.8 GB |
| ASR reload for the next job | 5.5 s | — |
| Tokens in / out | 9.6k / 1.9k | 9.6k / 1.9k |

Chunk peak: 2.0k tokens in + 0.6k out, so 6144 leaves room for a chunk twice as dense.

## Verdict quality: the bench (eval/llm_bench)

35 hand-written sentences (no real voices) with the expected verdict per case: hesitation
fillers, meaningful à/ừ/ờ, true vs intentional repeats, retake candidates, retakes with no
candidate, and wordless VAD candidates. Each case runs through the real prompt and schema.

```bash
python -m eval.llm_bench --provider ollama            # or anthropic (needs LLM_API_KEY)
python -m eval.llm_bench --model qwen2.5:7b --runs 3
```

It prints accuracy per category and `stable` (same answer in every run). qwen3:8b, RTX 4060,
2026-11-15, 3 runs each:

| category (n) | first prompt | current prompt | current, thinking on (1 run, diagnostic) |
| --- | --- | --- | --- |
| filler_hesitation (7) | 100% | 86% | 86% |
| filler_meaningful (7) | 0% | 57% | 57% |
| repeat_true (4) | 100% | 25% | 100% |
| repeat_intentional (4) | 0% | 100% | 75% |
| retake_candidate (5) | 60% | 60% | 60% (2 timeouts) |
| retake_found (4) | 50% (never finds one) | 50% (never finds one) | 50% (2 timeouts) |
| vad_no_text (4) | 50% | 50% | 75% (1 error) |
| **all (35)** | **51%** | **63%** | **71%** (83% of answered) |
| stable over 3 runs | 100% | 100% | — |
| time per case | 1.1 s | 1.2 s | 40 s |

The first prompt said "cut" to all 35 cases. The current prompt puts the reason before the
verdict, shows each candidate's words in place (an 8B model looks words up by index poorly)
and drops the rule confidence (it anchored the model to "cut"). Its "keep" is right 9 of 14
times. Thinking helps but is far too slow for the 30 s chunk timeout. On c001 (tune split)
the current prompt gives 3 keep verdicts, 0 new retakes, 22 sure / 26 unsure (rules-only:
22 / 26), `llm_review` 54 s.

## Known limits (qwen3:8b, LEARNING-208)

- **Weak verdicts.** 63% on the bench; half of the meaningful "à"/"ừ"/"ờ" still get "cut"
  (harmless with the asymmetric merge: they keep their rule tier) and 3 of 4 true repeats get
  "keep" (they drop to `unsure`).
- **No retakes found** on the bench or c001 with thinking off.
- **Wordless candidates are a guess.** The LLM reads text only; for a VAD candidate it knows
  only that some sound sits after word i.
- The bench is small and written by us; a few points of accuracy are one or two cases.

## Troubleshooting

| Symptom (WARN in the log, `llm_review` span = error) | Fix |
| --- | --- |
| `cannot reach Ollama at http://127.0.0.1:11434` | Start Ollama (tray app, or `ollama serve`) |
| `Ollama error 404 ... (run: ollama pull qwen3:8b)` | Pull the model |
| `model not loaded within 120 s` | Slow first load from disk; raise `STUTTERCUT_LLM_LOAD_TIMEOUT_S` |
| `no answer within 30 s` | A dense chunk on a slow machine: lower `STUTTERCUT_LLM_CHUNK_WORDS` or raise `STUTTERCUT_LLM_TIMEOUT_S` |
| `context full (...)` | Raise `STUTTERCUT_LLM_NUM_CTX` or lower `STUTTERCUT_LLM_CHUNK_WORDS` |
