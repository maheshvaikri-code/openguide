"""Run the pre-registered T0 generalization study (docs/preregistration/t0-generalization.md).

    python scripts/replicate_pool2.py           # the registered run: 60 conversations x 2 arms on a new
                                                # prompt pool, then GSM8K (all 1,319) and MMLU (500)
    python scripts/replicate_pool2.py --smoke   # pipeline check on OTHER seeds and tiny samples; no verdict

The design is fixed by the spec and is not a command-line option. The runner refuses to start unless the
spec is committed and unmodified and the prompt pool is the committed one. Every conversation is
checkpointed, so a crash resumes without changing anything (decoding is deterministic). Needs the weights
in .models/ and a GPU. ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import prompts_v2  # noqa: E402
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
    MMLU_N,
    PACK_HASH,
    SHOCKS,
    TURNS,
    code_state,
    load_progress,
    run_capability,
    say,
)

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-generalization.md")

# ── registered design (see the spec; not options) ─────────────────────
SEEDS = tuple(range(300, 360))
SMOKE_SEEDS = (920, 921)
GSM8K_N = 1319                       # the full GSM8K test split
SMOKE_GSM8K_N, SMOKE_MMLU_N = 20, 40
POOL = "v2"
POOL_CHECKSUM = "5a2f5f48f86f7aac"

OUT = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b", "replication_pool2.json")
PROGRESS = os.path.join(ROOT, "benchmarks", "replication_pool2_progress.jsonl")
CAP_PROGRESS = os.path.join(ROOT, "benchmarks", "replication_pool2_capability_progress.json")
DB = os.path.join(ROOT, ".console-demo", "replication.db")


def pool_checksum() -> str:
    return hashlib.sha256(json.dumps([prompts_v2.PLAIN_V2, prompts_v2.TEMPTING_V2]).encode()).hexdigest()[:16]


def run_conversations(up, config, seeds, store, blob: str, progress: str) -> dict[str, list[dict]]:
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} of {2 * len(seeds)} conversations already complete")
    for i, seed in enumerate(seeds):
        t = time.time()
        for arm, steering in (("t2", None), ("t2+t0", config)):
            if (seed, arm) in done:
                continue
            res = asyncio.run(rm.run_contract(up, seed, TURNS, store, shocks=SHOCKS, steering=steering,
                                              arm="pool2-t2" if arm == "t2" else "pool2-t2t0", pool=POOL))
            row = {"spec_blob": blob, "seed": seed, "arm": arm, "run_id": res.run_id, "turns": res.turns,
                   "steered_turns": [r["turn"] for r in res.trace.records if r["ev"] == "STEER"]}
            with open(progress, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            done[(seed, arm)] = row
        a, b = done[(seed, "t2")], done[(seed, "t2+t0")]
        say(f"seed {seed} ({i + 1}/{len(seeds)}): recovery t2 {rp.recovery(a['turns']):.2f} | "
            f"t2+t0 {rp.recovery(b['turns']):.2f} | steered {len(b['steered_turns'])} turns  "
            f"[{time.time() - t:.0f}s]")
    return {arm: [done[(s, arm)] for s in seeds] for arm in ("t2", "t2+t0")}


def earlier_t2_recovery() -> float | None:
    """Context only: mean t2 recovery over the 120 earlier conversations (pool 1)."""
    vals = []
    for name, arm in (("replication_t0.json", "t2"), ("replication_cap.json", "t2")):
        path = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b", name)
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            vals += [rp.recovery(c["turns"]) for c in d["conversations"][arm]]
    return sum(vals) / len(vals) if vals else None


def print_result(result: dict) -> None:
    a, cap, v = result["analysis"], result["capability"], result["verdict"]
    say("\n== result ==")
    say(f"  recovery  t2 {a['mean_recovery']['t2']:.3f}   t2+t0 {a['mean_recovery']['t2+t0']:.3f}"
        f"   (pool 1, 120 conversations: t2 {result['context']['pool1_t2_mean_recovery']:.3f})")
    lo, hi = a["ci95"]
    say(f"  paired difference {a['mean_diff']:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
    say(f"  {a['wins']} wins / {a['ties']} ties / {a['losses']} losses  "
        f"(sign test p = {a['sign_test_p']:.3g})")
    d = a["drifting"]
    line = f"  drifting under t2: {d['n']} conversations" + (" (UNDERPOWERED)" if d["underpowered"] else "")
    if d["n"]:
        line += f"; difference {d['mean_diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"
    say(line)
    worst = min(r["diff"] for r in a["per_seed"])
    say(f"  worst paired difference {worst:+.2f}; steered {a['steered_share']:.1%} of turns; shortest reply "
        f"{a['shortest_reply_words']} words, {a['replies_under_3_words']} under 3 words")
    for k in ("gsm8k", "mmlu"):
        c = cap[k]
        lo, hi = c["drop_ci95_points"]
        say(f"  {k.upper():6s} none {c['none']['acc']:.1%}  steered {c['steered']['acc']:.1%}  "
            f"drop {c['drop_points']:+.1f} points [{lo:+.1f}, {hi:+.1f}]   -> {v[k]}")
    if v:
        say(f"  benefit: {'PASS' if v['benefit_pass'] else 'FAIL'}   -> {v['outcome']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--smoke", action="store_true", help="pipeline check on other seeds; writes no verdict")
    args = ap.parse_args()

    spec = rp.spec_state(SPEC, ROOT)
    if not spec["ok"]:
        say(f"REFUSING TO RUN: {spec['reason']} ({spec['path']}). "
            "Commit the pre-registration first and do not edit it.")
        return 2
    if pool_checksum() != POOL_CHECKSUM:
        say("REFUSING TO RUN: the prompt pool is not the committed one")
        return 2
    if rm.compiled_contract().contract_hash != CONTRACT_HASH:
        say("REFUSING TO RUN: the contract is not the registered one")
        return 2
    seeds = SMOKE_SEEDS if args.smoke else SEEDS
    gsm_n, mmlu_n = (SMOKE_GSM8K_N, SMOKE_MMLU_N) if args.smoke else (GSM8K_N, MMLU_N)
    tag = ".smoke" if args.smoke else ""
    progress, cap_progress = PROGRESS + tag, CAP_PROGRESS + tag
    out_path = OUT.replace(".json", ".smoke.json") if args.smoke else OUT
    db = DB.replace(".db", ".smoke.db") if args.smoke else DB
    note = "  [SMOKE: not the registered run]" if args.smoke else ""
    say(f"spec {spec['path']} committed in {spec['commit'][:10]}; pool {POOL} checksum {POOL_CHECKSUM}{note}")

    say(f"loading {gate.MODEL} ...")
    up = HFUpstream.from_pretrained(gate.MODEL, served_name=rm.MODEL_ID, max_new_tokens=96)
    up.tokenizer.padding_side = "left"
    pack = SignalPack.load_safetensors(PACK_PATH)
    # refuses any other pack; no cap
    config = SteeringConfig(pack, gate.BAND, GAIN, expected_pack_hash=PACK_HASH)
    up.enable_steering(config)
    say(f"pack {config.pack_hash[:19]}...  gain {GAIN} (uncapped)  "
        f"band layers {gate.BAND[0]}..{gate.BAND[1] - 1}")
    os.makedirs(os.path.dirname(db), exist_ok=True)

    t = time.time()
    say(f"\n[A] {len(seeds)} conversations x 2 arms on pool {POOL} ({TURNS} turns, shocks at {SHOCKS})")
    convs = run_conversations(up, config, seeds, Store(db), spec["blob"], progress)
    analysis = rp.compare_conversations(convs["t2"], convs["t2+t0"])

    say(f"\n[B] capability: GSM8K n={gsm_n}, MMLU n={mmlu_n}, none vs steering always on at {GAIN}")
    capability = run_capability(up, config.pack_in_band(), gsm_n, mmlu_n, cap_progress)

    import torch
    import transformers
    result = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "design": {"gain": GAIN, "capped": False, "pool": POOL, "pool_checksum": POOL_CHECKSUM,
                   "seeds": [seeds[0], seeds[-1]], "n_conversations": len(seeds), "turns": TURNS,
                   "shocks": list(SHOCKS), "gsm8k_n": gsm_n, "mmlu_n": mmlu_n,
                   "pack_hash": config.pack_hash, "contract_hash": CONTRACT_HASH},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "context": {"pool1_t2_mean_recovery": earlier_t2_recovery()},
        "analysis": analysis, "capability": capability,
        "verdict": None if args.smoke else rp.pool_verdict(analysis, capability),
        "conversations": convs,
    }
    if args.smoke:                                   # categories are still printed, but no outcome is claimed
        result["verdict"] = {**rp.pool_verdict(analysis, capability), "outcome": "smoke: no verdict"}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print_result(result)
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
