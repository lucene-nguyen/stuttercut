# 0005 — Clean preview with Web Audio, plan endpoint as single source of truth

- **Status:** Accepted
- **Date:** 2026-11-27
- **Jira:** LEARNING-209 (follow-up)

## Context

The Review screen's "clean version" preview skipped cuts by seeking the `<video>` on
`timeupdate`, which browsers fire about 4 times a second. The first 100–250 ms of every cut was
heard (c001 at 00:51: the start of the abandoned "Mọi người…" plays), while the rendered MP4 is
clean. The preview also did not know the render's padding, merging and frame snapping, so even a
perfect skip would not have matched the MP4. Cut edges could only follow word edges.

## Decision

1. **One plan.** `worker.pipeline.job_plan()` turns the approved, not-kept cuts into
   keep-segments (padding, merging, minimum segment, frame snapping: `media.render.plan`). Render
   uses it, `GET /api/jobs/{id}/plan` returns it
   (`{keep_segments: [{start_s, end_s}], fade_ms, duration_s}`), and the saved time comes from
   it. A hypothesis test checks that the endpoint and render see identical segments.
2. **Web Audio is the clock.** The browser decodes a 48 kHz mono WAV of the source
   (`GET /api/jobs/{id}/preview-audio`, made by the worker's preview step, or on first use for
   older jobs) into an `AudioBuffer`. Clean mode schedules each keep-segment with
   `AudioBufferSourceNode.start(when, offset, duration)` back to back on the `AudioContext`
   clock, with the render's 10 ms fades at the joins (gain ramps). The video is muted and follows
   the audio: it is seeked at each segment start and whenever it drifts more than 80 ms.
   Seeking inside a cut snaps to the next keep-segment. Every decision or edge edit re-fetches the
   plan and reschedules from the current position.
3. **Edges finer than words.** `PATCH /api/jobs/{id}/cuts/{cut_id} {start_s, end_s}` (0 ≤ start <
   end ≤ duration, ≥ 20 ms) moves a cut and approves it. The cut keeps its `orig_start_s` /
   `orig_end_s` (for eval and Reset) and flags `start_edited` / `end_edited`. An edited edge gets
   **no padding**; unedited edges keep `STUTTERCUT_CUT_PADDING_MS`. Keep-segments still snap
   outward to whole frames, so an edited edge can move by up to one frame (33 ms at 30 fps) toward
   keeping more: A/V sync wins over 10 ms precision.

## Consequences

- What you hear in clean mode is what the MP4 will contain, segment for segment.
- The preview needs a decoded WAV in memory: about 17 MB for 3 minutes (48 kHz, 16-bit, mono)
  on disk and roughly 35 MB as a float `AudioBuffer`. Its size shows in the Diagnostics trace.
- Safari (the target on the Mac) starts an `AudioContext` suspended: it is created and resumed
  only inside a click or key press. Not tested on Safari in CI (Chromium only); checked by hand
  in the v1 acceptance test.
- The API process makes the preview WAV for jobs created before this change (an audio-only decode,
  about 1 s for a 3-minute clip). New jobs get it from the worker's preview step.
- Edge edits are saved through one queue per cut (at most one PATCH in flight, latest edges
  win, 150 ms debounce); a `/plan` answer older than the last request is ignored; after a failed
  save the cuts are reloaded from the API. The edge editor shows the set edges and the
  effective ones from the plan, because a 10 ms nudge can land on the same frame.
- `eval.score_cuts` scores the detector against its own original edges; `eval.export_reviews`
  writes both the original and the edited edges.
