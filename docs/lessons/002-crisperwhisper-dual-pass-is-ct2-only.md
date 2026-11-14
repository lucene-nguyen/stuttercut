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
- The `Transcriber` interface hides it: `CrisperWhisperTranscriber.transcribe_dual` calls the
  library's `transcribe_dual` on `STUTTERCUT_ASR_BACKEND=ct2` and two `transcribe` passes on
  `transformers` (default, works on MPS).

## Evidence
```text
$ python -m stuttercut.worker.cli c001.mp4
model nyralabs/CrisperWhisper2.0_large on cuda, loaded in 14.1 s
  extract_audio     0.26 s  ok
  transcribe      149.06 s  ok
words verbatim 746, intended 675
peak RSS 7809 MB, peak VRAM 7180 MB (torch reserved)
```

## Next time
Measure the full step on the target device before fixing a timeout. Open for LEARNING-235: the
3 min transcribe timeout leaves little room for two passes on MPS; measure on the Mac, then
either raise the timeout, use `turbo` for the intended pass, or run ct2 on CPU for `dual`.
