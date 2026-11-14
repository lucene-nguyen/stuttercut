# Setup on macOS (Apple Silicon)

The run environment: an Apple Silicon Mac (M1 or later, 16 GB RAM). PyTorch uses the GPU
through **MPS**; FFmpeg encodes with **VideoToolbox** later in the project.

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
pip install -e "backend[dev]"            # app + quality tools
pip install -e "backend[dev,eval]"       # + ASR spike models (torch, transformers, ...)
pre-commit install
cp .env.example .env
```

The default `torch` wheel for macOS arm64 already includes MPS; do not use a CUDA index URL.

Edit `.env`:

```bash
STUTTERCUT_DATA_DIR=/Users/<you>/stuttercut-data    # clips/, audacity/, index.csv; outside the repo
LLM_API_KEY=
```

## 3. Frontend

```bash
cd frontend && npm install && cd ..
```

## 4. Check

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
