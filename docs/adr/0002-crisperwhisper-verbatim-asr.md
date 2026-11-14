# 0002 — CrisperWhisper for verbatim ASR

- **Status:** Proposed — pending spike [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205)
- **Date:** 2026-11-14
- **Jira:** LEARNING-234

## Context

Detection needs a **verbatim** transcript with accurate **word timestamps**: repeated words,
fillers ("ờ", "ừm") and false starts must appear in the text. Standard Whisper models clean up
disfluencies, so they hide exactly what we want to cut. The model must run locally on Apple
Silicon (`mps`), on CUDA, or on CPU.

## Decision

Use CrisperWhisper 2.0 through PyTorch, selecting the device at runtime (`mps` → `cuda` →
`cpu`). Hide it behind a `Transcriber` interface so tests use a fake transcriber with captured
transcripts. Spike LEARNING-205 will compare verbatim ASR models on Vietnamese stuttered clips;
this ADR is accepted, amended or superseded based on its results.

## Consequences

- Detection quality depends on the model keeping disfluencies in Vietnamese; this is the main
  project risk until LEARNING-205 reports.
- The model download and memory use must fit a 16 GB Mac; it loads only in the worker.
- The `Transcriber` interface keeps unit and integration tests fast and offline, and makes a
  model swap a local change.
