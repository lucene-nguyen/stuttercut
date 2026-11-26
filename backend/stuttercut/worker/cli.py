"""Manual run: python -m stuttercut.worker.cli <video>
           python -m stuttercut.worker.cli render <job_id|latest> [--approve sure|all|none]
                                              [--format mp4|xml|both]

The first creates a job, loads the real transcriber and VAD and runs the pipeline in this
process. It prints the job id, device, step timings, word counts, cut counts per reason and
source, and peak RSS/VRAM. ``render`` marks which cuts are approved (until the review UI does,
LEARNING-209), renders and prints the approved cut count, removed seconds, output duration,
encoder, render time and output paths. Neither prints transcript text.
"""

import argparse
import sys
import time
from pathlib import Path

from stuttercut.asr import Unloadable
from stuttercut.config import RENDER_FORMATS, load_config
from stuttercut.observability.logging import setup_logging
from stuttercut.observability.metrics import PeakRss
from stuttercut.storage import paths, repo
from stuttercut.storage.db import connect
from stuttercut.worker.main import load_llm, load_transcriber, load_vad
from stuttercut.worker.pipeline import run_job, run_render


def peak_vram_mb() -> int | None:
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_available() or not torch.cuda.is_initialized():
        return None
    return round(int(torch.cuda.max_memory_reserved()) / 2**20)


def render_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="stuttercut.worker.cli render")
    parser.add_argument("job", help="job id, or 'latest'")
    parser.add_argument(
        "--approve",
        choices=repo.APPROVE_MODES,
        default="sure",
        help="sure = only the sure tier; all; none = render as-is (baseline)",
    )
    parser.add_argument("--format", choices=RENDER_FORMATS, default="mp4")  # fmt: skip
    args = parser.parse_args(argv)

    cfg = load_config()
    log_file = setup_logging(paths.log_dir(cfg), cfg.log)
    conn = connect(paths.db_path(cfg))
    job_id = repo.latest_job(conn) if args.job == "latest" else args.job
    if job_id is None or repo.get_job(conn, job_id) is None:
        parser.error(f"no renderable job {args.job!r}")
    approved = repo.approve_cuts(conn, job_id, args.approve)
    print(f"job {job_id}: approve {args.approve}, {approved} cuts approved", flush=True)
    t0 = time.perf_counter()
    try:
        result = run_render(conn, cfg, job_id, args.format)
    except ValueError as e:  # wrong status
        print(e)
        return 1
    took = time.perf_counter() - t0
    job = repo.get_job(conn, job_id)
    assert job is not None
    if result.status != "done":
        print(f"status failed at {job['failed_step']}: {job['error']}")
        print(f"log {log_file}")
        return 1
    print(f"removed {result.removed_s:.2f} s, output {result.output_s:.2f} s")
    if result.mp4:
        print(f"encoder {result.encoder}")
    print(f"render time {took:.1f} s")
    for p in (result.mp4, result.xml):
        if p:
            print(f"output {p}")
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["render"]:
        return render_main(argv[1:])
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
        vad = load_vad(cfg)
        llm = load_llm(cfg)
        status = run_job(conn, cfg, job_id, transcriber, vad, llm)
        resident = getattr(llm, "peak_resident_mb", None)  # Ollama's own process, not ours
        reload_s = None
        if isinstance(transcriber, Unloadable) and not transcriber.loaded:
            t0 = time.perf_counter()  # what the next job pays for the unload
            transcriber.load()
            reload_s = time.perf_counter() - t0

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
    for by in ("reason", "source", "tier"):
        by_count = repo.cut_counts(conn, job_id, by)
        listed = ", ".join(f"{k} {n}" for k, n in sorted(by_count.items())) or "none"
        print(f"cuts by {by}: {listed} (total {sum(by_count.values())})")
    print(f"vad {'silero' if vad else 'off'}")
    if llm is None:
        print("llm review off (STUTTERCUT_LLM_ENABLED=false, or anthropic without LLM_API_KEY)")
    else:
        cuts = repo.get_cuts(conn, job_id)
        keeps = sum(c["llm_verdict"] == "keep" for c in cuts)
        new = sum(c["source"] == "llm" for c in cuts)
        if resident:
            print(f"llm peak in Ollama: {resident[0]} MB, of which VRAM {resident[1]} MB")
        print(
            f"llm {cfg.llm.provider} {llm.model}: "
            f"tokens in {job['llm_input_tokens']} out {job['llm_output_tokens']}, "
            f"cost ${job['llm_cost_usd']}, verdict keep {keeps}, new retakes {new}"
        )
    if reload_s is not None:
        print(f"asr unloaded before llm_review; reload {reload_s:.1f} s (paid by the next job)")
    print(f"db {paths.db_path(cfg)}\nlog {log_file}")
    conn.close()
    return 0 if status == "ready_for_review" else 1


if __name__ == "__main__":
    sys.exit(main())
