# 0001 — Local-first architecture

- **Status:** Accepted
- **Date:** 2026-11-14
- **Jira:** LEARNING-234

## Context

StutterCut edits short (≤ 3 min) Vietnamese videos of real people. The videos are private, a
single person uses the tool, and it must run on one machine: developed on Windows, run on an
Apple Silicon Mac with 16 GB RAM. Cloud transcription or rendering would upload voice and
video, add cost and accounts, and need network for every job.

## Decision

Run everything locally as one web app bound to `127.0.0.1`: a React UI, a FastAPI server and a
worker process on the same machine. ASR, detection rules and rendering run locally. The only
network call is the LLM API for retake detection, and it receives **transcript text only** —
never audio, video or file paths. No accounts, no cloud services, no settings screen.

## Consequences

- Privacy by default; the tool works offline except for retake detection.
- Speed is bounded by local hardware, so model size and encoder choice must fit a 16 GB Mac
  (see ADR 0002, ADR 0003).
- The same codebase must work on Windows and macOS: `pathlib`, `platformdirs`, and runtime
  device/encoder selection with fallbacks.
- When the LLM API is unreachable, the pipeline falls back to rule-only detection.
- Adding any service, database or cloud dependency needs a new ADR.

## Amendment — local LLM by default (LEARNING-208, 2026-11-15)

The LLM review now defaults to a **local model through Ollama** (`STUTTERCUT_LLM_PROVIDER=ollama`,
HTTP on `127.0.0.1:11434`), so by default nothing leaves the machine, not even transcript text.
The Anthropic Messages API stays as an opt-in provider (`anthropic` + `LLM_API_KEY`) under the
original rule: transcript text and candidate word ranges only, never audio, video, timestamps,
file paths or clip names. Ollama is a local runtime the user installs, not a cloud service; it
runs as its own process, so its memory is outside the worker and is reported separately by the
CLI. When Ollama is not running or the model is missing, the review falls back to rules-only
like any other LLM failure.
