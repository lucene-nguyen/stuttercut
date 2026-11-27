# LEARNING-209 follow-up — Clean preview with Web Audio, cut edge editing

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-209

## Prompt

```text
LEARNING-209 follow-up (new branch fix/LEARNING-209-clean-preview). Save this prompt to docs/prompts/LEARNING-209-followup.md and fill its Outcome at the end.

Problem: the clean preview on the Review screen jumps over cuts on timeupdate (~4 Hz), so the start of a cut is audible (e.g. the retake at 00:51 of c001: "Mọi người..." is heard, but the rendered MP4 is clean). Also, cut edges can only follow word edges.

Scope (decided with the owner):
A. Clean preview with Web Audio: the audio must match the rendered MP4 exactly.
B. Edit cut edges finer than word edges.
Out of scope: time-range cuts with no words (breath, cough), the 480p preview render.

1. Single source of truth for cut planning
   - Extract the render planning (approved, not-kept cuts → keep segments, padding, merging, 10 ms fades) into one pure function used by both render and a new endpoint GET /api/jobs/{id}/plan → {keep_segments:[{start_s,end_s}], fade_ms, duration_s}.
   - pytest: the endpoint and render.py produce identical segments for the same decisions (hypothesis property test).

2. Preview audio
   - On first use, the worker or API makes a preview audio file in the job folder with ffmpeg: 48 kHz mono WAV (not the 16 kHz ASR audio). Serve it with HTTP Range. Reuse it if it already exists. Note the size in Diagnostics.

3. Web Audio player (frontend only)
   - Decode the preview WAV into an AudioBuffer once per job (lazy, on first clean play; show a small loading state).
   - Clean mode: schedule each keep segment with AudioBufferSourceNode.start(when, offset, duration) back to back on the AudioContext clock, with 10 ms gain fades at each join, exactly as in the plan.
   - The video element is muted in clean mode and follows the audio clock: seek it at each segment start; correct drift > 80 ms. The audio is the master.
   - Play/pause/seek/scrub work in clean mode. Seeking inside a cut snaps to the next keep segment.
   - Re-fetch the plan after every decision or edge edit and reschedule from the current position.
   - Clean mode off → normal video playback with its own audio.
   - Safari is the target browser on Mac: create or resume the AudioContext on a user gesture and handle the suspended state.
   - Keep the scheduling and the source↔clean time mapping in pure, unit-tested functions. Remove the old timeupdate skip path.

4. Cut edge editing
   - Selecting a cut (AI or user) shows a waveform strip around it (±1.5 s, drawn from the decoded AudioBuffer) with draggable start/end handles, the start/end times to 10 ms, ±10 ms nudge buttons and "Reset edges".
   - Keys while a cut is focused and focus is not in a text field: Alt+←/→ move start, Shift+←/→ move end, 10 ms per step. Add them to the keyboard hint. Do not change the existing keys (Space/K/X/←/→/Enter).
   - Clicking a point on the strip plays 1 s around it (normal audio) so the edge can be checked by ear.
   - API: PATCH /api/jobs/{id}/cuts/{cut_id} {start_s, end_s}. Validate: 0 ≤ start < end ≤ duration and length ≥ 20 ms. Editing edges approves the cut (decision = cut).
   - DB migration: orig_start_s, orig_end_s (kept for eval and reset), start_edited, end_edited flags.
   - Planning: an edge the user edited gets no padding; unedited edges keep cut_padding_ms. Update the render docs.
   - eval.export_reviews includes original and edited edges.

5. Tests
   - vitest: scheduling (joins, fades, chained cuts, seek inside a cut, rescheduling after an edit), time mapping, edge nudge limits.
   - pytest: PATCH validation, migration, no padding on edited edges, plan == render.
   - One ffmpeg test: render after an edge edit has the expected duration (±1 frame).
   - Playwright with the fake transcriber: select a cut, nudge an edge, check the shown times and the plan request. Toggle clean mode without errors (audio is not checked). axe stays clean.

6. Docs: update docs/design (Review screen, the plan endpoint), add an ADR "Clean preview with Web Audio, plan endpoint as single source of truth", and add a lesson if anything surprising comes up (Safari autoplay and so on).

Commit with LEARNING-209 (Conventional Commits). Open the PR, watch CI with gh pr checks --watch, fix until green. Do not merge: normal review again from now on.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/13 (open for review; not merged by Claude).

**Worked well**
- `job_plan()` is the one place keep-segments come from; a hypothesis test proves `GET /plan` equals what render encodes.
- All scheduling and time mapping are pure functions (`cleanAudio.ts`) with 13 vitest tests; the Web Audio hook only applies them.
- Original edges kept by a SQLite trigger, so every insert path stayed unchanged.

**Had to be corrected or deviated from the prompt**
- Edited edges still snap outward to the frame grid (≤ 1 frame) with the keep-segments: A/V sync over 10 ms precision.
- Clean mode has its own Play/Pause/scrub instead of the native controls (the native ones would play the video's audio).
- The API makes the preview WAV only for jobs from before this change; new jobs get it from the worker.
- axe flagged the play button (visible text vs `aria-label`); the visible text is now the name. A missing favicon caused console 404s in E2E.

**Review of PR #13**
- Rapid nudges raced (overlapping PATCH and /plan, stale snapshot restored on error): saves now go through a per-cut queue (latest wins), /plan answers are sequence-checked, errors reload the cuts.
- The strip shows the effective (frame-snapped) edges next to the set ones.

**Review of PR #13, part 2**
- Render planning had three ordering bugs (touching cuts left scraps, short cuts vanished, pause cuts double-padded). New order: group (silent gaps too), pad outer edges into silence or inward, nearest frame with a one-frame minimum (lesson 006).

**Not checked in CI**
- Listening (clean preview vs MP4, c001 00:51) and Safari: acceptance test step C.
