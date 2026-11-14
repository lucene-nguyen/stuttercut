# Labelling golden clips

How to record and label the clips used to measure accuracy (Test Plan: *Accuracy evaluation*; Jira [LEARNING-205](https://lucenenguyen.atlassian.net/browse/LEARNING-205)).

## 1. Where the files live

Real voices never go into this repo.

```
C:\work-space\stuttercut-data\        # outside the repo; set STUTTERCUT_DATA_DIR to this path
  clips\c001.mp4, c002.mp4, ...       # the recordings
  audacity\c001.txt, ...              # label exports from Audacity
```

In the repo: `eval/manifest.csv` (one row per clip) and `eval/labels/c001.cuts.json` (converted labels).

## 2. Record the clips

- 1–3 minutes each, natural speech on any topic. Do not "perform" stutters; keep the ones that happen.
- Make sure the set contains fillers (ờ, à, ừm, ừ), repeated words, long pauses and at least a few retakes (start a sentence, stop, start again).
- Vary conditions: laptop mic vs headset, quiet room vs some background noise.
- Only record people who agreed in writing that the clip is used for testing. Start with yourself.

## 3. Label in Audacity (free)

1. Open the clip in Audacity (File > Import > Audio works for MP4 if FFmpeg is installed for Audacity).
2. Add a label track: Edit > Labels > Add Label at Selection (Ctrl+B).
3. For each segment that **should be cut**, select it on the waveform and add a label whose text is exactly one type:

| Label | Select | Example |
| --- | --- | --- |
| `filler` | The filler sound only | "ờ", "à", "ừm" used as hesitation |
| `repeat` | The **earlier** copies; keep the last one | "tôi [tôi] sẽ", "[cài] cài Node" |
| `pause` | Silence longer than 600 ms, minus ~150 ms on each side to keep natural breathing room | gap between two sentences while thinking |
| `retake` | The abandoned attempt, from its first word to the moment speech restarts | "[Bài đầu tiên chúng ta sẽ nói về —] Ok, bài đầu tiên là…" |

4. Export: File > Export > Export Labels → `stuttercut-data\audacity\c001.txt`.

## 4. Labelling rules (keep them consistent)

- Do **not** label a word that carries meaning, even if it sounds like a filler ("à, ra vậy" — "à" here is a real word).
- A filler inside a repeat: label both separately.
- Boundaries: start just before the sound begins, end just after it ends; do not include breath of the next word.
- When unsure, leave it unlabelled and note it in the manifest `notes` column.
- Two people label the same 3 clips once; every disagreement becomes a new rule in this section.

## 5. Manifest

`eval/manifest.csv` columns:

```
clip_id,duration_s,speaker_id,mic,noise,split,notes
c001,142,s01,laptop,quiet,tune,
c002,95,s01,headset,noisy,heldout,two retakes near the end
```

- `speaker_id`: anonymous id, never a name.
- `split`: `tune` (~70%, rules may be adjusted on these) or `heldout` (~30%, only measured).

## 6. Convert labels

```bash
python -m eval.convert_audacity "$STUTTERCUT_DATA_DIR/audacity" eval/labels
```

Produces `eval/labels/c001.cuts.json`:

```json
{"clip_id": "c001", "cuts": [{"start": 3.42, "end": 3.81, "type": "filler"}]}
```
