# Spike: verbatim ASR models on Vietnamese stuttered clips

Date: 2026-11 · Jira: [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205) · Time box: — · Status: **tooling ready, waiting for labelled clips**

## Question

Which locally runnable ASR model keeps Vietnamese disfluencies (fillers, repeats, retakes) in
the transcript, with word timestamps accurate enough to cut on, and fits a 16 GB Apple Silicon Mac?

## Options compared

| Option | Version | Notes |
| --- | --- | --- |
| CrisperWhisper 2.0 | `nyralabs/CrisperWhisper2.0_large` (also turbo / medium / small); `crisperwhisper` 2.1.0, transformers backend, `mode="verbatim"` | Trained for verbatim output. v1 (`nyrahealth/CrisperWhisper`) was English/German only and is superseded. The 2.0 card says verbatim mode works "across most languages Whisper supports"; Vietnamese is not confirmed. |
| Whisper baseline | faster-whisper 1.2.1, `large-v3` (or `turbo`) | Standard Whisper, which tends to clean up disfluencies. Reference point. CTranslate2 has no MPS backend, so it runs on CPU on the Mac. |
| PhoWhisper | `vinai/PhoWhisper-large` (tiny to large) via the transformers pipeline | Vietnamese fine-tune of Whisper (844 h). Its generation config includes `alignment_heads`, so word timestamps work through cross-attention DTW. |

### Licenses

| Model | License | Commercial use | Source |
| --- | --- | --- | --- |
| CrisperWhisper 2.0 (standard) | Weights: Nyra Health Non-Commercial Research License. Inference code (`crisperwhisper` package): MIT | **No.** A commercial licence is available from Nyra; the "Pro" variants are commercial-licence only | Deprecation notice on <https://huggingface.co/nyrahealth/CrisperWhisper> and <https://github.com/nyrahealth/CrisperWhisper>. To confirm on <https://huggingface.co/nyralabs/CrisperWhisper2.0_large> |
| CrisperWhisper v1 | CC BY-NC 4.0 | No | <https://huggingface.co/nyrahealth/CrisperWhisper> |
| faster-whisper large-v3 | MIT (CTranslate2 conversion); original OpenAI weights Apache-2.0 | Yes | <https://huggingface.co/Systran/faster-whisper-large-v3>, <https://huggingface.co/openai/whisper-large-v3> |
| faster-whisper turbo | MIT | Yes | <https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo> |
| PhoWhisper | BSD-3-Clause | Yes, under standard BSD-3 terms (check the repo LICENSE file) | <https://huggingface.co/vinai/PhoWhisper-large> |

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
- **Hardware:** _fill in from `eval/reports/<date>/run.json`._ Dev machine: Windows 11, AMD
  Ryzen, 32 GB RAM, RTX 4060 Laptop 8 GB. Target: Apple Silicon, 16 GB.

## Results

_Pending: the owner runs `run_spike.py` on the labelled clips and sends `summary.md`._

| Option | Recall overall | Filler-word recall | Halluc. fillers/min | Boundary ms | Pauses in gap | RTF | Peak RAM |
| --- | --- | --- | --- | --- | --- | --- | --- |
| crisperwhisper | | | | | | | |
| whisper_baseline | | | | | | | |
| phowhisper | | | | | | | |

Raw report: `eval/reports/<date>/summary.md` (raw transcripts stay local).

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

## Decision

_Pending results._ Draft rule, to confirm or overturn with the data:

- Choose the model with the best **filler-word recall** and **boundary error** that fits the
  16 GB Mac at RTF < 1.
- If CrisperWhisper 2.0 keeps Vietnamese fillers clearly better than PhoWhisper, accept
  ADR 0002 and record the non-commercial licence. If PhoWhisper is close, prefer it
  (Vietnamese-trained, permissive licence) and supersede ADR 0002.

## Open questions / follow-ups

- Does CrisperWhisper 2.0 `verbatim` mode keep Vietnamese fillers (ờ, ừm), or only English and
  German ones?
- Process RSS does not show all MPS memory; also check Activity Monitor on the Mac.
- If timestamps are too loose, try CrisperWhisper `timing_method="forced_aligner"`
  (English-only today) or a separate Vietnamese forced aligner.
