# LEARNING-228 — Observability (metrics, traces, logs, diagnostics export)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-228

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-228 Observability: finish what 206 started — GET /api/metrics (7 days: jobs, success rate, avg time per step, peak RSS), GET /api/jobs/{id}/trace, GET /api/logs?level=&job=, POST /api/logs (React error boundary), POST /api/diagnostics/export (zip of logs + environment, no transcripts).
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/8 (merged 2026-11-26, squash `1abcbca`).

**Worked well**
- One read-side module (`observability/diagnostics.py`) behind thin routes; metrics, trace, logs and export all built from spans, the job table and the JSON Lines logs.
- The export test proves no transcript word reaches the zip.

**Had to be corrected or deviated from the prompt**
- API and worker both rotated one `app.jsonl`: on Windows a rotation fails while the other process holds the file. Now one file per process (api/worker/app).
- Added `GET /api/diagnostics/environment` for the screen's environment line (not in the design's route list).

**Next time**
- Name log files per process from the start when more than one process logs.
