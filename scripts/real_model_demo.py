"""Run the real-model experiment, then serve the results in the Console.

    python scripts/real_model_demo.py --seeds 5 --turns 30        # run (GPU), ~30 min for 5x30
    python scripts/real_model_demo.py --serve                     # open the saved runs in the Console

Needs the weights in .models/Qwen2.5-1.5B-Instruct (see benchmarks/REPORT.md for how they were
fetched). Results: .console-demo/real-model.db (served by --serve) and
benchmarks/real_model_results.json (every reply, every check). ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_model as rm  # noqa: E402
from guidancegrid.store import Store  # noqa: E402

DB = os.path.join(ROOT, ".console-demo", "real-model.db")
RESULTS = os.path.join(ROOT, "benchmarks", "real_model_results.json")
DEFAULT_MODEL = os.path.join(ROOT, ".models", "Qwen2.5-1.5B-Instruct")


def say(msg: str) -> None:
    print(msg, flush=True)


async def run_all(upstream, seeds: list[int], turns: int, store) -> dict[str, list[rm.ArmResult]]:
    by_arm: dict[str, list[rm.ArmResult]] = {"contract": [], "naive": [], "none": []}
    for seed in seeds:
        t0 = time.time()
        gov = await rm.run_contract(upstream, seed, turns, store)
        every = rm.matched_every(turns, len(gov.reanchor_turns))
        naive = await rm.run_naive(upstream, seed, turns, every, store)
        none = await rm.run_none(upstream, seed, turns, store)
        by_arm["contract"].append(gov)
        by_arm["naive"].append(naive)
        by_arm["none"].append(none)
        say(f"seed {seed}: contract {gov.compliance():.0%} ({len(gov.reanchor_turns)} re-anchors) | "
            f"naive {naive.compliance():.0%} (every {every}) | none {none.compliance():.0%}"
            f"   [{time.time() - t0:.0f}s]")
    return by_arm


def dump(by_arm, summary, model: str, turns: int) -> None:
    payload = {
        "model": model, "turns": turns, "contract": os.path.basename(rm.CONTRACT_PATH),
        "summary": summary,
        "conversations": {arm: [{"seed": r.seed, "run_id": r.run_id, "compliance": r.compliance(),
                                 "reanchor_turns": r.reanchor_turns, "turns": r.turns} for r in rs]
                          for arm, rs in by_arm.items()},
    }
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)


def _pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{x:6.1%}"


def print_summary(summary) -> None:
    say("")
    say("arm        all turns   plain prompts   tempting prompts   brevity   plain text   sign-off   "
        "re-anchors   peak drift")
    for arm in ("none", "naive", "contract"):
        s = summary[arm]
        if not s["turns"]:
            continue
        b, k = s["by_rule"], s["by_kind"]
        say(f"{arm:9s}  {_pct(s['compliance'])}   {_pct(k['plain'])}        {_pct(k['tempting'])}"
            f"          {_pct(b['brevity'])}   {_pct(b['plain_text'])}      {_pct(b['sign_off'])}   "
            f"{s['reanchors_per_conversation']:8.1f}     {s['mean_peak_drift']:8.2f}")


def serve(port: int) -> int:
    import uvicorn

    from proxy.app import create_app
    from proxy.registry import ContractRegistry
    from proxy.upstream import MockUpstream

    if not os.path.isfile(DB):
        say(f"No saved results at {DB}. Run the experiment first (without --serve).")
        return 2
    console_dir = os.path.join(ROOT, "console", "dist")
    if not os.path.isfile(os.path.join(console_dir, "index.html")):
        say("Console is not built. Run: npm --prefix console run build")
        return 2
    registry = ContractRegistry(measures=rm.make_measures())
    registry.register(rm.contract_dict())
    app = create_app(registry=registry, upstream=MockUpstream(), store=Store(DB),
                     console_dir=console_dir)
    say(f"Console: http://127.0.0.1:{port}/console/   (REAL model runs: {rm.MODEL_ID})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=DEFAULT_MODEL, help="path to local weights")
    ap.add_argument("--seeds", type=int, default=5, help="number of conversations per arm")
    ap.add_argument("--turns", type=int, default=30)
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--serve", action="store_true", help="serve saved results; do not run the model")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()
    if args.serve:
        return serve(args.port)

    from proxy.hf_upstream import HFUpstream

    if not os.path.isdir(args.model):
        say(f"No model at {args.model}")
        return 2
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)                                  # fresh results every run
    say(f"loading {args.model} ...")
    t0 = time.time()
    upstream = HFUpstream.from_pretrained(
        args.model, served_name=rm.MODEL_ID, max_new_tokens=args.max_new_tokens)
    say(f"loaded in {time.time() - t0:.0f}s; {args.seeds} conversations x {args.turns} turns x 3 arms")
    store = Store(DB)
    by_arm = asyncio.run(run_all(upstream, list(range(args.seeds)), args.turns, store))
    summary = rm.summarize(by_arm)
    dump(by_arm, summary, args.model, args.turns)
    print_summary(summary)
    say(f"\nsaved: {DB}\n       {RESULTS}\nview:  python scripts/real_model_demo.py --serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
