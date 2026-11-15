# Setup on Windows

The development environment: Windows 11, optional NVIDIA GPU. Commands are for PowerShell
unless marked otherwise. Everything also works on CPU only; it is just slower.

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

```powershell
git clone https://github.com/lucene-nguyen/stuttercut.git
cd stuttercut
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e "backend[dev]"            # app + quality tools
pip install -e "backend[dev,eval]"       # + ASR spike models (torch, transformers, ...)
pre-commit install
Copy-Item .env.example .env
```

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

## 5. Check

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
- Paths with spaces or Vietnamese characters are fine; quote them in PowerShell.
