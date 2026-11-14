# 0003 — Separate worker process with a watchdog

- **Status:** Accepted
- **Date:** 2026-11-14
- **Jira:** LEARNING-234

## Context

Transcription and FFmpeg rendering are slow, memory-heavy and can hang or crash (out of
memory, driver errors, a stuck FFmpeg). If they ran inside the API process, the UI would freeze
and a crash would take the server down with it.

## Decision

The API server owns a job queue that runs **one job at a time** and starts the pipeline in a
separate **worker process** (`multiprocessing`). The model and FFmpeg run only in the worker.
A **watchdog** in the API process enforces step timeouts and checks the worker is alive and
within RAM limits (`psutil`); on a breach it kills the worker and marks the job `failed` with
`failed_step`. Limits live in config. The UI never talks to the worker directly.

## Consequences

- The API stays responsive; a crashed or hung worker is detected and the job can be retried.
- Reviewed cuts are stored in SQLite, so they survive a worker crash.
- Process start-up and model loading add latency per job; acceptable for ≤ 3 min clips.
- Worker and API communicate through SQLite state and the queue, which must be tested for
  crash and timeout paths (fault injection).
