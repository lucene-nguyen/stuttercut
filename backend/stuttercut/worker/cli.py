"""Manual run: python -m stuttercut.worker.cli <video>

Creates a job, loads the real transcriber and runs the pipeline in this process. Prints the job
id, device, step timings, word counts per variant and peak RSS/VRAM; never transcript text.
"""

import argparse
import sys
import time
from pathlib import Path

from stuttercut.config import load_config
from stuttercut.observability.logging import setup_logging
from stuttercut.observability.metrics import PeakRss
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import load_transcriber
from stuttercut.worker.pipeline import run_job


def peak_vram_mb() -> int | None:
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_available() or not torch.cuda.is_initialized():
        return None
    return round(int(torch.cuda.max_memory_reserved()) / 2**20)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", type=Path)
    args = parser.parse_args(argv)
    if not args.video.is_file():
        parser.error(f"not a file: {args.video}")

    cfg = load_config()
    log_file = setup_logging(paths.log_dir(cfg), cfg.log)
    conn = connect(paths.db_path(cfg))
    job_id = repo.create_job(conn, str(args.video.resolve()))
    print(f"job {job_id}", flush=True)

    with PeakRss() as rss:
        t0 = time.perf_counter()
        transcriber = load_transcriber(cfg)
        load_s = time.perf_counter() - t0
        print(
            f"model {transcriber.model_id} on {transcriber.device}, passes {cfg.asr.passes}, "
            f"loaded in {load_s:.1f} s"
        )
        status = run_job(conn, cfg, job_id, transcriber)

    for s in repo.get_spans(conn, job_id):
        print(f"  {s['step']:<14} {s['duration_s']:>7.2f} s  {s['status']}")
    job = repo.get_job(conn, job_id)
    assert job is not None
    counts = repo.word_counts(conn, job_id)
    vram = peak_vram_mb()
    print(
        f"status {status}"
        + (f" at {job['failed_step']}: {job['error']}" if status == "failed" else "")
    )
    print(
        f"duration {job['duration_s']} s, "
        f"words verbatim {counts['verbatim']}, "
        + (f"intended {counts['intended']}" if cfg.asr.passes == "dual" else "intended skipped")
    )
    print(
        f"peak RSS {rss.peak_mb} MB" + (f", peak VRAM {vram} MB (torch reserved)" if vram else "")
    )
    print(f"db {paths.db_path(cfg)}\nlog {log_file}")
    conn.close()
    return 0 if status == "transcribed" else 1


if __name__ == "__main__":
    sys.exit(main())
