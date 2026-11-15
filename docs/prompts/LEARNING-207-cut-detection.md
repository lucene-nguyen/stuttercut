# LEARNING-207 — Cut detection (rule engine + VAD + optional diff)

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-207

## Prompt

```text
Task: LEARNING-207 — detect the segments to cut. Read CLAUDE.md, ADR 0002 (Decision 2 + Consequences), lesson 002, docs/spikes/2026-11-asr-models.md and the Test Plan "Accuracy evaluation" section first.
Branch: feature/LEARNING-207-cut-detection. Work without asking unless something fails twice.

Housekeeping first (own commit, LEARNING-206 key): fill the Outcome of docs/prompts/LEARNING-206-worker-transcription.md, set its PR to #3 in docs/prompts/README.md, add this prompt's row.

Must work with the default STUTTERCUT_ASR_PASSES=verbatim. The verbatim-vs-intended diff is an extra source used only when intended words exist.

1. rules/ (pure functions, no I/O, typed): input = verbatim words (+ optional intended words, + VAD voiced segments); output = list[Cut{start, end, reason, source, confidence}], reason in filler | repeat | pause | retake, source in rules | vad | diff.
   - filler: Vietnamese hesitation tokens (ờ, à, ừm, ừ, ơ, …) and CrisperWhisper non-lexical tokens (find out which ones it actually emits on c001 and list them in the module); configurable list. Context rule so a meaningful "à"/"ừ" is not cut (e.g. sentence-initial answer particles followed by content) — keep it simple and documented, the human review is the safety net.
   - repeat: immediate repeats of 1–3 word n-grams (case/diacritics-normalised); keep the LAST occurrence, cut the earlier ones.
   - pause: gap between words > STUTTERCUT_PAUSE_MIN_MS (600); cut the middle, keep STUTTERCUT_PAUSE_KEEP_MS (150) on each side; confirm with VAD that the gap is really silent.
   - retake (simple): a phrase of >= 2 words that restarts with the same opening within N seconds; LLM retakes come in LEARNING-208.
   - vad: voiced segments (silero-vad) of 150–1200 ms not covered by any word (±80 ms) -> candidate filler with lower confidence.
   - diff (only if intended exists): words in verbatim not aligned to intended -> typed by the rules above, source=diff.
   - merge overlapping/adjacent cuts (gap < 50 ms), never cut inside a kept word.
   All thresholds in config.py with .env overrides; update .env.example.
2. storage: CUT table (job_id, start, end, reason, source, confidence, kept=false) + migration; repository functions.
3. worker: new step detect (span "detect"): load words, run VAD on the job's audio, run rules, store cuts, job transcribed -> ready_for_review. Re-running detect replaces previous non-kept cuts.
4. CLI: "python -m stuttercut.worker.cli <video>" now also prints cut counts per reason/source and the detect timing. Never print transcript text.
5. Evaluation of the detector (not the ASR): extend eval so "python -m eval.score_cuts" compares stored/produced cuts with eval/labels/<clip>.cuts.json: precision, recall, F1 per reason and overall (type must match, boundary tolerance 150 ms), mean boundary error, and a breakdown by source (rules / vad / diff). Works on whatever clips have labels; prints which clips were skipped.
6. Tests: property tests (hypothesis) for repeat detection and cut merging; unit tests per rule incl. the meaningful-"à" case; worker integration test with FakeTranscriber + synthetic audio; rules coverage > 80%.
7. Docs: update the design doc references in docs/README.md only if paths changed; add a lesson if something surprising comes up.

Out of scope: LLM retakes (208), render (210), API/UI.

Run lint, mypy, pytest. Then run the CLI on c001 (default verbatim) and, if eval/labels/c001.cuts.json exists, eval.score_cuts on it; report cut counts, detect time and the scores. Commit in small Conventional Commits with LEARNING-207, push, open the PR with gh, watch CI until green, do not merge.
```

## Outcome

PR: https://github.com/lucene-nguyen/stuttercut/pull/4 (merged 2026-11-14).

**Worked well**
- Rule engine as pure functions: 100% coverage, hypothesis properties for repeats and merging; detect step 2.2 s on c001.
- Works on verbatim only; diff and VAD are optional sources; user-kept cuts survive re-runs.
- c001 (GPU idle): transcribe 81.1 s, 48 cuts (filler 33, pause 3, repeat 5, retake 7).

**Had to be corrected or deviated from the prompt**
- CrisperWhisper writes Vietnamese hesitations as `[UH]`/`[UM]`, not "ờ"/"ừm"; the spike's filler counts were wrong for it (correction added to the spike report).
- silero VAD at 0.5 heard the noisy laptop mic as speech (153/161 s), so no pause survived; default 0.8, provisional.
- The simple retake rule flagged common phrases; now needs a hesitation before the restart (19 → 7).
- Importing silero sets torch to 1 thread; fixed, but measured no cost on CUDA.
- A game on the same GPU made two timing runs useless (232–267 s); re-measured with the GPU idle.
- No labelled clip yet, so `eval.score_cuts` had nothing to score ([lesson 003](../lessons/003-check-what-the-model-really-writes.md)).

**Next time**
- Label at least c001 before tuning thresholds; check `nvidia-smi` before timing.
