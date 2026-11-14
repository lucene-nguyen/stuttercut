# LEARNING-205 — Spike: verbatim ASR on Vietnamese stuttered clips

Jira: https://lucenenguyen.atlassian.net/browse/LEARNING-205

## Prompt

```text
Task: LEARNING-205 — spike to choose the ASR model. Read CLAUDE.md, docs/guides/labelling-golden-clips.md and docs/spikes/TEMPLATE.md first.
Branch: spike/LEARNING-205-asr-models. This is evaluation tooling, not app code: keep it under eval/ and do not touch backend/ except shared helpers if clearly needed.

Real clips live outside the repo in $STUTTERCUT_DATA_DIR (clips/, audacity/). Never copy them into the repo or print their content beyond timestamps.

Build:
1. eval/convert_audacity.py: Audacity label .txt (start<TAB>end<TAB>type) -> eval/labels/<clip_id>.cuts.json; validate types (filler, repeat, pause, retake) and that start < end. Unit tests in tests/unit/.
2. eval/manifest.csv with the columns from the guide (empty rows are fine until clips exist) and a loader that validates it.
3. eval/asr_runners/: one small adapter per candidate, same interface transcribe(audio_path) -> list of {word, start, end}:
   - crisperwhisper: CrisperWhisper 2.0, verbatim mode, word timestamps (transformers backend so it runs on CPU/CUDA/MPS)
   - whisper_baseline: faster-whisper large-v3 (or turbo) with word_timestamps=True
   - phowhisper: vinai/PhoWhisper (largest size that runs here) with word timestamps if supported; if not, record that as a finding
   Device via stuttercut.platform (mps -> cuda -> cpu). Model size configurable so it can run on CPU.
4. eval/run_spike.py: for each clip and model, extract 16 kHz mono audio with FFmpeg, transcribe, save the raw words to eval/reports/<date>/<model>/<clip_id>.json, and measure wall time and peak RSS (psutil).
5. Scoring (eval/score_spike.py), per model, per type and overall:
   - Disfluency capture: a labelled filler/repeat/retake counts as captured if the transcript has word(s) overlapping its span (±150 ms); report recall per type.
   - Hallucinated disfluencies: filler-like words (ờ, à, ừm, ừ) in the transcript that overlap no label; report count per minute.
   - Boundary error: mean |start/end offset| in ms between labelled fillers/repeats and the matching words.
   - Pauses: check that labelled pauses fall in gaps between words (word timestamps leave the gap).
   - Speed: real-time factor; peak RAM.
   Write eval/reports/<date>/summary.md and summary.json.
6. Fill docs/spikes/2026-11-asr-models.md from the template with method, results table, and a recommendation. Also record each model's license and whether commercial use is allowed (cite the model card URL).
7. Add docs/guides/running-eval.md with the exact commands.

Dependencies for the spike go in an optional extra "eval" in backend/pyproject.toml, not in the core dependencies.
Unit-test the converter and scoring with tiny synthetic label/transcript fixtures (no models in tests).
When the code is ready but clips are not, stop and tell me; I will run run_spike.py on my clips and send you the summary.
Then open the PR with gh, watch CI, do not merge.
```

## Outcome

_Fill in after the PR merges._
