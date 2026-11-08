"""Does drift-gated T0 steering help beyond the proxy's text re-anchoring alone? (ADR-003, REPORT 7.3)

    python scripts/derive_steering_pack.py                  # once: make the steering pack
    python scripts/real_closed_loop.py                      # 5 conversations x 16 turns, shocks at 4 and 10

Two arms on the SAME conversations as REPORT 7.1/7.2, both through the real proxy (create_app):
  t2     : the proxy as it was - a failed turn gets a text re-anchor on the next request.
  t2+t0  : the same, and the next generation is also steered at --gain (default 0.05) after a failed turn.
Decoding is greedy, so a re-run repeats. The runs are stored next to the other real-model runs
(.console-demo/real-model.db) so they can be replayed in the Console. Writes
benchmarks/real_closed_loop_results.json (every turn, every check). ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_model as rm  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.derive_steering_pack import DEFAULT_OUT as DEFAULT_PACK  # noqa: E402

OUT = os.path.join(ROOT, "benchmarks", "real_closed_loop_results.json")


def say(msg: str) -> None:
    print(msg, flush=True)


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided sign test on the non-tied pairs."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


async def run_arms(up, config, seeds: int, turns: int, shocks: tuple[int, ...], store) -> dict:
    t2, cl = [], []
    for seed in range(seeds):
        t = time.time()
        a = await rm.run_contract(up, seed, turns, store, shocks=shocks, arm="cl-t2")
        b = await rm.run_contract(up, seed, turns, store, shocks=shocks, steering=config, arm="cl-t2t0")
        t2.append(a)
        cl.append(b)
        steered = sum(1 for r in b.trace.records if r["ev"] == "STEER")
        say(f"seed {seed}: t2 {a.compliance():.0%} | t2+t0 {b.compliance():.0%} "
            f"({steered} of {turns} turns steered)   [{time.time() - t:.0f}s]")
    return {"t2": t2, "t2+t0": cl}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=gate.MODEL)
    ap.add_argument("--pack", default=DEFAULT_PACK)
    ap.add_argument("--gain", type=float, default=0.05, help="Qwen's validated ceiling is 0.05")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--turns", type=int, default=16)
    ap.add_argument("--shocks", default="4,10")
    args = ap.parse_args()
    if not os.path.exists(args.pack):
        say(f"no steering pack at {args.pack}; run scripts/derive_steering_pack.py first")
        return 2

    say(f"loading {args.model} ...")
    up = HFUpstream.from_pretrained(args.model, served_name=rm.MODEL_ID, max_new_tokens=96)
    pack = SignalPack.load_safetensors(args.pack)
    config = SteeringConfig(pack, gate.BAND, args.gain)
    up.enable_steering(config)
    say(f"pack {config.pack_hash[:19]}...  band layers {gate.BAND[0]}..{gate.BAND[1] - 1}  gain {args.gain}")

    shocks = tuple(int(x) for x in args.shocks.split(",") if x)
    store = Store(gate.DB)
    t0 = time.time()
    by_arm = asyncio.run(run_arms(up, config, args.seeds, args.turns, shocks, store))
    summary = rm.summarize(by_arm)

    wins = ties = losses = 0
    diffs = []
    for a, b in zip(by_arm["t2"], by_arm["t2+t0"]):
        d = b.compliance() - a.compliance()
        diffs.append(d)
        wins, ties, losses = wins + (d > 1e-9), ties + (abs(d) <= 1e-9), losses + (d < -1e-9)
    paired = {"mean_diff": sum(diffs) / len(diffs), "wins": wins, "ties": ties, "losses": losses,
              "sign_test_p": sign_test_p(wins, losses), "per_seed": diffs}

    say("\n== result (all turns / recovery after the first shock) ==")
    for arm, s in summary.items():
        say(f"  {arm:<6}: compliant {s['compliance']:.1%}   recovery {s['recovery']:.1%}   "
            f"plain {s['by_kind']['plain']:.1%}  tempting {s['by_kind']['tempting']:.1%}")
    say(f"  paired t2+t0 minus t2: {paired['mean_diff']:+.3f} per conversation; "
        f"{wins} wins / {ties} ties / {losses} losses (exact sign test p = {paired['sign_test_p']:.2f})")

    steered_replies = [t["reply"] for r in by_arm["t2+t0"] for t in r.turns]
    words = [len(x.split()) for x in steered_replies]
    short = sum(1 for w in words if w < 3)
    say(f"  sanity: shortest reply {min(words)} words, {short} replies under 3 words "
        f"(a rule-checker can pass broken output; look at the replies, not only the scores)")

    out = {
        "model": args.model, "pack_hash": config.pack_hash, "band": list(gate.BAND), "gain": args.gain,
        "seeds": args.seeds, "turns": args.turns, "shocks": list(shocks),
        "summary": summary, "paired_t2t0_minus_t2": paired,
        "conversations": {arm: [{"seed": r.seed, "run_id": r.run_id, "compliance": r.compliance(),
                                 "steered_turns": [x["turn"] for x in r.trace.records if x["ev"] == "STEER"],
                                 "turns": r.turns} for r in rs] for arm, rs in by_arm.items()},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    say(f"\nwrote {OUT}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
