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

_Fill in after the PR merges._
