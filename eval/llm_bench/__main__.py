"""python -m eval.llm_bench --provider ollama|anthropic [--model NAME] [--runs 3]"""

import argparse
import sys
import time
from dataclasses import replace

from eval.llm_bench import judge, load_cases, score
from stuttercut.config import DEFAULT_MODELS, LLM_PROVIDERS, load_config
from stuttercut.worker.main import load_llm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=LLM_PROVIDERS, default="ollama")
    ap.add_argument("--model", default="", help="default: the provider's default model")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    base = load_config()
    llm_cfg = replace(base.llm, enabled=True, provider=args.provider,
                      model=args.model or DEFAULT_MODELS[args.provider])  # fmt: skip
    cfg = replace(base, llm=llm_cfg)
    client = load_llm(cfg)
    if client is None:
        print("no client: anthropic needs LLM_API_KEY in .env", file=sys.stderr)
        return 2
    sure_min = cfg.rules.tier_sure_min
    cases = load_cases()
    print(f"{args.provider} {llm_cfg.model}: {len(cases)} cases x {args.runs} runs")

    warm = getattr(client, "warm", None)
    if warm is not None:
        warm()
    answers: dict[str, list[str]] = {c.id: [] for c in cases}
    t0 = time.perf_counter()
    try:
        for run in range(args.runs):
            for c in cases:
                got, why = judge(c, client, llm_cfg, sure_min)
                answers[c.id].append(got)
                if run == 0 or len(set(answers[c.id])) > 1:
                    mark = "ok " if got == c.expected else "BAD"
                    print(f"  run {run + 1} {mark} {c.id:<3} {c.category:<19} expected "
                          f"{c.expected:<5} got {got:<9} | {why[:70]}")  # fmt: skip
    finally:
        release = getattr(client, "release", None)
        if release is not None:
            release()
    elapsed = time.perf_counter() - t0

    print(f"\n{'category':<20} {'n':>3} {'accuracy':>9} {'stable':>7}")
    for cat, s in score(cases, answers).items():
        print(f"{cat:<20} {s['n']:>3} {s['accuracy']:>9.0%} {s['stable']:>7.0%}")
    print(f"{elapsed / (len(cases) * args.runs):.1f} s per case, {elapsed:.0f} s in all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
