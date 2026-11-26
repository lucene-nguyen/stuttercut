# LEARNING-204 — v1 batch (209, 228, 229, 235, 233, acceptance test)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-204

## Prompt

```text
Batch mode: finish all remaining LEARNING-204 tasks, then hand me ONE acceptance test. For this batch only, you may merge each PR yourself with "gh pr merge --squash --delete-branch" once CI is green; never merge red. One branch + PR per task, in this order, each starting from updated main. Fill each prompt's Outcome as you go. Stop and ask only if something fails twice or needs a design change.

0. Merge PR #6 (LEARNING-210) now (CI green; I will do the listening check in the final test).
1. LEARNING-209 Review UI ... (docs/prompts/LEARNING-209-review-ui.md)
2. LEARNING-228 Observability ... (LEARNING-228-observability.md)
3. LEARNING-229 Diagnostics screen ... (LEARNING-229-diagnostics-screen.md)
4. LEARNING-235 Resource limits ... (LEARNING-235-resource-limits.md)
5. LEARNING-233 Cross-platform ... (LEARNING-233-cross-platform.md)
6. Write docs/checklists/acceptance-v1.md: one end-to-end test I run once on Windows and once on the Mac (setup from scratch, upload 2 real clips, review with Approve all sure + a few manual toggles + one missed cut, render mp4 + xml, listening checklist, open XML in DaVinci, Diagnostics shows the jobs, kill the worker mid-job and retry, export_reviews + score_cuts). Include expected results and where to record them.

At the end, report per task: PR link, merged commit, tests added, deviations from the spec, and anything I must check by hand.
```

The full text of items 1–5 is in each task's own prompt file.

## Outcome

_Fill in after the PR merges._
