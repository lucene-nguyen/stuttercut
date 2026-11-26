# LEARNING-235 — Resource limits (watchdog, timeouts, idle unload)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-235

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-235 Resource limits: 1 job at a time, free-RAM pre-flight (turbo fallback / clear error), watchdog in the API process sampling worker RSS/CPU every 1 s → terminate+kill over limit and respawn, per-step timeouts scaled to clip length, model unload after idle, thread caps, all thresholds in config; fault-injection tests for RSS over limit, timeout, worker kill -9, API restart during review.
```

## Outcome

_Fill in after the PR merges._
