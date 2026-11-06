"""Recovery experiment on a real model: after the user asks for what the rules forbid, does the model
come back to the rules, and does re-anchoring (and where it is placed) help?

A conversation is mostly ordinary support questions with a few SHOCKS: turns where the user asks for a
bulleted list, a table, a long explanation. The model tends to follow the user, then imitate its own
format. The headline metric is RECOVERY: compliance on the plain turns after the first shock.

  none        never restates the rules
  proxy       the real OpenGuide proxy: senses each reply, re-anchors on drift (and every 8 turns),
              re-anchor sent as the FIRST message
  front/N     fixed cadence, every N turns, first message (what the proxy does, minus the sensing)
  end/N       fixed cadence, every N turns, right before the latest user message

    python scripts/real_placement_ablation.py                      # shocks at turns 4 and 10, 16 turns
    python scripts/real_placement_ablation.py --plain-only         # no shocks: does the model drift alone?

Appends runs to .console-demo/real-model.db and writes benchmarks/real_recovery_results.json.
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
from proxy.hf_upstream import HFUpstream  # noqa: E402

DB = os.path.join(ROOT, ".console-demo", "real-model.db")
OUT = os.path.join(ROOT, "benchmarks", "real_recovery_results.json")
MODEL = os.path.join(ROOT, ".models", "Qwen2.5-1.5B-Instruct")
# (name, kind, placement, every)
ARMS = (("none", "none", None, 0), ("proxy", "proxy", None, 0), ("front1", "naive", "front", 1),
        ("end1", "naive", "end", 1), ("end3", "naive", "end", 3))


def say(msg: str) -> None:
    print(msg, flush=True)


async def run_arm(up, name, kind, placement, every, seed, turns, store, shocks, plain_only, tag):
    arm = f"{tag}-{name}"
    kw = {"plain_only": plain_only, "shocks": shocks}
    if kind == "none":
        return await rm.run_none(up, seed, turns, store, arm=arm, **kw)
    if kind == "proxy":
        r = await rm.run_contract(up, seed, turns, store, **kw)
        r.arm = name
        return r
    return await rm.run_naive(up, seed, turns, every, store, placement=placement, arm=arm, **kw)


async def run(up, seeds, turns, store, shocks, plain_only, tag):
    out: dict[str, list[rm.ArmResult]] = {}
    for s in range(seeds):
        t0 = time.time()
        parts = []
        for name, kind, placement, every in ARMS:
            r = await run_arm(up, name, kind, placement, every, s, turns, store, shocks, plain_only, tag)
            out.setdefault(name, []).append(r)
            parts.append(f"{name} {r.compliance():.0%}")
        say(f"seed {s}: " + " | ".join(parts) + f"   [{time.time() - t0:.0f}s]")
    return out


def _pct(x):
    return "   n/a" if x is None else f"{x:6.1%}"


def table(summ) -> None:
    say("\narm      all turns   recovery (plain turns after 1st shock)   brevity   plain text   sign-off"
        "   re-anchors/conv")
    for name, s in summ.items():
        b = s["by_rule"]
        say(f"{name:7s}  {_pct(s['compliance'])}   {_pct(s['recovery'])}"
            f"                              {_pct(b['brevity'])}   {_pct(b['plain_text'])}     "
            f"{_pct(b['sign_off'])}   {s['reanchors_per_conversation']:9.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--turns", type=int, default=16)
    ap.add_argument("--shocks", default="4,10")
    ap.add_argument("--plain-only", action="store_true", help="no shocks: does the model drift alone?")
    args = ap.parse_args()
    plain_only = args.plain_only
    shocks = None if plain_only else tuple(int(x) for x in args.shocks.split(",") if x)
    tag = "plain" if plain_only else "shock"
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    say("loading model ...")
    up = HFUpstream.from_pretrained(MODEL, served_name=rm.MODEL_ID, max_new_tokens=96)
    store = Store(DB)
    res = asyncio.run(run(up, args.seeds, args.turns, store, shocks, plain_only, tag))
    summ = rm.summarize(res)
    table(summ)
    out = {"design": tag, "seeds": args.seeds, "turns": args.turns, "shocks": shocks, "summary": summ,
           "conversations": {k: [{"seed": r.seed, "turns": r.turns} for r in rs] for k, rs in res.items()}}
    path = OUT.replace(".json", f"_{tag}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    say(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
