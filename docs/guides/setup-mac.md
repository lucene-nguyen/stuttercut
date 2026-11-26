# Setup on macOS (Apple Silicon)

The run environment: an Apple Silicon Mac (M1 or later, 16 GB RAM). PyTorch uses the GPU
through **MPS**; FFmpeg encodes with **VideoToolbox** (falls back to libx264 by itself).

> CI (macOS runner) checks the CLI with the fake transcriber, a render with the encoder it finds,
> and `./scripts/start.sh`. A run on a real Mac with the real model is part of the v1 acceptance
> test (`docs/checklists/acceptance-v1.md`).

## 1. Tools

Install [Homebrew](https://brew.sh), then:

```bash
brew install python@3.11 node@22 ffmpeg git
python3.11 --version        # 3.11.x
node --version              # v22.x
ffmpeg -version | head -1   # also installs ffprobe
ffmpeg -hide_banner -encoders | grep videotoolbox   # h264_videotoolbox should be listed
```

## 2. Repository and Python environment

```bash
git clone https://github.com/lucene-nguyen/stuttercut.git
cd stuttercut
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e "backend[dev]"            # app + quality tools (enough with the fake transcriber)
pip install -e "backend[dev,asr]"        # + the real transcriber: CrisperWhisper, torch, silero-vad
pip install -e "backend[dev,eval]"       # only for the ASR spike scripts (eval/)
pre-commit install
cp .env.example .env
```

The first real job downloads CrisperWhisper large (about 3 GB) into `~/.cache/huggingface`.

The default `torch` wheel for macOS arm64 already includes MPS; do not use a CUDA index URL.

Edit `.env`:

```bash
STUTTERCUT_DATA_DIR=/Users/<you>/stuttercut-data    # clips/, audacity/, index.csv; outside the repo
```

For the LLM review (optional), install Ollama and pull the model: see
[local-llm.md](local-llm.md).

## 3. Frontend

```bash
cd frontend && npm install && cd ..
```

## 4. Run the app

```bash
./scripts/start.sh
```

One command: it installs the UI packages if needed, builds the UI when its sources changed,
starts the API (which starts the worker process and serves the UI) and opens
<http://127.0.0.1:8000>. Ctrl+C stops everything. `STUTTERCUT_PORT` picks another port,
`STUTTERCUT_NO_BROWSER=1` skips the browser. For UI work run `uvicorn stuttercut.api.main:app`
and `cd frontend && npm run dev` instead (http://127.0.0.1:5173).

To try the app without the model, set `STUTTERCUT_FAKE_TRANSCRIBER=tests/fixtures/review_clip.json`
in `.env`.

On a 16 GB Mac keep `STUTTERCUT_WORKER_MAX_RSS_GB=12` (default): the watchdog stops a worker
that grows past it, fails that job with "resource limit" and starts a new worker.

## 5. Check

```bash
python -c "import torch; print(torch.__version__, 'mps', torch.backends.mps.is_available())"
python -c "from stuttercut.platform import select_device; print(select_device())"   # mps
ruff check . && mypy backend && pytest
cd frontend && npm run lint && npm test && cd ..
```

`select_device()` should print `mps`. If it prints `cpu`, check that Python is the arm64 build
(`python -c "import platform; print(platform.machine())"` must print `arm64`, not `x86_64`).

## Notes

- faster-whisper (the spike baseline) has no MPS backend and runs on CPU on the Mac.
- If a transformers model fails with "operator ... is not currently implemented for the MPS
  device", run with `PYTORCH_ENABLE_MPS_FALLBACK=1` so that operator falls back to CPU, and
  note it in the spike report.
- Process RSS does not show all MPS (unified) memory. While a model runs, also watch
  Activity Monitor > Memory for the Python process and memory pressure.
