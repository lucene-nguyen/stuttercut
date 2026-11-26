# LEARNING-235 — Resource limits (watchdog, timeouts, idle unload)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-235

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-235 Resource limits: 1 job at a time, free-RAM pre-flight (turbo fallback / clear error), watchdog in the API process sampling worker RSS/CPU every 1 s → terminate+kill over limit and respawn, per-step timeouts scaled to clip length, model unload after idle, thread caps, all thresholds in config; fault-injection tests for RSS over limit, timeout, worker kill -9, API restart during review.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/10 (merged 2026-11-26, squash `a898243`).

**Worked well**
- Fault injection through the fixture file (`_allocate_mb`, `_sleep_s`) reaches the spawned worker, so the watchdog is tested end to end on all three OSes (7 tests, green on the first CI run).
- One recovery path (fail what ran, queue what waits) serves both the respawn and an API restart.

**Had to be corrected or deviated from the prompt**
- A killed worker can leave the multiprocessing queue broken: each respawn gets a new queue and re-queues from SQLite.
- Failure reasons are the error text (`resource limit: …`, `timeout: …`), with `failed_step` = the running step.
- The RAM pre-flight now also runs before every reload (after idle or LLM unload).

**Next time**
- Keep SQLite as the source of truth for waiting work; the queue is only a doorbell.
