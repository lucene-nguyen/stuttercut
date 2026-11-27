# 004 — Windows locks a file you just wrote; snap cuts to frames

Date: 2026-11-15 · Jira: LEARNING-210 · PR: #

## Context
Render writes `<name>_clean.mp4` / `.xml` to a temp file in the user's Videos folder and renames
it into place on success, so a failed render never leaves a half-written file.

## What went wrong / surprised me
1. The second c001 render (`--approve all --format both`) failed at the XML rename:
   `PermissionError: [WinError 32] The process cannot access the file because it is being used
   by another process: '...\.c001_clean.part.xml'`. The cleanup `unlink` hit the same lock, so
   the `.part.xml` stayed behind, and the MP4 of the same job was already written. The first
   render, seconds earlier, had worked.
2. While planning: trimming video at arbitrary times rounds each segment to whole frames but the
   audio is cut to the sample, so each join can shift A/V by up to a frame, and c001 has ~48
   joins.

## What I learned
1. Something on Windows (most likely Defender real-time scanning or the search indexer, both
   watch the Videos folder) opens a freshly written file for a moment. Rename and delete right
   after the write can then fail. Fix: `media/render.py` `move_into_place` and `discard` retry
   on `PermissionError` (20 × 0.1 s); a delete that still fails is logged, never raised over the
   real error.
2. (Since lesson 006: cut edges snap to the nearest frame, and padding moves into silence.)
   Snap every keep-segment to the source frame grid (outward, so the 40 ms padding is never
   eaten) and both streams hold the same time per segment: no drift however many joins.

## Evidence
- `tests/integration/test_render.py::test_output_locked_briefly_after_writing_is_moved_on_retry`
  (rename fails twice, then succeeds; no `.part` file left).
- c001 after both fixes: video 155.933 s / audio 155.933 s (sure, 22 cuts) and 136.367 s /
  136.366 s (all, 48 cuts): under 1 ms apart.

## Next time
On Windows, never assume a file you just closed is yours alone: retry rename/delete briefly.
Cut video only on frame boundaries.
