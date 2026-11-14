# 002 — CrisperWhisper's one-pass verbatim + intended needs CT2, which has no MPS

Date: 2026-11-14 · Jira: LEARNING-206 · PR: #

## Context
ADR 0002 gets cut candidates from the diff between CrisperWhisper's `verbatim` and `intended`
transcripts. The worker needs both for every job, on the Mac (MPS) and on Windows (CUDA).

## What went wrong / surprised me
- `CrisperWhisperModel.transcribe_dual()` (both modes in one decoder pass, shared encoder)
  raises `NotImplementedError: transcribe_dual() requires the ct2 backend.`
- The ct2 backend (CTranslate2) runs on CPU and CUDA only, **not MPS**, the target device.
- With the transformers backend the worker runs two full passes. On c001 (161 s, RTX 4060,
  `large`, fp16): transcribe **149 s** (verbatim alone was 90 s in the spike), RTF 0.93,
  peak RSS 7.8 GB, torch-reserved VRAM 7.2 GB of 8 GB.

## What I learned
- Read the library's source for the exact backend/device matrix before designing around a
  feature; the model card only says "dual" exists.
- Make the expensive pass optional instead of paying for it on every job. After review the
  intended pass became a setting: `STUTTERCUT_ASR_PASSES` = `verbatim` (default) | `dual`.
  `Transcriber.transcribe` returns `intended=None` in verbatim mode; with `dual` it uses the
  library's `transcribe_dual` on `STUTTERCUT_ASR_BACKEND=ct2` and two passes on `transformers`.
  ADR 0002 is amended to match.

## Evidence
c001 (161 s), RTX 4060 Laptop 8 GB, CUDA, CrisperWhisper 2.0 `large`, fp16, transformers backend,
`python -m stuttercut.worker.cli c001.mp4`:

| Passes | Load s | Transcribe s | RTF | Peak RSS MB | Peak VRAM MB (torch reserved) | Words verbatim / intended |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `dual` (two passes) | 14.1 | 149.1 | 0.93 | 7809 | 7180 | 746 / 675 |
| `verbatim` (default) | 12.5 | 78.8 | 0.49 | 7523 | 7180 | 746 / skipped |

Torch keeps its CUDA cache, so reserved VRAM peaks the same in both modes.

## Next time
Measure the full step on the target device before fixing a timeout. Open for LEARNING-207:
does the intended diff find cuts that verbatim words + VAD + rules miss? If not, leave `dual`
off. Open for LEARNING-235: measure both modes on the Mac (MPS) against the 3 min timeout.
