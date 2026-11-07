"""Run the pre-registered study of a cap on consecutive steered turns (docs/preregistration/t0-cap-study.md).

    python scripts/replicate_cap.py           # the registered run: 60 conversations x 3 arms
    python scripts/replicate_cap.py --smoke   # pipeline check on OTHER seeds; no verdict

The design (gain, cap, seeds, N, thresholds) is fixed by the spec and is not a command-line option. The
runner refuses to start unless the spec is committed and unmodified. Every conversation is checkpointed, so a
crash resumes without changing anything (decoding is deterministic). Needs the weights in .models/ and a GPU.
ASCII-only output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_model as rm  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.derive_steering_pack import DEFAULT_OUT as PACK_PATH  # noqa: E402
from scripts.replicate_t0 import (  # noqa: E402
    CONTRACT_HASH,
    GAIN,
    PACK_HASH,
    SHOCKS,
    TURNS,
    code_state,
    load_progress,
    say,
)

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-cap-study.md")

# ── registered design (see the spec; not options) ─────────────────────
SEEDS = tuple(range(200, 260))
SMOKE_SEEDS = (910, 911)
MAX_CONSECUTIVE, PAUSE_TURNS = 2, 3
ARMS = ("t2", "uncapped", "capped")

OUT = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b", "replication_cap.json")
PROGRESS = os.path.join(ROOT, "benchmarks", "replication_cap_progress.jsonl")
DB = os.path.join(ROOT, ".console-demo", "replication.db")


def run_conversations(up, configs: dict, seeds, store, blob: str, progress: str) -> dict[str, list[dict]]:
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} of {len(ARMS) * len(seeds)} conversations already complete")
    for i, seed in enumerate(seeds):
        t = time.time()
        for arm in ARMS:
            if (seed, arm) in done:
                continue
            res = asyncio.run(rm.run_contract(up, seed, TURNS, store, shocks=SHOCKS, steering=configs[arm],
                                              arm=f"cap-{arm}"))
            row = {"spec_blob": blob, "seed": seed, "arm": arm, "run_id": res.run_id, "turns": res.turns,
                   "steered_turns": [r["turn"] for r in res.trace.records if r["ev"] == "STEER"]}
            with open(progress, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            done[(seed, arm)] = row
        rec = {a: rp.recovery(done[(seed, a)]["turns"]) for a in ARMS}
        steered = {a: len(done[(seed, a)]["steered_turns"]) for a in ARMS[1:]}
        say(f"seed {seed} ({i + 1}/{len(seeds)}): recovery t2 {rec['t2']:.2f} | "
            f"uncapped {rec['uncapped']:.2f} ({steered['uncapped']} steered) | "
            f"capped {rec['capped']:.2f} ({steered['capped']} steered)  [{time.time() - t:.0f}s]")
    return {arm: [done[(s, arm)] for s in seeds] for arm in ARMS}


def print_result(result: dict) -> None:
    a, v = result["analysis"], result["verdict"]
    say("\n== result ==")
    for key, label in (("capped_vs_t2", "capped - t2"), ("uncapped_vs_t2", "uncapped - t2"),
                       ("capped_vs_uncapped", "capped - uncapped")):
        c = a[key]
        say(f"  {label:18s} {c['mean_diff']:+.3f}  95% CI [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]  "
            f"{c['wins']} wins / {c['ties']} ties / {c['losses']} losses")
    say(f"  mean recovery: t2 {a['capped_vs_t2']['mean_recovery']['t2']:.3f}  "
        f"uncapped {a['uncapped_vs_t2']['mean_recovery']['t2+t0']:.3f}  "
        f"capped {a['capped_vs_t2']['mean_recovery']['t2+t0']:.3f}")
    say(f"  worst paired difference vs t2: uncapped {a['worst_diff']['uncapped']:+.2f}  "
        f"capped {a['worst_diff']['capped']:+.2f}")
    for arm in ("uncapped", "capped"):
        s = a["steered_per_conversation"][arm]
        say(f"  steered turns per conversation, {arm}: min {s['min']}  median {s['median']:g}  "
            f"max {s['max']}  mean {s['mean']:.1f}")
    say(f"  shock-turn compliance: t2 {a['capped_vs_t2']['shock_turn_compliance']['t2']:.2f}  "
        f"uncapped {a['uncapped_vs_t2']['shock_turn_compliance']['t2+t0']:.2f}  "
        f"capped {a['capped_vs_t2']['shock_turn_compliance']['t2+t0']:.2f}")
    say(f"  replies not in English: {a['not_english']}")
    say(f"  drifting under t2: {a['capped_vs_t2']['drifting']['n']} conversations")
    if v:
        marks = {k: ("PASS" if v[k] else "FAIL") for k in ("benefit_kept", "harm_reduced", "non_inferior")}
        say(f"  1 benefit kept: {marks['benefit_kept']}   2 harm reduced: {marks['harm_reduced']}   "
            f"3 non-inferior: {marks['non_inferior']}   -> {v['outcome']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--smoke", action="store_true", help="pipeline check on other seeds; writes no verdict")
    args = ap.parse_args()

    spec = rp.spec_state(SPEC, ROOT)
    if not spec["ok"]:
        say(f"REFUSING TO RUN: {spec['reason']} ({spec['path']}). "
            "Commit the pre-registration first and do not edit it.")
        return 2
    seeds = SMOKE_SEEDS if args.smoke else SEEDS
    tag = ".smoke" if args.smoke else ""
    progress = PROGRESS + tag
    out_path = OUT.replace(".json", ".smoke.json") if args.smoke else OUT
    db = DB.replace(".db", ".smoke.db") if args.smoke else DB
    note = "  [SMOKE: not the registered run]" if args.smoke else ""
    say(f"spec {spec['path']} committed in {spec['commit'][:10]}{note}")
    if rm.compiled_contract().contract_hash != CONTRACT_HASH:
        say("REFUSING TO RUN: the contract is not the registered one")
        return 2

    say(f"loading {gate.MODEL} ...")
    up = HFUpstream.from_pretrained(gate.MODEL, served_name=rm.MODEL_ID, max_new_tokens=96)
    up.tokenizer.padding_side = "left"
    pack = SignalPack.load_safetensors(PACK_PATH)
    # both refuse any pack other than the registered one
    uncapped = SteeringConfig(pack, gate.BAND, GAIN, expected_pack_hash=PACK_HASH)
    capped = SteeringConfig(pack, gate.BAND, GAIN, expected_pack_hash=PACK_HASH,
                            max_consecutive=MAX_CONSECUTIVE, pause_turns=PAUSE_TURNS)
    up.enable_steering(uncapped)
    say(f"pack {uncapped.pack_hash[:19]}...  gain {GAIN}  "
        f"cap {MAX_CONSECUTIVE} consecutive, pause {PAUSE_TURNS}")
    os.makedirs(os.path.dirname(db), exist_ok=True)

    t = time.time()
    say(f"\n{len(seeds)} conversations x {len(ARMS)} arms ({TURNS} turns, shocks at {SHOCKS})")
    convs = run_conversations(up, {"t2": None, "uncapped": uncapped, "capped": capped}, seeds, Store(db),
                              spec["blob"], progress)
    analysis = rp.compare_cap_arms(convs["t2"], convs["uncapped"], convs["capped"])

    import torch
    import transformers
    result = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "design": {"gain": GAIN, "max_consecutive": MAX_CONSECUTIVE, "pause_turns": PAUSE_TURNS,
                   "seeds": [seeds[0], seeds[-1]], "n_conversations": len(seeds), "turns": TURNS,
                   "shocks": list(SHOCKS), "pack_hash": uncapped.pack_hash, "contract_hash": CONTRACT_HASH},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "analysis": analysis,
        "verdict": None if args.smoke else rp.cap_verdict(analysis),
        "conversations": convs,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print_result(result)
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
