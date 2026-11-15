# 0002 — CrisperWhisper for verbatim ASR

- **Status:** Accepted (2026-11-14, after spike [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205))
- **Date:** 2026-11-14 (proposed in LEARNING-234)
- **Jira:** LEARNING-234, LEARNING-205
- **Evidence:** [spike report](../spikes/2026-11-asr-models.md)

## Context

Detection needs a **verbatim** transcript with accurate **word timestamps**: repeated words,
fillers ("ờ", "ừm") and false starts must appear in the text. Standard Whisper models clean up
disfluencies, so they hide exactly what we want to cut. The model must run locally on Apple
Silicon (`mps`), on CUDA, or on CPU, and fit a 16 GB Mac.

The spike (5 clips, about 11 minutes of speech, no labels yet) showed:

- every candidate wrote very few filler words, so a transcript alone is not enough to find cuts;
- faster-whisper large-v3 gave the most accurate Vietnamese text in a listening check, but drops
  stutters (it cleans fillers and repeats out of the transcript);
- CrisperWhisper 2.0 large in verbatim mode kept the most content (about twice the repeats of
  the baseline) at RTF 0.36–0.62 on an RTX 4060, 7.9 GB RAM, 5.1 GB VRAM;
- PhoWhisper was the slowest and heaviest (RTF up to 1.43, 9.3 GB RAM) and needed a
  non-commercial Vietnamese aligner for word timestamps.

## Decision

1. **ASR:** CrisperWhisper 2.0 **large**, `mode="verbatim"`, with word timestamps, through
   PyTorch on the device chosen at runtime (`mps` → `cuda` → `cpu`). When the RAM pre-flight
   fails (e.g. a 16 GB Mac under pressure), fall back to CrisperWhisper 2.0 **turbo**.
2. **Cut candidates from two transcripts of the same model (optional pass):** with
   `STUTTERCUT_ASR_PASSES=dual`, also run CrisperWhisper in `intended` mode and diff it with
   `verbatim`. Words present in verbatim but not in intended become filler / repeat / retake
   candidates, timed with the verbatim word timestamps. The default is `verbatim` only (one
   pass); see Consequences. *(Amended in LEARNING-206.)*
3. **Acoustic backup:** voiced segments from a VAD that no transcript word covers become
   candidates too (fillers and dropped repeats the model did not write).
4. **Long pauses** come from the rule engine (word gaps and silence), not from the model.
5. **Human review** before render stays the safety net; nothing is cut without approval.
6. **Dropped:** PhoWhisper. faster-whisper stays only as a fast baseline in `eval/`, not in the
   app.

Keep all of this behind a `Transcriber` interface so tests use a fake transcriber with captured
transcripts. Accuracy targets (recall, boundary error) are validated with labelled golden clips
in LEARNING-206 / LEARNING-207; they do not block this decision.

## Consequences

- **The intended pass is optional and off by default.** CrisperWhisper's one-pass
  `transcribe_dual` exists only on the ct2 backend, which has no MPS support, so on the
  transformers backend (the Mac default) `dual` is a second full pass. Measured on c001
  (161 s, RTX 4060, `large`): transcribe 78.8 s verbatim only vs 149.1 s dual — see
  [lesson 002](../lessons/002-crisperwhisper-dual-pass-is-ct2-only.md). `STUTTERCUT_ASR_PASSES`
  = `verbatim` (default) | `dual`; `TranscriptPair.intended` is `None` in verbatim mode.
- Detection (LEARNING-207) must work from verbatim words + VAD gaps + pause rules alone, and use
  the verbatim-vs-intended diff only when `dual` ran; it merges overlapping candidates from all
  sources. Whether `dual` is worth its cost is measured with labelled clips in LEARNING-207.
- Memory: about 8 GB RAM for `large` on the dev machine. It must be measured on the 16 GB Mac
  (MPS, fp16); the RAM pre-flight and the `turbo` fallback are required, not optional.
- Vietnamese support of CrisperWhisper 2.0 is not confirmed by its model card; if the labelled
  eval shows poor recall, revisit this ADR (the `Transcriber` interface keeps a swap local).
- **Licence:** CrisperWhisper 2.0 weights are under the Nyra Health Non-Commercial Research
  License. Accepted because StutterCut is personal / learning use; any commercial use needs a
  licence from Nyra Health or a model swap.
- The model loads only in the worker process.
- **Sharing memory with a local LLM (LEARNING-208):** with the Ollama provider, the worker
  unloads CrisperWhisper before `llm_review` when free RAM is below
  `STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB` (8 GB) and empties the CUDA/MPS cache; the next job loads
  it again (span `load_model`). On a 16 GB Mac the two models never sit in memory together; the
  price is one model load per job. See [docs/guides/local-llm.md](../guides/local-llm.md) for
  measured numbers.
