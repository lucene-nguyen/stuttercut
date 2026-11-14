# Running the ASR spike eval

How to run the LEARNING-205 model comparison on your golden clips and produce the summary.
Read [labelling-golden-clips.md](labelling-golden-clips.md) first; this guide starts once clips
are recorded and labelled.

Real clips and raw transcripts never enter the repo: clips stay in `$STUTTERCUT_DATA_DIR`, and
`eval/reports/<date>/<model>/` (raw words) is git-ignored. Only `summary.md` / `summary.json`
(metrics, no text) are committed.

## 1. Install

```bash
. .venv/bin/activate                       # Windows: .venv\Scripts\Activate.ps1
pip install -e "backend[dev,eval]"
```

GPU builds of PyTorch:

- **macOS (Apple Silicon):** the default `torch` wheel already supports MPS. Nothing extra.
- **Windows/Linux with NVIDIA:** the default Windows wheel is CPU-only. Install the CUDA build
  that matches your driver from <https://pytorch.org/get-started/locally/>, for example
  `pip install torch --index-url https://download.pytorch.org/whl/cu128`.
  faster-whisper on CUDA also needs cuBLAS and cuDNN 9:
  `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`.

Check the device: `python -c "from stuttercut.platform import select_device; print(select_device())"`.

FFmpeg must be on `PATH` (`ffmpeg -version`).

## 2. Prepare clips and labels

```bash
export STUTTERCUT_DATA_DIR=~/stuttercut-data     # PowerShell: $env:STUTTERCUT_DATA_DIR = "C:\work-space\stuttercut-data"
python -m eval.convert_audacity "$STUTTERCUT_DATA_DIR/audacity" eval/labels
```

- Media files are `$STUTTERCUT_DATA_DIR/clips/<clip_id>.<ext>` (any format FFmpeg reads). The
  file name must equal the `clip_id` in `eval/manifest.csv`.
- `eval/manifest.csv` must list every clip. The loader rejects bad rows with line numbers.
- The converter writes nothing if any label file is invalid, and reports every bad line.

## 3. Transcribe

```bash
python -m eval.run_spike                                  # all clips, all 3 models, default sizes
python -m eval.run_spike --models whisper_baseline --clips c001 c002
python -m eval.run_spike --size whisper_baseline=turbo --size phowhisper=medium
python -m eval.run_spike --device cpu                     # force a device (default: mps > cuda > cpu)
```

| Model key | Default | `--size` options |
| --- | --- | --- |
| `crisperwhisper` | `nyralabs/CrisperWhisper2.0_large`, verbatim mode, transformers backend | `large`, `turbo`, `medium`, `small`, or a model id |
| `whisper_baseline` | faster-whisper `large-v3` | any faster-whisper alias (`turbo`, `medium`, `small`, ...) or a repo id |
| `phowhisper` | `vinai/PhoWhisper-large` | `large`, `medium`, `small`, `base`, `tiny`, or a model id |

- The first run downloads each model from Hugging Face (several GB for the large sizes).
- Each model runs in its own process, so load time and peak RSS are measured per model.
- Output: `eval/reports/<today>/<model>/<clip_id>.json` plus `run.json` (hardware, versions).
- Failures go to `eval/reports/<today>/<model>/errors.log` and the run continues with the next
  model; the exit code is 1 if anything failed.
- Only clip ids, word counts and real-time factors are printed, never transcript text.

## 4. Score

```bash
python -m eval.score_spike eval/reports/<date>
python -m eval.score_spike eval/reports/<date> --tolerance 0.10    # stricter matching
```

Writes `eval/reports/<date>/summary.md` and `summary.json`. Clips without a label file are
listed as `unlabelled_clips` in the JSON and not scored.

## 5. Read the summary

| Column | Meaning | Good |
| --- | --- | --- |
| Recall filler / repeat / retake | A labelled cut has a transcript word overlapping it (±150 ms) | High |
| Filler-word recall | A labelled filler has a filler word (ờ, à, ừm, ừ) overlapping it. Stricter: shows the model really wrote the filler | High |
| Halluc. fillers/min | Filler words in the transcript that overlap no label | Low |
| Boundary ms | Mean distance between labelled filler/repeat edges and the matching words' edges (words whose midpoint lies inside the span ±150 ms) | Low (< 100 ms) |
| Pauses in gap | Labelled pauses that no word crosses | ~100% |
| RTF | Wall time / audio time; model load is excluded (it is `load_s` in each clip JSON) | < 1 |
| Peak RSS MB | Highest process RSS seen, model included. CUDA GPU memory is **not** included | Fits a 16 GB Mac |

Plain recall is generous on purpose (a neighbouring word can "capture" a filler), so read it
together with filler-word recall and boundary error.

Commit only `summary.md` and `summary.json`, then fill in the results in
[`docs/spikes/2026-11-asr-models.md`](../spikes/2026-11-asr-models.md).
