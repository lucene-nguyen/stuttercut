# 001 — One GPU, two CUDA versions: torch vs CTranslate2

Date: 2026-11-14 · Jira: LEARNING-205 · PR: #

## Context
Running the ASR spike on the Windows dev laptop (RTX 4060, driver 591.66, "CUDA Version: 13.1").
CrisperWhisper and PhoWhisper run on PyTorch; the faster-whisper baseline runs on CTranslate2.

## What went wrong / surprised me
1. `pip install -e "backend[dev,eval]"` on Windows installs **`torch 2.15.0+cpu`**:
   `torch.cuda.is_available()` is `False` on a GPU machine. No error, just a silent CPU run.
2. After installing the CUDA build (`+cu132`), torch worked on the GPU, but CTranslate2 4.9
   loads **CUDA 12** libraries (`cublas64_12.dll`, cuDNN 9). The CUDA 13 torch wheel does not
   ship them, so faster-whisper on `cuda` cannot load cuBLAS.
3. Downloading the 2.1 GB CUDA wheel with `uv pip install --index-url ...` failed twice
   (30 s timeout, then `connection reset`) and has no resume.

## What I learned
- On Windows, always install torch from the CUDA index and check
  `torch.__version__` ends in `+cuXXX`. `run_spike` now prints the device it picked.
- Each GPU library brings its own CUDA runtime. Install `nvidia-cublas-cu12` and
  `nvidia-cudnn-cu12==9.*` for CTranslate2, and add their `bin` folders with
  `os.add_dll_directory` **and** `PATH` (CTranslate2 uses a plain `LoadLibrary`) before
  loading the model. Done in `eval/asr_runners/whisper_baseline.py`.
- For big wheels on a flaky network: `curl -fL -C - --retry 10 --retry-all-errors`, check the
  sha256 from the index page, then `pip install <file>`.

## Evidence
```text
$ strings .venv/Lib/site-packages/ctranslate2/ctranslate2.dll | grep -o "cublas64_[0-9]*.dll"
cublas64_12.dll
$ python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
2.15.0+cpu False            # before
2.15.0+cu132 True           # after installing from the cu132 wheel
$ python -m eval.run_spike --models whisper_baseline --size whisper_baseline=tiny --clips c001
[whisper_baseline] tiny on cuda, loaded in 2.63s
```

## Next time
Before a GPU run, check every backend's CUDA needs (torch *and* CTranslate2) and print the
device each model really uses; never trust a "fast enough" run as proof it was on the GPU.
