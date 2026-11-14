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

PR: https://github.com/lucene-nguyen/stuttercut/pull/2 (merged 2026-11-14). Decision: [ADR 0002](../adr/0002-crisperwhisper-verbatim-asr.md) Accepted — CrisperWhisper 2.0 large verbatim + verbatim/intended diff + VAD + pause rules; PhoWhisper dropped. Report: [spike](../spikes/2026-11-asr-models.md).

**Worked well**
- Eval tooling (ingest, prelabel, compare pages, runs table) made a 5-clip × 3-model GPU run and a listening check possible in one evening, without labels.
- Each model in its own process gave clean per-model RAM/VRAM numbers; CI green on the first run.
- Raw transcripts and media stayed out of git (only metrics committed).

**Had to be corrected or deviated from the prompt**
- Follow-up prompts grew the scope (ingest, prelabel, compare_html, guides) mid-task.
- Windows: pip installs CPU torch; the CUDA wheel download failed twice (network) and needed curl with resume. CTranslate2 needs CUDA 12 cuBLAS/cuDNN next to CUDA 13 torch ([lesson 001](../lessons/001-torch-cuda13-vs-ctranslate2-cuda12.md)).
- PhoWhisper word timestamps via cross-attention used ~20 GB RAM; replaced by segment timestamps + CTC alignment. The usual WhisperX aligner for Vietnamese had no CTC head.
- Labelled accuracy was not measured; the decision used speed, memory and a listening check. Moved to LEARNING-206/207.
- Python heredocs with `\n` got mangled by the shell several times; writing files with the editor tool is safer.

**Next time**
- Write the decision criteria before running models, and label at least one clip before the first full run.
- Check every backend's device support (MPS, CUDA version) before choosing it.
