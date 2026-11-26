# LEARNING-208 — LLM review of cut candidates

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-208

## Prompt

```text
Task: LEARNING-208 — LLM finds retakes and judges every cut candidate in context. Read CLAUDE.md, the Jira description of LEARNING-208, ADR 0001 (local-first: only transcript text may leave the machine) and lesson 003 first.
Branch: feature/LEARNING-208-llm-review. Work without asking unless something fails twice.

Housekeeping first (own commit, LEARNING-207 key): fill the Outcome of docs/prompts/LEARNING-207-cut-detection.md, set its PR to #4 in docs/prompts/README.md, add this prompt's row.

1. llm/: an LLMClient protocol with one real implementation (provider and model from config, API key from .env) and a FakeLLMClient for tests. Before writing the real client, ask me once which provider/model to use if .env has none configured; default the code to the Anthropic Messages API.
2. Request: only text — verbatim words with indices (no timestamps needed), plus the candidate cuts as word-index ranges with reason/source/confidence. Never send audio, video, file paths or clip names. Chunk long transcripts with overlap so each request stays small.
3. Response: strict JSON validated with a schema (pydantic): (a) retakes as word-index ranges + short reason; (b) a verdict per candidate: cut | keep, confidence 0–1, short reason. Reject and retry once on invalid JSON; 30 s timeout; on failure fall back to rules-only, WARN log, span "llm_review" status error, job still ready_for_review.
4. Merge: final confidence = combine rule confidence and LLM verdict (document the formula); tier = sure | unsure (threshold in config). Store tier, llm_verdict and llm_reason on CUT (migration). LLM retakes become new cuts with source=llm. A keep verdict lowers confidence but never deletes the candidate; the human decides.
5. Worker: step llm_review after detect when STUTTERCUT_LLM_ENABLED=true (default false until a key is set). Log token usage and cost estimate per job.
6. CLI: print counts per tier and per source, and llm_review timing and tokens. Never print transcript text.
7. Tests (no network): parsing valid/malformed/timeout responses, chunking with overlap, merge/tier logic (property tests), worker path with LLM disabled and with FakeLLMClient.

Out of scope: UI (209), render (210).

Run lint, mypy, pytest. If a key is configured, run the CLI on c001 with the LLM enabled and report tier counts, how many candidates the LLM marked keep, new retakes, time and tokens. Commit in small Conventional Commits with LEARNING-208, push, open the PR with gh, watch CI until green, do not merge.
```

## Follow-up: local LLM provider

```text
LEARNING-208 follow-up on the same branch: add a local LLM provider.
1. OllamaClient implementing LLMClient via Ollama's local HTTP API (127.0.0.1:11434), JSON output enforced, same schema validation/retry/timeout. Config STUTTERCUT_LLM_PROVIDER = ollama (default) | anthropic, STUTTERCUT_LLM_MODEL (pick a 7–8B model with good Vietnamese, tell me which and why).
2. Memory: before llm_review, unload the ASR model and free CUDA/MPS memory when free RAM is below a config threshold; record the extra reload cost in the CLI output.
3. Run c001 with the local model (pull it if needed, keep the 5 GB free-disk guard). Report tier counts, keep verdicts, new retakes, llm_review time, peak RAM/VRAM, and show 5 example verdicts as (reason, verdict, confidence) only — no transcript text.
4. Update ADR 0001/0002 notes, .env.example and running docs. Commit with LEARNING-208, push, watch CI, do not merge.
```

## Follow-up: asymmetric merge and LLM bench

```text
Decisions for PR #5 (LEARNING-208):
1. Asymmetric merge for all reasons: the LLM can only lower confidence (keep -> demote to unsure); it never raises a candidate to sure. LLM-proposed retakes enter as unsure. Update tests and docs.
2. Add eval/llm_bench/: ~30 hand-written Vietnamese sentences (no real voices) covering hesitation fillers, meaningful à/ừ/ờ (question particle, "à, ra là vậy", answers), true repeats vs intentional repetition, retakes, and no-text VAD candidates; expected verdict per case. "python -m eval.llm_bench --provider ollama|anthropic" prints accuracy per category and determinism over 3 runs.
3. Run it on qwen3:8b now. c001 is in the tune split, so prompt tuning on it is allowed.
Commit with LEARNING-208, push, watch CI, do not merge. I will add an Anthropic key later to compare.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/5 (merged 2026-11-15).

**Worked well**
- One `LLMClient` protocol, two providers (Anthropic, Ollama) and a fake; strict JSON schema + pydantic, one retry, rules-only fallback on any failure.
- Local by default: qwen3:8b on Ollama, ASR unloaded before the review when VRAM/RAM is short (llm_review 91 s → 48 s on the RTX 4060), model warmed under its own timeout, unloaded after.
- `eval/llm_bench`: 35 synthetic cases measure verdicts without real voices; deterministic at temperature 0.

**Had to be corrected or deviated from the prompt**
- 300-word chunks timed out at 30 s on the local model; 150 + 30 overlap.
- Wordless VAD candidates were sent as "silence"; fixed to "unwritten sound".
- qwen3:8b judged meaningful "à"/"ừ" as cut and lifted them to `sure`; the merge became asymmetric (the LLM can only lower confidence).
- Bench: first prompt 51% (said "cut" to everything), final 63%; thinking mode 71% but 40 s per case. No retakes found without thinking.

**Next time**
- Build the bench before tuning the prompt, and compare a second provider before choosing the merge rule.
