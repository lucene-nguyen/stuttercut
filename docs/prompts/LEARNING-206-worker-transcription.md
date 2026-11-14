# LEARNING-206 — Worker: audio extraction and transcription

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-206

## Prompt

```text
Task: LEARNING-206 — production transcription path in the worker. Read CLAUDE.md, ADR 0002 (Accepted), ADR 0003, ADR 0004 and docs/spikes/2026-11-asr-models.md first.
Branch: feature/LEARNING-206-worker-transcription. Work without asking unless something fails twice.

Housekeeping first (own commits):
- Fill the "Outcome" section of docs/prompts/LEARNING-205-asr-spike.md and set its PR to #2 in docs/prompts/README.md (LEARNING-205 key). Add this prompt's row.

Scope (backend only, no API routes or UI yet):
1. asr/: a Transcriber protocol: transcribe_dual(audio_path) -> TranscriptPair(verbatim: list[Word], intended: list[Word]), Word = {text, start, end} in seconds.
   - CrisperWhisperTranscriber: CrisperWhisper 2.0, verbatim + intended passes, word timestamps; model loaded once and reused; size from config (large default).
   - FakeTranscriber: returns fixtures from tests/fixtures/*.json, used by all unit/integration tests.
   Reuse what works from eval/asr_runners/crisperwhisper.py, but production code must not import from eval/.
2. platform.py: select_device() (cuda -> mps -> cpu) already exists; add RAM pre-flight with psutil: if free RAM < config.asr.min_free_gb_large, use the turbo size and log WARN; if < config.asr.min_free_gb_any, fail with a clear error.
3. media/: extract_audio(video) -> 16 kHz mono WAV via FFmpeg, ffprobe duration; reject > 3 min or no audio stream with typed errors. Capture FFmpeg stderr on failure.
4. storage/: SQLite schema + migrations for JOB and WORD (columns per the design doc data model; WORD has a `variant` column: verbatim | intended). Paths via platformdirs. Repositories with simple functions, no ORM.
5. observability/: JSON Lines logger (rotating 5 MB x 3) and a span context manager writing SPAN rows (job_id, step, started_at, duration_s, status, error).
6. worker/: a process entrypoint that loads the transcriber once, takes job ids from a multiprocessing queue, runs steps extract_audio -> transcribe, stores words, records spans, sets JOB status (processing -> transcribed, or failed + failed_step). One job at a time.
7. CLI for manual runs: "python -m stuttercut.worker.cli <video>" creates a job, runs it in-process, prints job id, step timings, word counts per variant and peak RSS. Never print transcript text.
8. Config: all thresholds (model size, RAM limits, max duration, log rotation) in config.py with .env overrides; update .env.example.
9. Tests (no real model, no network): unit tests for pre-flight decisions, duration/no-audio validation, schema migrations, span recording, worker happy path and failure path with FakeTranscriber; synthetic media generated at test time by an FFmpeg lavfi fixture in tests/conftest.py (skip cleanly if ffmpeg is missing).
10. Docs: update CLAUDE.md "Common commands" with the CLI; add a lesson in docs/lessons/ if anything surprising comes up.

Out of scope: rule engine / diff (LEARNING-207), LLM (208), API routes and SSE, UI, watchdog (235).

Run lint, mypy, pytest. Then run the CLI once on $STUTTERCUT_DATA_DIR/clips/c001.mp4 on the best device and report timings, word counts and peak RSS/VRAM. Commit in small Conventional Commits with LEARNING-206, push, open the PR with gh, watch CI until green, do not merge.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/3 (merged 2026-11-14).

**Worked well**
- Worker pipeline (extract_audio -> transcribe), SQLite schema + migrations, JSON Lines logs and spans landed in small commits; CI green on 3 OSes.
- Fake transcriber + lavfi media made the worker tests fast and model-free; after review the FFmpeg tests run on CI on all 3 OSes (82 passed, 0 skipped).
- c001 via the CLI on RTX 4060: 746 verbatim words, transcribe 78.8 s (verbatim) / 149.1 s (dual), peak RSS ~7.5–7.8 GB.

**Had to be corrected or deviated from the prompt**
- `transcribe_dual` is ct2-only (no MPS), so dual = two passes on transformers; the intended pass became optional, verbatim by default (review), ADR 0002 amended ([lesson 002](../lessons/002-crisperwhisper-dual-pass-is-ct2-only.md)).
- CI runners had no ffmpeg, so 7 media tests silently skipped until review; now ffmpeg is installed and `STUTTERCUT_REQUIRE_FFMPEG=1` fails instead of skipping.
- New JOB status `transcribed` (end state until detection, LEARNING-207).
- A pre-commit mypy hook sees unstaged files only partly (stash): commit order had to keep each commit type-correct.

**Next time**
- Make expensive model passes opt-in from the start and measure them on the target device.
- Make "skip if tool missing" tests fail in CI by design.
