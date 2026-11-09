"""The direction control on Qwen2.5-1.5B (docs/preregistration/t0-direction-control.md).

    python scripts/replicate_direction_control.py           # 60 conversations x 3 arms, then GSM8K (random)
    python scripts/replicate_direction_control.py --smoke   # pipeline check on OTHER seeds and 20 problems

The design is fixed by the spec and is not an option. The runner refuses to start unless the spec is
committed and unmodified, the prompt pool and both packs are the registered ones, and the unsteered GSM8K
baseline reproduces. The rules arm runs under Qwen's validated record; the random arm is an experiment under
the guard (experimental=True) and is marked in the trace. Arms are run one after another so each
authorisation is set once. Every conversation is checkpointed. Needs a GPU. ASCII-only output.
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

from benchmarks import diagnostics as diag  # noqa: E402
from benchmarks import models  # noqa: E402
from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.replicate_pool2 import POOL, POOL_CHECKSUM, pool_checksum  # noqa: E402
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

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-direction-control.md")

# registered design (see the spec; not options)
SEEDS = tuple(range(600, 660))
SMOKE_SEEDS = (960, 961)
RANDOM_SEED = 2718
RANDOM_PACK_HASH = "sha256:468a3c1d6d1b0a74acce9e7d94e134eb36d97855f860b54fba40a9732c9a65c2"
ARMS = ("t2", "rules", "random")
GSM8K_N, SMOKE_GSM8K_N, CHECK_N = 1319, 20, 40

RES = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b")
FLAGS = os.path.join(RES, "replication_pool2_gsm8k_flags.json")
OUT = os.path.join(RES, "direction_control.json")
PROGRESS = os.path.join(ROOT, "benchmarks", "direction_control_progress.jsonl")
CAP_PROGRESS = os.path.join(ROOT, "benchmarks", "direction_control_capability_progress.json")
DB = os.path.join(ROOT, ".console-demo", "replication.db")


def run_arm(up, arm: str, cfg, seeds, store, blob: str, progress: str, done: dict) -> None:
    """Run one arm on every seed (checkpointed). Authorisation for ``cfg`` must already be set on ``up``."""
    for i, seed in enumerate(seeds):
        if (seed, arm) in done:
            continue
        t = time.time()
        res = asyncio.run(rm.run_contract(up, seed, TURNS, store, shocks=SHOCKS, steering=cfg,
                                          arm=f"dir-{arm}", pool=POOL, model_id=models.QWEN.served_name))
        row = {"spec_blob": blob, "seed": seed, "arm": arm, "run_id": res.run_id, "turns": res.turns,
               "steered_turns": [r["turn"] for r in res.trace.records if r["ev"] == "STEER"],
               "experimental_marks": sum(1 for r in res.trace.records
                                         if r["ev"] == "STEER" and r.get("experimental") is True)}
        with open(progress, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        done[(seed, arm)] = row
        say(f"  [{arm}] seed {seed} ({i + 1}/{len(seeds)}): recovery {rp.recovery(row['turns']):.2f}, "
            f"steered {len(row['steered_turns'])} turns  [{time.time() - t:.0f}s]")


def gsm8k_flags(up, band_pack, problems, gain: float) -> list[int]:
    ctx = t0.steering_context(up.model, band_pack, models.QWEN.band, gain, {"model": models.QWEN.key})
    out: list[int] = []
    for b in gate.batches(problems, 20):
        replies = t0.generate_batch(up.model, up.tokenizer, gate.BASE_SYSTEM,
                                    [q + gate.GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
        out += [int(t0.same_number(t0.extract_number(r), gold)) for r, (_, gold) in zip(replies, b)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--smoke", action="store_true", help="pipeline check on other seeds; no verdict")
    args = ap.parse_args()
    prof = models.QWEN

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
    gsm_n = SMOKE_GSM8K_N if args.smoke else GSM8K_N
    tag = ".smoke" if args.smoke else ""
    progress, cap_progress = PROGRESS + tag, CAP_PROGRESS + tag
    out_path = OUT.replace(".json", ".smoke.json") if args.smoke else OUT
    db = DB.replace(".db", ".smoke.db") if args.smoke else DB
    note = "  [SMOKE: not the registered run]" if args.smoke else ""
    say(f"spec {spec['path']} committed in {spec['commit'][:10]}; pool {POOL} {POOL_CHECKSUM}{note}")

    say(f"loading {prof.path} ({prof.dtype}) ...")
    up = HFUpstream.from_pretrained(prof.path, served_name=prof.served_name, max_new_tokens=96,
                                    dtype=prof.dtype)
    rules_pack = SignalPack.load_safetensors(prof.pack_path)
    random_pack = diag.random_direction_pack(rules_pack, prof.band, RANDOM_SEED)
    if rules_pack.hash() != PACK_HASH or random_pack.hash() != RANDOM_PACK_HASH:
        say("REFUSING TO RUN: a pack is not the registered one")
        return 2
    cfg_rules = SteeringConfig(rules_pack, prof.band, GAIN, expected_pack_hash=PACK_HASH)
    cfg_random = SteeringConfig(random_pack, prof.band, GAIN, expected_pack_hash=RANDOM_PACK_HASH,
                                experimental=True, gain_ceiling=GAIN)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    store, blob = Store(db), spec["blob"]
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} of {len(ARMS) * len(seeds)} conversations already complete")

    t = time.time()
    say(f"\n[A] {len(seeds)} conversations x {len(ARMS)} arms on pool {POOL} "
        f"({TURNS} turns, shocks at {SHOCKS})")
    say("arm t2 (no steering)")
    run_arm(up, "t2", None, seeds, store, blob, progress, done)
    say("arm rules (validated record)")
    up.enable_steering(cfg_rules)
    assert up.steering_authorisation.mode == "validated"
    run_arm(up, "rules", cfg_rules, seeds, store, blob, progress, done)
    say("arm random (experimental, marked in the trace)")
    up.enable_steering(cfg_random)
    assert up.steering_authorisation.mode == "experimental"
    run_arm(up, "random", cfg_random, seeds, store, blob, progress, done)
    convs = {arm: [done[(s, arm)] for s in seeds] for arm in ARMS}

    rules_vs_random = rp.compare_conversations(convs["random"], convs["rules"])      # rules - random
    random_vs_t2 = rp.compare_conversations(convs["t2"], convs["random"])
    rules_vs_t2 = rp.compare_conversations(convs["t2"], convs["rules"])
    verdict = rp.direction_verdict(rules_vs_random, random_vs_t2, rules_vs_t2)
    marks = sum(r["experimental_marks"] for r in convs["random"])
    steered_random = sum(len(r["steered_turns"]) for r in convs["random"])

    say(f"\n[B] GSM8K, {gsm_n} problems, random arm, steering always on at {GAIN}")
    flags = json.load(open(FLAGS, encoding="utf-8"))
    none, rules = flags["gsm8k_none"][:gsm_n], flags["gsm8k_steered"][:gsm_n]
    problems = gate.load_gsm8k(GSM8K_N)[:gsm_n]
    band_pack = cfg_random.pack_in_band()
    check = min(CHECK_N, gsm_n)
    if gsm8k_flags(up, band_pack, problems[:check], 0.0) != none[:check]:
        say("REFUSING TO CONTINUE: the unsteered results do not reproduce the committed ones")
        return 2
    say(f"  unsteered baseline reproduced on the first {check} problems")
    state = json.load(open(cap_progress, encoding="utf-8")) if os.path.exists(cap_progress) else {}
    if "random" not in state:
        state["random"] = gsm8k_flags(up, band_pack, problems, GAIN)
        json.dump(state, open(cap_progress, "w", encoding="utf-8"))
    capability = {"random": rp.compare_accuracy(none, state["random"]),
                  "rules": rp.compare_accuracy(none, rules),
                  "rules_minus_random": rp.compare_accuracy(rules, state["random"])}

    import torch
    import transformers
    result = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "design": {"gain": GAIN, "pool": POOL, "pool_checksum": POOL_CHECKSUM, "seeds": [seeds[0], seeds[-1]],
                   "n_conversations": len(seeds), "turns": TURNS, "shocks": list(SHOCKS),
                   "rules_pack_hash": PACK_HASH, "random_pack_hash": RANDOM_PACK_HASH,
                   "random_seed": RANDOM_SEED,
                   "gsm8k_n": gsm_n, "contract_hash": CONTRACT_HASH},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "analysis": {"rules_vs_random": rules_vs_random, "random_vs_t2": random_vs_t2,
                     "rules_vs_t2": rules_vs_t2},
        "trace_marks": {"random_steer_records": steered_random, "marked_experimental": marks},
        "verdict": {**verdict, "outcome": "smoke: no verdict"} if args.smoke else verdict,
        "capability": capability, "conversations": convs,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    say("\n== result ==")
    for key, label in (("rules_vs_random", "rules - random"), ("random_vs_t2", "random - t2"),
                       ("rules_vs_t2", "rules - t2")):
        c = result["analysis"][key]
        say(f"  {label:15s} {c['mean_diff']:+.3f}  95% CI [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]  "
            f"{c['wins']} wins / {c['ties']} ties / {c['losses']} losses")
    rec = {"t2": rules_vs_t2["mean_recovery"]["t2"], "rules": rules_vs_t2["mean_recovery"]["t2+t0"],
           "random": random_vs_t2["mean_recovery"]["t2+t0"]}
    say(f"  mean recovery: t2 {rec['t2']:.3f}  rules {rec['rules']:.3f}  random {rec['random']:.3f}")
    share = (rules_vs_t2["steered_share"], random_vs_t2["steered_share"])
    say(f"  steered share: rules {share[0]:.1%}  random {share[1]:.1%};"
        f"  random STEER records marked experimental: {marks}/{steered_random}")
    for k, label in (("random", "random arm"), ("rules", "rules pack")):
        c = capability[k]
        lo, hi = c["drop_ci95_points"]
        say(f"  GSM8K {label:10s}: {c['steered']['acc']:.1%} (none {c['none']['acc']:.1%})  "
            f"drop {c['drop_points']:+.1f} [{lo:+.1f}, {hi:+.1f}]")
    c = capability["rules_minus_random"]
    say(f"  GSM8K rules minus random: {c['drop_points']:+.1f} points "
        f"[{c['drop_ci95_points'][0]:+.1f}, {c['drop_ci95_points'][1]:+.1f}]")
    say(f"  -> {result['verdict']['outcome']}   (random push itself "
        f"{'helps' if verdict['random_helps'] else 'does not detectably help'} vs t2)")
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
