"""Five more random-direction draws on Qwen2.5-1.5B (docs/preregistration/t0-direction-draws.md).

    python scripts/replicate_direction_draws.py           # 5 draws x 60 conversations + GSM8K each (~3.5 h)
    python scripts/replicate_direction_draws.py --smoke   # pipeline check: OTHER seeds, one draw, 20 problems

The design is fixed by the spec and is not an option. The runner refuses to start unless the spec is committed
and unmodified, the prompt pool, contract and every pack are the registered ones, each random pack is
near-orthogonal to the rules pack, and a re-run of three conversations reproduces the committed t2 and rules
arms reply for reply. The t2 and rules arms are reused from direction_control.json; only random arms are run.
Every random arm is an experiment under the guard (experimental=True) and is marked in the trace. Every
conversation is checkpointed. Needs a GPU. ASCII-only output.
"""
from __future__ import annotations

import argparse
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
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.replicate_direction_control import GSM8K_N, gsm8k_flags, run_arm  # noqa: E402
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

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-direction-draws.md")

# registered design (see the spec; not options)
SEEDS = tuple(range(600, 660))
SMOKE_SEEDS = (960, 961)
CHECK_SEEDS = (600, 601, 602)
MAX_COSINE = 0.05
DRAWS = {                                  # random-pack seed -> the hash the spec pins
    31415: "sha256:9b2083afdbce840f2a64966a2bf954f320085309cf320aad7e17d344c74cc7bf",
    27183: "sha256:f643be029dce5d3d68791e76717d1b76e7ac7b647905063b2f1d775870ebf91d",
    16180: "sha256:ce4880797ba50af9faa6da0bb810c02442c9dd7c5881adb2c5c99430a13e0be7",
    14142: "sha256:1476272ff428ea47589091f556cc426c9bd79074a6a517b3d55b66f4972639b3",
    13579: "sha256:16fc2906bc1b204bc3c78bd90575c27f30a237d1b4814a50c0047c250ecafe1b",
}
SMOKE_GSM8K_N, CHECK_N = 20, 40

RES = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b")
ORIGINAL = os.path.join(RES, "direction_control.json")
FLAGS = os.path.join(RES, "replication_pool2_gsm8k_flags.json")
OUT = os.path.join(RES, "direction_draws.json")
PROGRESS = os.path.join(ROOT, "benchmarks", "direction_draws_progress.jsonl")
CAP_PROGRESS = os.path.join(ROOT, "benchmarks", "direction_draws_capability_progress.json")
DB = os.path.join(ROOT, ".console-demo", "replication.db")


def arm_label(seed: int) -> str:
    return f"draw{seed}"


def worst_diff(reference, convs, sign: int = 1) -> float:
    ref, arm = rp._recoveries(reference), rp._recoveries(convs)
    return min(sign * (ref[s] - arm[s]) for s in ref)


def draw_summary(rules, t2, convs) -> dict:
    turns = [t for c in convs for t in c["turns"]]
    rec = rp._recoveries(convs)
    return {
        "mean_recovery": sum(rec.values()) / len(rec),
        "steered_share": sum(len(c["steered_turns"]) for c in convs) / len(turns),
        "worst_rules_minus_random": worst_diff(rules, convs),
        "worst_random_minus_t2": worst_diff(t2, convs, sign=-1),
        "not_english_replies": sum(rp.not_english(t["reply"]) for t in turns),
        "replies": len(turns),
        "steer_records": sum(len(c["steered_turns"]) for c in convs),
        "marked_experimental": sum(c["experimental_marks"] for c in convs),
    }


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
    original = json.load(open(ORIGINAL, encoding="utf-8"))
    ref = original["design"]
    if (ref["rules_pack_hash"], ref["pool_checksum"], ref["contract_hash"], ref["gain"]) != (
            PACK_HASH, POOL_CHECKSUM, CONTRACT_HASH, GAIN) or ref["seeds"] != [SEEDS[0], SEEDS[-1]]:
        say("REFUSING TO RUN: direction_control.json is not the study this one is registered against")
        return 2
    ref_t2 = original["conversations"]["t2"]
    ref_rules = original["conversations"]["rules"]
    if [c["seed"] for c in ref_t2] != list(SEEDS) or [c["seed"] for c in ref_rules] != list(SEEDS):
        say("REFUSING TO RUN: the reference arms do not cover seeds 600-659")
        return 2

    seeds = SMOKE_SEEDS if args.smoke else SEEDS
    draws = dict(list(DRAWS.items())[:1]) if args.smoke else DRAWS
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
    if up.tokenizer.pad_token is None:
        up.tokenizer.pad_token = up.tokenizer.eos_token
    up.tokenizer.padding_side = "left"                      # batched GSM8K generation needs left padding
    rules_pack = SignalPack.load_safetensors(prof.pack_path)
    if rules_pack.hash() != PACK_HASH:
        say("REFUSING TO RUN: the rules pack is not the registered one")
        return 2
    packs, cosines = {}, {}
    for seed, pinned in draws.items():
        pack = diag.random_direction_pack(rules_pack, prof.band, seed)
        cosines[seed] = diag.max_abs_layer_cosine(rules_pack, pack, prof.band)
        if pack.hash() != pinned:
            say(f"REFUSING TO RUN: the random pack for seed {seed} is not the registered one")
            return 2
        if cosines[seed] > MAX_COSINE:
            say(f"REFUSING TO RUN: the random pack for seed {seed} is not near-orthogonal "
                f"(largest |cosine| {cosines[seed]:.4f})")
            return 2
        packs[seed] = pack
    say(f"  {len(packs)} random packs match their pinned hashes; largest |cosine| with the rules pack "
        f"{max(cosines.values()):.4f}")

    cfg_rules = SteeringConfig(rules_pack, prof.band, GAIN, expected_pack_hash=PACK_HASH)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    store, blob = Store(db), spec["blob"]
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} conversations already complete")
    t = time.time()

    # the reference arms: reused from the committed study, after proving a re-run reproduces them
    determinism: list[dict] = []
    if args.smoke:
        say("\n[smoke] no committed reference for the smoke seeds: running t2 and rules on them")
        run_arm(up, "t2", None, seeds, store, blob, progress, done)
        up.enable_steering(cfg_rules)
        run_arm(up, "rules", cfg_rules, seeds, store, blob, progress, done)
        ref_t2 = [done[(s, "t2")] for s in seeds]
        ref_rules = [done[(s, "rules")] for s in seeds]
    else:
        say(f"\n[check] re-running seeds {list(CHECK_SEEDS)} under t2 and rules; "
            "they must match the committed arms")
        run_arm(up, "check-t2", None, CHECK_SEEDS, store, blob, progress, done)
        up.enable_steering(cfg_rules)
        assert up.steering_authorisation.mode == "validated"
        run_arm(up, "check-rules", cfg_rules, CHECK_SEEDS, store, blob, progress, done)
        committed = {"t2": {c["seed"]: c for c in ref_t2}, "rules": {c["seed"]: c for c in ref_rules}}
        for arm in ("t2", "rules"):
            for s in CHECK_SEEDS:
                same = rp.same_conversation(committed[arm][s]["turns"], done[(s, f"check-{arm}")]["turns"])
                determinism.append({"arm": arm, "seed": s, "identical": same})
        bad = [d for d in determinism if not d["identical"]]
        if bad:
            say(f"REFUSING TO CONTINUE: a re-run did not reproduce the committed arms: {bad}")
            return 2
        say(f"  all {len(determinism)} re-runs identical to the committed conversations")

    say(f"\n[A] {len(draws)} random draw(s) x {len(seeds)} conversations (experimental, marked in the trace)")
    for seed in draws:
        say(f"draw {seed}")
        cfg = SteeringConfig(packs[seed], prof.band, GAIN, expected_pack_hash=draws[seed],
                             experimental=True, gain_ceiling=GAIN)
        up.enable_steering(cfg)
        assert up.steering_authorisation.mode == "experimental"
        run_arm(up, arm_label(seed), cfg, seeds, store, blob, progress, done)
    by_draw = {seed: [done[(s, arm_label(seed))] for s in seeds] for seed in draws}

    for seed, convs in by_draw.items():
        records = sum(len(c["steered_turns"]) for c in convs)
        marked = sum(c["experimental_marks"] for c in convs)
        if records != marked:
            say(f"REFUSING TO WRITE A RESULT: draw {seed} has {records - marked} unmarked STEER records")
            return 2

    rules_vs_random = rp.across_draws(ref_rules, by_draw)
    random_vs_t2 = rp.across_draws(ref_t2, by_draw, sign=-1)
    verdict = rp.draws_verdict(rules_vs_random, random_vs_t2)
    summaries = {seed: draw_summary(ref_rules, ref_t2, convs) for seed, convs in by_draw.items()}

    say(f"\n[B] GSM8K, {gsm_n} problems, per draw, steering always on at {GAIN}")
    flags = json.load(open(FLAGS, encoding="utf-8"))
    none = flags["gsm8k_none"][:gsm_n]
    problems = gate.load_gsm8k(GSM8K_N)[:gsm_n]
    check = min(CHECK_N, gsm_n)
    if gsm8k_flags(up, diag_pack_for_check(packs), problems[:check], 0.0) != none[:check]:
        say("REFUSING TO CONTINUE: the unsteered results do not reproduce the committed ones")
        return 2
    say(f"  unsteered baseline reproduced on the first {check} problems")
    state = json.load(open(cap_progress, encoding="utf-8")) if os.path.exists(cap_progress) else {}
    for seed in draws:
        if str(seed) not in state:
            cfg = SteeringConfig(packs[seed], prof.band, GAIN, expected_pack_hash=draws[seed],
                                 experimental=True, gain_ceiling=GAIN)
            state[str(seed)] = gsm8k_flags(up, cfg.pack_in_band(), problems, GAIN)
            json.dump(state, open(cap_progress, "w", encoding="utf-8"))
            c = rp.compare_accuracy(none, state[str(seed)])
            say(f"  draw {seed}: {c['steered']['acc']:.1%} (none {c['none']['acc']:.1%})  "
                f"drop {c['drop_points']:+.1f}")
    capability = {str(seed): rp.compare_accuracy(none, state[str(seed)]) for seed in draws}
    mean_drop = sum(c["drop_points"] for c in capability.values()) / len(capability)

    import torch
    import transformers
    result = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "design": {"gain": GAIN, "pool": POOL, "pool_checksum": POOL_CHECKSUM, "seeds": [seeds[0], seeds[-1]],
                   "n_conversations": len(seeds), "turns": TURNS, "shocks": list(SHOCKS),
                   "rules_pack_hash": PACK_HASH, "contract_hash": CONTRACT_HASH, "gsm8k_n": gsm_n,
                   "draws": {str(s): {"pack_hash": h, "max_abs_cosine_with_rules": cosines[s]}
                             for s, h in draws.items()},
                   "max_cosine_allowed": MAX_COSINE},
        "reference": {"file": "benchmarks/results/qwen2.5-1.5b/direction_control.json",
                      "spec_commit": original["spec"]["commit"], "code_commit": original["code"]["commit"],
                      "note": "t2 and rules arms are read from that file, not copied"},
        "determinism_check": determinism,
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "analysis": {"rules_vs_random": rules_vs_random, "random_vs_t2": random_vs_t2,
                     "per_draw_summary": {str(s): v for s, v in summaries.items()}},
        "original_draw": {"seed": original["design"]["random_seed"],
                          "rules_vs_random": {k: original["analysis"]["rules_vs_random"][k]
                                              for k in ("mean_diff", "ci95", "wins", "ties", "losses")},
                          "random_vs_t2": {k: original["analysis"]["random_vs_t2"][k]
                                           for k in ("mean_diff", "ci95", "wins", "ties", "losses")},
                          "gsm8k_drop_points": original["capability"]["random"]["drop_points"],
                          "enters_no_decision": True},
        "verdict": {**verdict, "outcome": "smoke: no verdict"} if args.smoke else verdict,
        "capability": {"per_draw": capability, "mean_drop_points": mean_drop},
        "conversations": {str(s): c for s, c in by_draw.items()},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    say("\n== result ==")
    for key, label in (("rules_vs_random", "rules - random"), ("random_vs_t2", "random - t2")):
        a = result["analysis"][key]
        say(f"  {label:15s} (draw-averaged) {a['mean_diff']:+.3f}  "
            f"95% CI [{a['ci95'][0]:+.3f}, {a['ci95'][1]:+.3f}]"
            f"   draws ahead {a['draws_positive']}/{a['n_draws']}  (one-sided p {a['draw_sign_p']:.4f})")
        for s, v in a["per_draw"].items():
            say(f"      draw {s}: {v['mean_diff']:+.3f} [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]  "
                f"{v['wins']} wins / {v['ties']} ties / {v['losses']} losses")
        sp = a["spread"]
        say(f"      spread across draws: min {sp['min']:+.3f}  max {sp['max']:+.3f}  sd {sp['sd']:.3f}")
    say(f"  mean GSM8K drop over draws: {mean_drop:+.1f} points")
    say(f"  -> {verdict['outcome']}  (random push helps on average: {verdict['random_helps_on_average']})"
        if not args.smoke else "  -> smoke: no verdict")
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


def diag_pack_for_check(packs):
    """The band-only pack for the unsteered baseline check (any draw's pack: the gain is 0, so no effect)."""
    first = next(iter(packs.values()))
    return SteeringConfig(first, models.QWEN.band, GAIN, experimental=True, gain_ceiling=GAIN).pack_in_band()


if __name__ == "__main__":
    raise SystemExit(main())
