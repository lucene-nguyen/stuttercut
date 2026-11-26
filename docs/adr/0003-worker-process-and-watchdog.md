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

## Implementation notes (LEARNING-235, 2026-11-26)

- The watchdog is a thread in the API process (`api/worker_proc.py`), every
  `STUTTERCUT_WATCHDOG_INTERVAL_S` (1 s). It samples the RSS of the worker **and its FFmpeg
  children** (limit `STUTTERCUT_WORKER_MAX_RSS_GB`, 12) and its CPU (shown in `/api/health`).
- Step timeout = `STUTTERCUT_STEP_TIMEOUT_BASE_S` (60) + factor × clip seconds (transcribe 1.5,
  LLM review 1.0, render 1.0, other 0.5); model load 300 s. The running step comes from the
  job row the worker updates (`job.step`, `step_started_at`).
- On a breach or a dead worker: terminate the process tree, kill it after
  `STUTTERCUT_KILL_GRACE_S`, fail the running job at its step with the reason and an error span,
  start a new worker with a **new queue** (a killed process can leave the old one broken) and
  queue again the work waiting in SQLite (queued jobs, requested renders). The same recovery runs
  when the API starts, so a crash or restart never loses waiting work or reviewed cuts.
- The worker frees the ASR model after `STUTTERCUT_MODEL_IDLE_UNLOAD_S` (600) without a job; the
  next job reloads it after the free-RAM pre-flight.
