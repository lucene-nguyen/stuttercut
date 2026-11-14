# Spike: verbatim ASR models on Vietnamese stuttered clips

Date: 2026-11 · Jira: [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205) · Time box: — · Status: **decided** — CrisperWhisper 2.0 large verbatim + verbatim/intended diff + VAD + pause rules ([ADR 0002](../adr/0002-crisperwhisper-verbatim-asr.md))

## Question

Which locally runnable ASR model keeps Vietnamese disfluencies (fillers, repeats, retakes) in
the transcript, with word timestamps accurate enough to cut on, and fits a 16 GB Apple Silicon Mac?

## Options compared

| Option | Version | Notes |
| --- | --- | --- |
| CrisperWhisper 2.0 | `nyralabs/CrisperWhisper2.0_large` (also turbo / medium / small); `crisperwhisper` 2.1.0, transformers backend, `mode="verbatim"` | Trained for verbatim output. v1 (`nyrahealth/CrisperWhisper`) was English/German only and is superseded. The 2.0 card says verbatim mode works "across most languages Whisper supports"; Vietnamese is not confirmed. |
| Whisper baseline | faster-whisper 1.2.1, `large-v3` (or `turbo`) | Standard Whisper, which tends to clean up disfluencies. Reference point. CTranslate2 has no MPS backend, so it runs on CPU on the Mac. |
| PhoWhisper | `vinai/PhoWhisper-large` (tiny to large) via the transformers pipeline: segment timestamps (`return_timestamps=True`, chunk 30 s, batch 1, fp16), words force-aligned with `nguyenvulebinh/wav2vec2-base-vietnamese-250h` (CTC Viterbi, WhisperX-style) | Vietnamese fine-tune of Whisper (844 h). Its config has `alignment_heads`, but word timestamps from cross-attention were far too heavy on long clips; see [Memory issue](#memory-issue-phowhisper-word-timestamps). |

### Licenses

| Model | License | Commercial use | Source |
| --- | --- | --- | --- |
| CrisperWhisper 2.0 (standard) | Weights: Nyra Health Non-Commercial Research License. Inference code (`crisperwhisper` package): MIT | **No.** A commercial licence is available from Nyra; the "Pro" variants are commercial-licence only | Deprecation notice on <https://huggingface.co/nyrahealth/CrisperWhisper> and <https://github.com/nyrahealth/CrisperWhisper>. To confirm on <https://huggingface.co/nyralabs/CrisperWhisper2.0_large> |
| CrisperWhisper v1 | CC BY-NC 4.0 | No | <https://huggingface.co/nyrahealth/CrisperWhisper> |
| faster-whisper large-v3 | MIT (CTranslate2 conversion); original OpenAI weights Apache-2.0 | Yes | <https://huggingface.co/Systran/faster-whisper-large-v3>, <https://huggingface.co/openai/whisper-large-v3> |
| faster-whisper turbo | MIT | Yes | <https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo> |
| PhoWhisper | BSD-3-Clause | Yes, under standard BSD-3 terms (check the repo LICENSE file) | <https://huggingface.co/vinai/PhoWhisper-large> |
| wav2vec2-base-vietnamese-250h (aligner used for PhoWhisper word times) | CC BY-NC 4.0 on the model card; the repo also ships a `CC-BY-NC-SA-4.0.txt` | No | <https://huggingface.co/nguyenvulebinh/wav2vec2-base-vietnamese-250h> |

StutterCut is a personal, local tool today, so a non-commercial licence does not block the
spike. It does block any commercial use of CrisperWhisper without a licence from Nyra.

## Method

- **Data:** golden clips listed in `eval/manifest.csv`, labelled in Audacity following
  [labelling-golden-clips.md](../guides/labelling-golden-clips.md) and converted to
  `eval/labels/*.cuts.json`. Both `tune` and `heldout` clips are measured; nothing is tuned here.
- **Run:** `python -m eval.run_spike`, then `python -m eval.score_spike eval/reports/<date>`
  (see [running-eval.md](../guides/running-eval.md)). Audio is extracted with FFmpeg to 16 kHz
  mono WAV, the language is forced to Vietnamese, and each model runs in its own process.
- **Metrics** (per model, per type and overall; tolerance ±150 ms):
  - disfluency recall: a labelled filler/repeat/retake is overlapped by any transcript word;
  - filler-word recall: a labelled filler is overlapped by a filler word (ờ, à, ừm, ừ). Added
    because plain overlap also counts a neighbouring word as a "capture";
  - hallucinated fillers per minute: filler words that overlap no label;
  - boundary error (ms): mean |start| and |end| offset between labelled fillers/repeats and the
    words whose midpoint falls inside the span;
  - pauses in gap: labelled pauses that no word crosses;
  - real-time factor (wall / audio, model load excluded) and peak process RSS.
- **Hardware:** from `eval/reports/<date>/run.json`. Dev machine: Windows 11, AMD
  Ryzen, 32 GB RAM, RTX 4060 Laptop 8 GB. Target: Apple Silicon, 16 GB.

## Results

Labelled accuracy (recall, boundary error) is not part of this spike: the clips are not labelled
yet, and the decision below did not need it. It moves to LEARNING-206 / 207, using
`eval.prelabel`, `eval.convert_audacity` and `eval.score_spike` built here.

| Model | RTF (5 clips) | Peak RAM | Peak VRAM | Fillers written (total) | Repeats written (total) |
| --- | --- | --- | --- | --- | --- |
| CrisperWhisper 2.0 large, verbatim | 0.36–0.62 | 7.9 GB | 5.1 GB | 1 | 16 |
| faster-whisper large-v3 | 0.11–0.24 | 3.1 GB | 4.5 GB | 1 | 8 |
| PhoWhisper large + wav2vec2 CTC alignment | 0.63–1.43 | 9.3 GB | 6.5 GB | 5 | 13 |

### First full run, before labels (2026-11-14)

5 clips (c001 plus 4 ingested: 633e80af, 5911f3b2, 0ef0e720, 319af07b), all three models at
default size, Windows 11, RTX 4060 Laptop 8 GB, CUDA (torch 2.15.0+cu132, CTranslate2 4.9.0,
transformers 5.23.0). Source: [`eval/reports/2026-11-14/runs.md`](../../eval/reports/2026-11-14/runs.md).
PhoWhisper is attempt 1 below (segments + CTC alignment).

- **Transcribe** = wall time without model load. **RAM** = peak process RSS (per process, so the
  same for every clip of a model). **VRAM** = rise in GPU memory used (nvidia-smi).
- **Fillers** = words ờ, à, ừm, ừ written by the model; **Repeats** = earlier copies of
  immediate repeats. Counts only; without labels they say nothing about accuracy.

| Clip (audio s) | Model | Load s | Transcribe s | RTF | Peak RAM MB | Peak VRAM MB | Words | Fillers | Repeats |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| c001 (160.9) | crisperwhisper | 17.8 | 90.0 | 0.56 | 7943 | 5128 | 746 | 1 | 7 |
| | whisper_baseline | 9.1 | 29.9 | 0.19 | 3118 | 4466 | 692 | 1 | 3 |
| | phowhisper | 13.2 | 229.9 | 1.43 | 9329 | 6471 | 570 | 4 | 8 |
| 633e80af (164.8) | crisperwhisper | 17.8 | 60.0 | 0.36 | 7943 | 5128 | 500 | 0 | 4 |
| | whisper_baseline | 9.1 | 18.1 | 0.11 | 3118 | 4466 | 460 | 0 | 2 |
| | phowhisper | 13.2 | 176.9 | 1.07 | 9329 | 6506 | 617 | 0 | 2 |
| 0ef0e720 (157.8) | crisperwhisper | 17.8 | 58.0 | 0.37 | 7943 | 5128 | 496 | 0 | 5 |
| | whisper_baseline | 9.1 | 18.1 | 0.12 | 3118 | 4502 | 460 | 0 | 3 |
| | phowhisper | 13.2 | 98.8 | 0.63 | 9329 | 6540 | 476 | 1 | 2 |
| 319af07b (41.8) | crisperwhisper | 17.8 | 26.0 | 0.62 | 7943 | 5128 | 257 | 0 | 0 |
| | whisper_baseline | 9.1 | 10.1 | 0.24 | 3118 | 4550 | 249 | 0 | 0 |
| | phowhisper | 13.2 | 40.1 | 0.96 | 9329 | 6540 | 260 | 0 | 1 |
| 5911f3b2 (31.6) | crisperwhisper | 17.8 | 13.8 | 0.44 | 7943 | 5128 | 103 | 0 | 0 |
| | whisper_baseline | 9.1 | 3.9 | 0.12 | 3118 | 4466 | 100 | 0 | 0 |
| | phowhisper | 13.2 | 21.0 | 0.67 | 9329 | 6506 | 100 | 0 | 0 |

> **Correction (LEARNING-207, [lesson 003](../lessons/003-check-what-the-model-really-writes.md)):** the
> "Fillers" column counted only ờ/à/ừm/ừ. CrisperWhisper writes Vietnamese hesitations as
> `[UH]`/`[UM]`: 22 on c001 (19 + 3), not 1. Its filler count below is therefore far too low,
> and "all three models write almost no fillers" does not hold for CrisperWhisper.

What the counts suggest (to be checked against labels):

- All three models write almost no filler words: 6 in total across ~11 minutes of speech,
  4 of them from PhoWhisper in c001. Either these clips have few fillers, or none of the models
  keeps Vietnamese fillers, CrisperWhisper's verbatim mode included. Labels decide which.
- CrisperWhisper writes 5–10% more words and about twice the repeats of the baseline, which
  hints at more verbatim output; it is ~3x slower and uses ~2.5x the RAM.
- PhoWhisper (with alignment) is the slowest and heaviest: RTF up to 1.43 on the long clips and
  9.3 GB RAM on this machine.
- Audio length is the decoded audio stream; for 319af07b the manifest's 44.8 s is the container
  length from ffprobe.

### Smoke test (tooling check, not results)

One 20 s excerpt of an unlabelled clip, Windows 11, CPU, smallest sizes
(`crisperwhisper=small`, `whisper_baseline=tiny`, `phowhisper=tiny`). Says nothing about accuracy.

| Model | Load | RTF | Peak RSS | Output |
| --- | --- | --- | --- | --- |
| CrisperWhisper 2.0 small (fp32, CPU) | 38 s | 0.51 | 4.7 GB | 87 words, 80% with Vietnamese diacritics, timestamps monotonic |
| faster-whisper tiny (int8, CPU) | 2 s | 0.06 | 0.2 GB | 108 words, timestamps monotonic |
| PhoWhisper tiny (fp32, CPU) | 20 s | 0.42 | 1.5 GB | 113 words, timestamps monotonic, 1 zero-length word |

Findings so far:

- All three produce Vietnamese text with word timestamps. PhoWhisper's word timestamps work
  as shipped (its config includes `alignment_heads`).
- CrisperWhisper 2.0 on the transformers backend reports two unused weights
  (`encoder_blank_head.*`, "UNEXPECTED"); harmless for inference.
- CrisperWhisper `small` already peaks at about 4.7 GB RSS in fp32 on CPU. `large` must be
  measured on the 16 GB Mac (fp16 on MPS) before it can be chosen.
- faster-whisper cannot use MPS, so on the Mac the baseline runs on CPU.

### Memory issue: PhoWhisper word timestamps

Windows 11, RTX 4060 Laptop (8 GB VRAM), 32 GB RAM, clip c001 (161 s), `vinai/PhoWhisper-large`
fp16 on CUDA. RAM = peak process RSS; VRAM = rise in GPU memory used (nvidia-smi).

| Attempt | Word timing | Result on c001 | Peak RAM | Peak VRAM | RTF |
| --- | --- | --- | --- | --- | --- |
| 0 | transformers `return_timestamps="word"` (cross-attention DTW) | Finished c001 only, then stopped by hand; GPU memory full, Windows spilled into shared RAM and the page file (C: dropped to ~3 GB free) | 19.8 GB | 6.8 GB (GPU full at 7.8 / 8 GB) | 5.32 |
| 1 | segment timestamps (`return_timestamps=True`, chunk 30 s, batch 1, fp16) + CTC forced alignment with `nguyenvulebinh/wav2vec2-base-vietnamese-250h` | **Works**; 570 words, timestamps monotonic, no zero-length words | 9.6 GB | 6.0 GB | 1.65 |
| 2 | convert to CTranslate2 and run through faster-whisper | Not needed: attempt 1 works | – | – | – |

- Word-level timestamps in the transformers pipeline keep the cross-attentions of every
  generated token for the DTW step; on a 161 s clip that does not fit an 8 GB GPU.
- The first aligner tried, `nguyenvulebinh/wav2vec2-base-vi` (WhisperX's usual choice for
  Vietnamese), is a pretraining checkpoint **without a CTC head** (`lm_head` missing), so it
  cannot align. `wav2vec2-base-vietnamese-250h` is the CTC fine-tune and loads with no missing
  weights.
- Attempt 1 still needs 9.6 GB RAM and runs slower than real time on this GPU, so PhoWhisper is
  the heaviest of the three. On a 16 GB Mac it must be measured before it can be chosen; if it
  is too heavy, attempt 2 (CTranslate2 + faster-whisper) is the next step.

## Listening check (owner, c001)

- faster-whisper large-v3 gives the most accurate Vietnamese text but **drops the stutters**: it
  cleans fillers and repeats out of the transcript.
- All three models write very few fillers even where they are audible, so transcript-only
  detection is not enough; an acoustic signal is needed.

## Decision

Decided by the owner on 2026-11-14 (Jira comment on LEARNING-205); recorded as
[ADR 0002](../adr/0002-crisperwhisper-verbatim-asr.md) (Accepted).

- **ASR:** CrisperWhisper 2.0 **large**, verbatim mode. It keeps the most content, including
  repeats and false starts. On the Mac it runs on MPS; when the RAM pre-flight fails, fall back
  to CrisperWhisper 2.0 **turbo**. Non-commercial licence accepted (personal / learning use).
- **Cut detection:**
  1. verbatim vs intended diff (same model, two modes) gives filler / repeat / retake
     candidates with verbatim timestamps;
  2. VAD voiced segments not covered by any word are a backup for what the model did not write;
  3. the rule engine finds long pauses.
- **Dropped:** PhoWhisper (slow, 9.3 GB RAM, non-commercial aligner needed for word times).
  faster-whisper stays only as a fast baseline in `eval/`.
- **Human review** before render stays the safety net.

Why not wait for labels: the speed, memory and listening results already rule PhoWhisper out
and show that no model alone writes the fillers; the hybrid design does not depend on which
transcript wins. Accuracy targets are validated with labelled clips in LEARNING-206 / 207.

## Open questions / follow-ups

- Measure CrisperWhisper large and turbo on the 16 GB Mac (MPS, fp16): RAM, RTF, and whether
  verbatim mode keeps Vietnamese fillers. Process RSS does not show all MPS memory; also check
  Activity Monitor. (LEARNING-206)
- Does `transcribe_dual` (verbatim + intended in one pass) work on the transformers backend and
  on MPS? (LEARNING-206)
- Risk: word timestamps may stretch over audio the model dropped and hide the VAD gaps; may need
  tighter alignment. Measure with labels. (LEARNING-207)
- Label the 5 clips (`eval.prelabel` + Audacity) and score recall and boundary error for the
  diff + VAD + rules pipeline. (LEARNING-207)
