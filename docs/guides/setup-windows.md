# Setup on Windows

The development environment: Windows 11, optional NVIDIA GPU. Commands are for PowerShell
unless marked otherwise. Everything also works on CPU only; it is just slower.

> **Verified 2026-11-26** on Windows 11 (Python 3.11.9, Node 22.20, FFmpeg 8.1): a fresh
> clone in a folder with a space and Vietnamese letters, steps 1–2 and 4, then
> `scripts\start.ps1` (npm ci + UI build + API in 20 s; `pip install -e "backend[dev]"` took
> 3 min) and upload → Approve all sure → render MP4 + XML with the fake transcriber. The real
> model on this machine: c001 in LEARNING-206 to 210.

## 1. Tools

```powershell
winget install Python.Python.3.11 OpenJS.NodeJS.LTS Git.Git Gyan.FFmpeg
# or with Chocolatey: choco install python311 nodejs-lts git ffmpeg
```

Open a new terminal, then check:

```powershell
py -3.11 --version          # 3.11.x
node --version              # v22.x
ffmpeg -version             # first line shows the version; ffprobe comes with it
```

## 2. Repository and Python environment

Clone into a folder whose **path has only ASCII letters** (e.g. `C:\work-space\stuttercut`).
Python 3.11 reads the editable install's `.pth` file in the Windows code page, so a path with
Vietnamese letters makes `stuttercut` unimportable for pytest and the CLI
([lesson 005](../lessons/005-python-311-pth-files-are-not-utf8-on-windows.md)). The start
script works around it, the tools do not. Video files and the data folder may use any name.

```powershell
git clone https://github.com/lucene-nguyen/stuttercut.git
cd stuttercut
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e "backend[dev]"            # app + quality tools (enough with the fake transcriber)
pip install -e "backend[dev,asr]"        # + the real transcriber: CrisperWhisper, torch, silero-vad
pip install -e "backend[dev,eval]"       # only for the ASR spike scripts (eval/)
pre-commit install
Copy-Item .env.example .env
```

The first real job downloads CrisperWhisper large (about 3 GB) into the Hugging Face cache
(`%USERPROFILE%\.cache\huggingface`); later jobs load it from there.

Edit `.env` (forward slashes avoid escaping problems):

```
STUTTERCUT_DATA_DIR=C:/work-space/stuttercut-data
```

For the LLM review (optional), install Ollama and pull the model: see
[local-llm.md](local-llm.md).

Git converts line endings for you; the repo's `.gitattributes` keeps LF in the repository.

## 3. NVIDIA GPU (optional)

The `torch` wheel that pip installs by default on Windows is **CPU-only**. To use an NVIDIA GPU:

1. Update the NVIDIA driver. `nvidia-smi` shows the highest CUDA version the driver supports
   (top right, "CUDA Version"). No CUDA Toolkit install is needed; the wheels bring their own
   CUDA libraries.
2. Pick the PyTorch build for that CUDA major version on
   <https://pytorch.org/get-started/locally/> and reinstall torch from its index. Example that
   works on this project's dev laptop (RTX 4060, driver 591.66, "CUDA Version: 13.1"):

   ```powershell
   pip install --force-reinstall "torch==2.15.0" --index-url https://download.pytorch.org/whl/cu132
   ```

3. faster-whisper (CTranslate2) uses its own CUDA libraries, not torch's: see
   [CTranslate2 on CUDA](#ctranslate2-on-cuda) below.

## 4. Frontend

```powershell
cd frontend; npm install; cd ..
```

## 5. Run the app

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

One command: it installs the UI packages if needed, builds the UI when its sources changed,
starts the API (which starts the worker process and serves the UI) and opens
<http://127.0.0.1:8000>. Ctrl+C stops everything. `STUTTERCUT_PORT` picks another port,
`STUTTERCUT_NO_BROWSER=1` skips the browser.

For UI work use two terminals instead: `uvicorn stuttercut.api.main:app` and
`cd frontend; npm run dev` (http://127.0.0.1:5173, reloads on save).

Without the `asr` extra (or to try the app without the model), set
`STUTTERCUT_FAKE_TRANSCRIBER=tests/fixtures/review_clip.json` in `.env`: every video then gets
the same short synthetic transcript.

## 6. Check

```powershell
python -c "import torch; print(torch.__version__, 'cuda', torch.cuda.is_available())"
python -c "from stuttercut.platform import select_device; print(select_device())"   # cuda or cpu
ruff check .; mypy backend; pytest
cd frontend; npm run lint; npm test; cd ..
```

`torch.__version__` ends in `+cpu` for the CPU build and `+cu132` (or similar) for a CUDA build.
To check the GPU really runs work:

```powershell
python -c "import torch; x = torch.ones(2000, 2000, device='cuda'); print((x @ x).sum().item(), torch.cuda.get_device_name(0))"
```

## CTranslate2 on CUDA

faster-whisper runs on CTranslate2, which loads **CUDA 12** cuBLAS (`cublas64_12.dll`) and
**cuDNN 9** at runtime. The CUDA 13 torch build does not provide them, so install the pip
copies into the same venv:

```powershell
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

They land in `.venv\Lib\site-packages\nvidia\cublas\bin` and `...\nvidia\cudnn\bin`. Windows
does not search those folders by itself; the spike's faster-whisper runner
(`eval/asr_runners/whisper_baseline.py`) adds them to the DLL search path and `PATH` before it
loads the model, so nothing else is needed for `python -m eval.run_spike`.

To use faster-whisper on CUDA outside the spike scripts, put the folders on `PATH` for the
session first:

```powershell
$sp = python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
$env:PATH = "$sp\nvidia\cublas\bin;$sp\nvidia\cudnn\bin;$env:PATH"
```

Check:

```powershell
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count(), 'CUDA device(s)')"
python -m eval.run_spike --models whisper_baseline --size whisper_baseline=tiny --clips c001
```

The run prints `device: cuda (...)` and the clip JSON has `"device": "cuda"`. If it fails with
`Library cublas64_12.dll is not found or cannot be loaded`, the two packages above are missing.

On macOS there is nothing to do: faster-whisper runs on CPU there.

## Troubleshooting

- `python -m eval.run_spike` says `device: cpu` on a GPU machine: torch is the `+cpu` build;
  redo step 3.
- The CUDA torch download (about 2 GB) times out or fails with `connection reset`: download
  the wheel with resume, check its sha256 against the `#sha256=` part of the link on
  <https://download.pytorch.org/whl/cu132/torch/>, then install the file:

  ```bash
  curl -fL -C - --retry 10 --retry-all-errors -o torch-2.15.0+cu132-cp311-cp311-win_amd64.whl \
    "https://download.pytorch.org/whl/cu132/torch-2.15.0%2Bcu132-cp311-cp311-win_amd64.whl"
  sha256sum torch-2.15.0+cu132-cp311-cp311-win_amd64.whl
  pip install ./torch-2.15.0+cu132-cp311-cp311-win_amd64.whl
  ```

  (Git Bash; rerun the `curl` line if it stops, it continues where it left off.) See
  [lesson 001](../lessons/001-torch-cuda13-vs-ctranslate2-cuda12.md).
- `Activate.ps1 cannot be loaded`: run the `Set-ExecutionPolicy` line from step 2 once.
- Video and data paths with spaces or Vietnamese characters are fine; quote them in PowerShell.
  The repository path should be ASCII (step 2).
- `No module named 'stuttercut'` right after `pip install -e`: the checkout path has non-ASCII
  letters (step 2). Move the folder, or prefix commands with `$env:PYTHONPATH="$PWDackend";`.
- `[Errno 10048] ... address already in use` from the start script: another app holds port
  8000; `$env:STUTTERCUT_PORT=8010` then start again.
- `ffmpeg is not installed`: open a new terminal after `winget install Gyan.FFmpeg` (PATH is
  read when the terminal starts).
