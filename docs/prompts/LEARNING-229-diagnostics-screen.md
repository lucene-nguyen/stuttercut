# LEARNING-229 — Diagnostics screen (screen 3)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-229

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-229 Diagnostics screen (screen 3): metrics cards + avg step time bars, job trace waterfall with failed step + stderr + Copy error details, logs table filtered by level, Open log folder, Export diagnostics.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/9 (merged 2026-11-26, squash `3f97aee`).

**Worked well**
- Pure diagnostics logic (waterfall geometry, level counts, copy text) tested in vitest; the screen only renders it.
- E2E covers metrics, trace, logs filter, export download and axe in one flow.

**Had to be corrected or deviated from the prompt**
- E2E helpers raced with the jobs list loading, and Chrome drops a big upload's reply body; jobs are now found by diffing `/api/jobs`.
- Step bars came alphabetical and job times in UTC; now pipeline order and local time.
- The environment line has no ASR device (the API never loads torch); it is in the worker log.

**Next time**
- Find created objects by id from the API, never by counting rows in the UI.
