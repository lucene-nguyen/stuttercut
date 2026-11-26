# LEARNING-209 — Review UI (Upload & jobs, Review & render)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-209

## Prompt

Part of the batch prompt for LEARNING-204 (2026-11-26): one branch + PR per task, merge when CI is green.

```text
LEARNING-209 Review UI (screens 1–2 of the UI design, dark theme, English labels):
- API (FastAPI, 127.0.0.1): POST /api/jobs (upload, validate ≤3 min), GET /api/jobs, GET /api/jobs/{id} (words + cuts), GET /api/jobs/{id}/events (SSE progress), GET /api/jobs/{id}/preview (480p proxy, HTTP Range), PATCH cut keep/cut, POST cuts:bulk, POST render (mp4|xml|both, folder), POST retry. Worker runs in its own process; one job at a time.
- Upload & jobs screen: drop zone with inline errors, detection options, jobs table with live progress, Review / Show in Finder / failed → View trace + Retry.
- Review screen: video preview, timeline cut markers, transcript with cuts colour-coded by reason, filter by reason, live clean/saved time, cuts grouped sure/unsure, "Approve all sure", keyboard (Space play, K keep, X cut, ←/→ prev/next, Enter render), "Mark missed cut" on a transcript selection, inline render panel with done state.
- Every decision saved (kept/removed/user-added + timestamp); "python -m eval.export_reviews" writes eval/labels/<clip>.cuts.json for eval.score_cuts.
- Tests: API contract tests, vitest for UI logic, Playwright E2E flows with the fake transcriber (upload → review → render; 4-min upload error; toggles survive reload), axe scan with no serious issues.
```

## Outcome

_Fill in after the PR merges._
