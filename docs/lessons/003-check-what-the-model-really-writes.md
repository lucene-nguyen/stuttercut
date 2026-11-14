# 003 — Check what the model really writes, and what else shares the machine

Date: 2026-11-14 · Jira: LEARNING-207 · PR: #

## Context
Building the cut detector (rules + VAD) on the default verbatim transcript of c001 (161 s,
Vietnamese, laptop mic), CrisperWhisper 2.0 large on an RTX 4060.

## What went wrong / surprised me
1. **CrisperWhisper does not write "ờ"/"ừm" for Vietnamese hesitations.** It writes the
   non-lexical tokens `[UH]` (19 on c001) and `[UM]` (3). The spike counted only ờ/à/ừm/ừ, so
   it reported 1 filler for CrisperWhisper and concluded "no model writes fillers"; the
   detector and the Audacity pre-labels would have missed all 22.
2. **Importing `silero_vad` calls `torch.set_num_threads(1)`** for the whole process
   (`silero_vad/model.py`, line 3), so every later torch CPU op in the worker runs on one thread.
3. **silero's default threshold (0.5) hears a noisy laptop mic as speech**: 153 of 161 s on c001
   were "voiced", every word gap held 0.2–3 s of "speech", and the pause rule (gap confirmed
   silent by VAD) never fired.
4. **The simple retake rule fired on ordinary phrases**: 19 candidates on c001, 12 of them with
   no pause or filler before the "restart" — just a two-word phrase recurring within 4 s.
5. **Timings were confounded by a game using the same GPU** (73% GPU busy before the run):
   transcribe took 232–267 s instead of 79 s, which I first blamed on point 2.

## What I learned
- Count the model's real output tokens on a real clip before writing rules or metrics; the
  filler list now lives once in `RulesConfig.filler_tokens` and `eval/` imports it.
- Treat library imports as possibly global side effects; `SileroVad` restores the thread count.
- A VAD threshold is a property of the microphone, not a constant: default 0.8 for now,
  provisional until labelled clips (STUTTERCUT_VAD_THRESHOLD).
- A retake now needs a hesitation (filler or >= 300 ms silence) right before the restart.
- Before any timing, check `nvidia-smi` for other GPU users.

## Evidence
c001, detect only on stored words (counts per reason; no labels yet, so no accuracy):

| Setting | filler | pause | repeat | retake | from VAD |
| --- | ---: | ---: | ---: | ---: | ---: |
| no VAD | 13 | 5 | 4 | 16 | 0 |
| VAD 0.5 | 38 | 0 | 4 | 16 | 25 |
| VAD 0.8 | 32 | 3 | 4 | 16 | 19 |
| VAD 0.8 + retake hesitation (new default) | 33 | 3 | 5 | 7 | 19 |

## Next time
Label c001 first (`eval.prelabel` now suggests `[UH]`/`[UM]`), then tune thresholds on the
`tune` clips with `eval.score_cuts` instead of on counts.
