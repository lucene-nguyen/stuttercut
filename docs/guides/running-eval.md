# Running the ASR spike eval

How to run the LEARNING-205 model comparison and turn its output into labels and a summary.
Set up the machine first: [setup-windows.md](setup-windows.md) or [setup-mac.md](setup-mac.md).
Labelling rules: [labelling-golden-clips.md](labelling-golden-clips.md).

Real clips and raw transcripts never enter git. Clips stay in `STUTTERCUT_DATA_DIR`;
`eval/reports/<date>/<model>/` (raw words) and `eval/reports/<date>/compare/` (HTML pages) are
git-ignored. Only `summary.md` / `summary.json` (metrics, no text) may be committed.

Every command below runs from the repo root with the venv active. Paths in the PowerShell
lines use the Windows data folder; adjust to yours.

## The loop

```
put videos in clips/ -> ingest -> run_spike -> compare_html -> prelabel -> fix in Audacity
                                     ^                                           |
                                     +------ score_spike <- convert_audacity <---+
```

## 1. Point the scripts at your data

Set it once in `.env` (read by every eval script; the environment wins if both are set):

```bash
STUTTERCUT_DATA_DIR=C:/work-space/stuttercut-data     # Windows (forward slashes are fine)
STUTTERCUT_DATA_DIR=/Users/<you>/stuttercut-data      # macOS
```

Layout inside it: `clips/` (your videos, any names), `audacity/` (label files), `index.csv`
(written by ingest).

## 2. Register new clips

Copy videos into `clips/` with any file name, then:

```bash
python -m eval.ingest                     # bash and PowerShell
python -m eval.ingest --speaker s02       # clips of another speaker
```

- Each new file gets `clip_id` = first 8 hex chars of its SHA-256, its duration from ffprobe,
  and a deterministic split (~70% `tune`, ~30% `heldout`). A row is appended to
  `eval/manifest.csv`; fill in `mic` and `noise` by hand.
- Files are never renamed or copied. `index.csv` in the data folder maps `clip_id` to the
  original file name.
- A file with the same content as an existing one is refused and reported (exit code 1).
- Files already named after a manifest id (`c001.mp4`) keep that id.

## 3. Transcribe

```bash
python -m eval.run_spike                                  # all clips, all 3 models
python -m eval.run_spike --clips c001                     # one clip
python -m eval.run_spike --models whisper_baseline phowhisper
python -m eval.run_spike --size whisper_baseline=turbo --size crisperwhisper=turbo
python -m eval.run_spike --device cpu                     # force CPU (default: auto)
```

| Model key | Default | `--size` options |
| --- | --- | --- |
| `crisperwhisper` | `nyralabs/CrisperWhisper2.0_large`, verbatim mode, transformers backend | `large`, `turbo`, `medium`, `small`, or a model id |
| `whisper_baseline` | faster-whisper `large-v3` | any faster-whisper alias (`turbo`, `medium`, `small`, ...) or a repo id |
| `phowhisper` | `vinai/PhoWhisper-large`, segment timestamps + word times from CTC forced alignment (`nguyenvulebinh/wav2vec2-base-vietnamese-250h`, ~360 MB download) | `large`, `medium`, `small`, `base`, `tiny`, or a model id |

- `--device auto` picks the GPU if there is one (CUDA on Windows/Linux, MPS on a Mac), else CPU,
  and prints the choice. faster-whisper has no MPS backend, so on a Mac it runs on CPU.
- Each model runs in its own process, so load time and peak RAM are measured per model.
- Output: `eval/reports/<today>/<model>/<clip_id>.json` and `run.json` (hardware, versions).
  Errors go to `<model>/errors.log` and the run continues with the next model.
- At the end it scores every clip that has `eval/labels/<clip_id>.cuts.json` and writes
  `summary.md`. Clips without labels are skipped, so it also works before you have labels.
- Only clip ids, word counts and timings are printed, never transcript text.
- The first run downloads each model from Hugging Face (several GB for the large sizes).

## 4. Compare transcripts

```bash
python -m eval.compare_html                    # newest report
python -m eval.compare_html eval/reports/2026-11-20
```

Prints one `file:///.../compare/<clip_id>.html` link per clip; open it in a browser. You see
the three models side by side:

- yellow = filler word (ờ, à, ừm, ừ), blue = earlier copy of an immediate repeat;
- hover a word for its start time; click it to play the clip from there;
- while it plays, the current word is highlighted in every column, so you can see which
  model's timestamps are off.

## 5. Pre-label, then fix in Audacity

```bash
python -m eval.prelabel c001                   # uses the newest report
python -m eval.prelabel c001 --model phowhisper --force
```

Writes `audacity/c001.prelabel.txt` with:

- `pause`: silences longer than 600 ms below -35 dB (FFmpeg silencedetect), trimmed 150 ms on
  each side as the labelling guide asks;
- `filler?` and `repeat?`: suggestions from the best transcript (by `summary.json` scores if any,
  else CrisperWhisper, then PhoWhisper, then the baseline).

It refuses to overwrite an existing pre-label (it may hold your edits) unless `--force` is given.

In Audacity: open the clip, File > Import > Labels... > `c001.prelabel.txt`. Check every label:
fix its boundaries, delete wrong ones, add what is missing (retakes are never suggested), and
remove the `?` from the ones you keep. Then File > Export > Export Labels as `c001.txt` or as
`<original video name>.txt` in the same `audacity/` folder.

## 6. Convert labels and score

```bash
python -m eval.convert_audacity                # $STUTTERCUT_DATA_DIR/audacity -> eval/labels
python -m eval.score_spike                     # newest report
python -m eval.score_spike eval/reports/2026-11-20 --tolerance 0.10
```

PowerShell, with explicit folders:

```powershell
python -m eval.convert_audacity "C:\work-space\stuttercut-data\audacity" eval\labels
python -m eval.score_spike eval\reports\2026-11-20
```

- Label files can be named after the `clip_id` or the original video; `index.csv` maps them.
- `*.prelabel.txt` files are skipped. Labels still ending in `?` are rejected with their line
  numbers, and nothing is written until every file is valid.

## 7. Read the summary

| Column | Meaning | Good |
| --- | --- | --- |
| Recall filler / repeat / retake | A labelled cut has a transcript word overlapping it (±150 ms) | High |
| Filler-word recall | A labelled filler has a filler word (ờ, à, ừm, ừ) overlapping it. Stricter: the model really wrote the filler | High |
| Halluc. fillers/min | Filler words in the transcript that overlap no label | Low |
| Boundary ms | Mean distance between labelled filler/repeat edges and the matching words' edges (words whose midpoint lies inside the span ±150 ms) | Low (< 100 ms) |
| Pauses in gap | Labelled pauses that no word crosses | ~100% |
| RTF | Wall time / audio time; model load excluded (`load_s` in each clip JSON) | < 1 |
| Peak RSS MB | Highest process RAM seen, model included | Fits a 16 GB Mac |
| Peak VRAM MB (`runs.md`, clip JSON) | Rise in GPU memory used during that model's process (nvidia-smi, CUDA context included); CUDA only | Fits the GPU |

`runs.md` (written by every run, labels or not) has one table per clip: model, device, load
and transcribe time, RTF, peak RAM / VRAM, and how many filler words and immediate repeats each
model wrote. It contains counts only, no transcript text.

Plain recall is generous on purpose (a neighbouring word can "capture" a filler), so read it
together with filler-word recall and boundary error.

Then fill in the results in [`docs/spikes/2026-11-asr-models.md`](../spikes/2026-11-asr-models.md).
