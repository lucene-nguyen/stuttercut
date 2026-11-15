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

## Outcome

_Fill in after the PR merges._
