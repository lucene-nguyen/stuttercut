"""Run the ASR spike: transcribe every manifest clip with every candidate model.

Usage: python -m eval.run_spike [--models crisperwhisper whisper_baseline phowhisper]
                                [--size whisper_baseline=turbo] [--device auto] [--clips c001]

Clips are read from $STUTTERCUT_DATA_DIR/clips (env or .env) and never copied into the repo.
Writes eval/reports/<date>/<model>/<clip_id>.json (raw words, git-ignored) and run.json.
Each model runs in its own process so its load time and peak RSS are measured alone.
Only clip ids and timings are printed, never transcript text.
"""

import argparse
import json
import multiprocessing as mp
import platform
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from datetime import date
from importlib import metadata
from pathlib import Path

from eval.asr_runners import RUNNER_NAMES, get_loader
from eval.env import REPORTS, data_dir
from eval.ingest import find_media
from eval.manifest import load_manifest
from stuttercut.platform import select_device


def extract_audio(src: Path, dst: Path) -> float:
    """16 kHz mono PCM WAV via FFmpeg; returns duration in seconds."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {src.name}:\n{proc.stderr}")
    with wave.open(str(dst)) as w:
        return w.getnframes() / w.getframerate()


class PeakRss:
    """Samples this process's RSS in a background thread; ``peak_mb`` is the max seen."""

    def __init__(self, interval_s: float = 0.05) -> None:
        import psutil

        self._proc = psutil.Process()
        self.peak = self._proc.memory_info().rss
        threading.Thread(target=self._run, args=(interval_s,), daemon=True).start()

    def _run(self, interval_s: float) -> None:
        while True:
            self.peak = max(self.peak, self._proc.memory_info().rss)
            time.sleep(interval_s)

    @property
    def peak_mb(self) -> float:
        return round(self.peak / 2**20, 1)


def run_model(
    name: str, size: str | None, device: str, items: list[tuple[str, str, float]], out: str
) -> None:
    """Child process: load one model, transcribe every clip, write one JSON per clip."""
    out_dir = Path(out) / name
    out_dir.mkdir(parents=True, exist_ok=True)
    rss = PeakRss()
    t0 = time.perf_counter()
    try:
        runner = get_loader(name)(size, device)
    except Exception:
        (out_dir / "errors.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"[{name}] failed to load, see {out_dir / 'errors.log'}", flush=True)
        sys.exit(1)
    load_s = round(time.perf_counter() - t0, 2)
    print(f"[{name}] {runner.model_id} on {runner.device}, loaded in {load_s}s", flush=True)

    failed = False
    for clip_id, wav, audio_s in items:
        t0 = time.perf_counter()
        try:
            words = runner.transcribe(Path(wav))
        except Exception:
            failed = True
            with (out_dir / "errors.log").open("a", encoding="utf-8") as f:
                f.write(f"--- {clip_id}\n{traceback.format_exc()}\n")
            print(f"[{name}] {clip_id}: FAILED, see errors.log", flush=True)
            continue
        wall_s = round(time.perf_counter() - t0, 2)
        result = {
            "clip_id": clip_id,
            "model": name,
            "model_id": runner.model_id,
            "device": runner.device,
            "word_timestamps": runner.word_timestamps,
            "load_s": load_s,
            "audio_s": round(audio_s, 2),
            "wall_s": wall_s,
            "rtf": round(wall_s / audio_s, 3),
            "peak_rss_mb": rss.peak_mb,
            "words": words,
        }
        (out_dir / f"{clip_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"[{name}] {clip_id}: {len(words)} words, rtf {result['rtf']}", flush=True)
    sys.exit(1 if failed else 0)


def device_name(device: str) -> str:
    if device == "cuda":
        import torch

        return str(torch.cuda.get_device_name(0))
    return platform.processor() or platform.machine()


def _versions() -> dict[str, str]:
    out = {}
    for pkg in ("crisperwhisper", "faster-whisper", "ctranslate2", "torch", "transformers"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, help="default $STUTTERCUT_DATA_DIR (env or .env)")
    parser.add_argument("--models", nargs="+", choices=RUNNER_NAMES, default=list(RUNNER_NAMES))
    parser.add_argument(
        "--size",
        action="append",
        default=[],
        metavar="MODEL=SIZE",
        help="e.g. whisper_baseline=turbo, phowhisper=small, crisperwhisper=turbo",
    )
    parser.add_argument(
        "--device", choices=["auto", "cuda", "mps", "cpu"], default="auto", help="default auto"
    )
    parser.add_argument("--manifest", type=Path, default=None, help="default eval/manifest.csv")
    parser.add_argument("--clips", nargs="+", help="subset of clip ids (default: all)")
    parser.add_argument("--out", type=Path, default=REPORTS / date.today().isoformat())
    args = parser.parse_args()

    root = data_dir(args.data_dir)
    sizes = dict(s.split("=", 1) for s in args.size)
    if unknown := set(sizes) - set(RUNNER_NAMES):
        parser.error(f"unknown model in --size: {sorted(unknown)}")
    device = select_device() if args.device == "auto" else args.device
    print(f"device: {device} ({device_name(device)}){' [auto]' if args.device == 'auto' else ''}")

    clips = load_manifest(args.manifest) if args.manifest else load_manifest()
    if args.clips:
        clips = [c for c in clips if c["clip_id"] in set(args.clips)]
    if not clips:
        parser.error("no clips to run: fill eval/manifest.csv (or check --clips)")
    sources = {c["clip_id"]: find_media(root, c["clip_id"]) for c in clips}

    args.out.mkdir(parents=True, exist_ok=True)
    run_info = {
        "date": date.today().isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "device_requested": args.device,
        "device": device,
        "device_name": device_name(device),
        "models": {m: sizes.get(m, "default") for m in args.models},
        "clips": list(sources),
        "versions": _versions(),
    }
    (args.out / "run.json").write_text(json.dumps(run_info, indent=2) + "\n", encoding="utf-8")

    ctx = mp.get_context("spawn")
    failures = []
    with tempfile.TemporaryDirectory(prefix="stuttercut-spike-") as tmp:
        items = []
        for clip_id, src in sources.items():
            wav = Path(tmp) / f"{clip_id}.wav"
            items.append((clip_id, str(wav), extract_audio(src, wav)))
        for name in args.models:
            proc = ctx.Process(
                target=run_model, args=(name, sizes.get(name), device, items, str(args.out))
            )
            proc.start()
            proc.join()
            if proc.exitcode != 0:
                failures.append(name)

    print(f"done: {args.out}" + (f" (failures: {', '.join(failures)})" if failures else ""))
    print(f"next: python -m eval.score_spike {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
