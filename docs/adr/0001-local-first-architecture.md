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
