# LEARNING-210 — Render the clean video and export FCP XML

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-210

## Prompt

```text
Task: LEARNING-210 — turn approved cuts into a clean video (and/or an editor timeline). Read CLAUDE.md, the design doc sequence "Review, approve and render", the Test Plan rows for render (FFmpeg exit, encoder fallback, disk full, listening checklist) and docs/checklists/listening-check.md first.
Branch: feature/LEARNING-210-render. Work without asking unless something fails twice.

Housekeeping first (own commit, LEARNING-208 key): fill the Outcome of docs/prompts/LEARNING-208-llm-review.md, set its PR to #5 in docs/prompts/README.md, add this prompt's row.

There is no review UI yet (LEARNING-209), so approval is a CLI choice for now.

1. Cut selection: render uses cuts with kept=false. CLI "--approve sure|all|none" marks which cuts count as approved before rendering ("sure" = only the sure tier, default; "all"; "none" = render as-is for a baseline). Store the approval on CUT so the review UI can reuse it later.
2. media/render.py (pure planning + thin FFmpeg layer):
   - invert approved cuts into keep-segments over the source duration; shrink each cut by STUTTERCUT_CUT_PADDING_MS (default 40) on both sides so no syllable is clipped; drop keep-segments shorter than 80 ms; merge cuts closer than 50 ms.
   - one FFmpeg filter_complex with trim/atrim + concat (frame-accurate, re-encode); a short audio fade out/in at every join (STUTTERCUT_JOIN_FADE_MS, default 10) to avoid clicks.
   - encoder by platform: h264_videotoolbox (Mac) -> h264_nvenc (NVIDIA) -> libx264, chosen at runtime by probing ffmpeg -encoders and a 1-frame test; overridable in config; keep source resolution and frame rate; AAC audio.
   - output to STUTTERCUT_OUTPUT_DIR (default platformdirs user videos dir / StutterCut) as "<source stem>_clean.mp4"; never overwrite: add a numeric suffix. Write to a temp file and move on success; delete partial output on failure.
   - capture FFmpeg stderr; on failure raise a typed error with the step and stderr tail.
3. media/fcpxml.py: export an FCP7 XML (xmeml v5) timeline with one clipitem per keep-segment referencing the original file, no re-encode, so it opens in DaVinci Resolve / Premiere. Same output naming (.xml).
4. Worker: step render (span "render") for formats mp4 | xml | both; job ready_for_review -> rendering -> done (store output paths) or failed with failed_step=render. Re-render allowed from done.
5. CLI: "python -m stuttercut.worker.cli render <job_id|latest> --approve sure --format both" prints: approved cut count, removed seconds, output duration, encoder used, render time, output path(s). Never print transcript text.
6. Tests (synthetic media from the lavfi fixture, no real clips):
   - planning: property tests for cut inversion, padding, merging, minimum segment length;
   - render: output duration == source - removed (±1 frame), audio and video stream durations within 1 frame of each other (A/V sync), no output on failure, no overwrite;
   - encoder fallback: forced unavailable hardware encoder falls back to libx264;
   - XML: parses, clip in/out points match the plan, references the source path.
7. Docs: update the "Common commands" in CLAUDE.md and docs/guides/running-eval.md if relevant; add a lesson if something surprising comes up.

Out of scope: UI (209), watchdog/timeouts (235).

Run lint, mypy, pytest. Then render c001 twice with --approve sure and --approve all, both mp4 and xml, and report for each: approved cuts, removed seconds, output duration, encoder, render time. Put the two output paths in the report so I can do the listening checklist. Commit in small Conventional Commits with LEARNING-210, push, open the PR with gh, watch CI until green, do not merge.
```

## Outcome

_Fill in after the PR merges._
