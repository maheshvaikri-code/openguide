"""The pilot that sets a second model's steering gain (docs/preregistration/t0-second-model-pilot.md).

    python scripts/derive_steering_pack.py --profile granite   # first: the pack and its norm report
    python scripts/pilot_second_model.py --profile granite     # then: 20 conversations x (t2 + 3 gains)
                                                               #       and GSM8K, the first 300 problems
    python scripts/pilot_second_model.py --smoke               # pipeline check on OTHER seeds, tiny sample

The design and the selection rule are fixed by the spec and are not options. The runner refuses to start
unless the spec is committed and unmodified, the weights are the pinned revision, and the pack exists. Every
conversation is checkpointed, so a crash resumes without changing anything. Needs a GPU. ASCII-only output.
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

from benchmarks import models  # noqa: E402
from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.replicate_t0 import CONTRACT_HASH, SHOCKS, TURNS, code_state, load_progress, say  # noqa: E402

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-second-model-pilot.md")

# ── registered design (see the spec; not options) ─────────────────────
SEEDS = tuple(range(400, 420))
SMOKE_SEEDS = (940, 941)
GAINS = (0.025, 0.05, 0.075)
PILOT_CEILING = 0.075                 # raised above the default only for this pilot (spec, point 5)
GSM8K_FIRST_N, SMOKE_GSM8K_N = 300, 20
POOL = "v1"

OUT_DIR = os.path.join(ROOT, "benchmarks", "results", "granite-3.1-2b")
DB = os.path.join(ROOT, ".console-demo", "pilot.db")


def load_gsm8k_first(n: int) -> list[tuple[str, str | None]]:
    """The first ``n`` problems of the GSM8K test split, in dataset order (the pilot's registered sample)."""
    from datasets import load_dataset

    ds = load_dataset("openai/gsm8k", "main", split="test")
    return [(ds[i]["question"], t0.gsm8k_gold(ds[i]["answer"])) for i in range(n)]


def run_conversations(up, prof, configs: dict[str, SteeringConfig | None], seeds, store, blob: str,
                      progress: str) -> dict[str, list[dict]]:
    arms = list(configs)
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} of {len(arms) * len(seeds)} conversations already complete")
    for i, seed in enumerate(seeds):
        t = time.time()
        for arm in arms:
            if (seed, arm) in done:
                continue
            res = asyncio.run(rm.run_contract(up, seed, TURNS, store, shocks=SHOCKS, steering=configs[arm],
                                              arm=f"pilot-{arm}", pool=POOL, model_id=prof.served_name))
            row = {"spec_blob": blob, "seed": seed, "arm": arm, "run_id": res.run_id, "turns": res.turns,
                   "steered_turns": [r["turn"] for r in res.trace.records if r["ev"] == "STEER"]}
            with open(progress, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            done[(seed, arm)] = row
        rec = " | ".join(f"{a} {rp.recovery(done[(seed, a)]['turns']):.2f}" for a in arms)
        say(f"seed {seed} ({i + 1}/{len(seeds)}): recovery {rec}  [{time.time() - t:.0f}s]")
    return {arm: [done[(s, arm)] for s in seeds] for arm in arms}


def run_capability(up, prof, pack, gsm_n: int, progress: str) -> dict[str, list[int]]:
    """Per-question GSM8K correctness with no steering and with steering always on at each gain."""
    state = json.load(open(progress, encoding="utf-8")) if os.path.exists(progress) else {}
    gsm = load_gsm8k_first(gsm_n)
    for name, g in (("none", 0.0), *((f"g{g}", g) for g in GAINS)):
        if name in state:
            continue
        ctx = t0.steering_context(up.model, pack, prof.band, g, {"model": prof.served_name,
                                                                 "pack_hash": pack.hash()})
        flags = []
        for b in gate.batches(gsm, 20):
            replies = t0.generate_batch(up.model, up.tokenizer, gate.BASE_SYSTEM,
                                        [q + gate.GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
            flags += [int(t0.same_number(t0.extract_number(r), gold)) for r, (_, gold) in zip(replies, b)]
        state[name] = flags
        json.dump(state, open(progress, "w", encoding="utf-8"))
        say(f"  GSM8K {name:>7}: {sum(flags)}/{len(flags)}")
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="granite", choices=["granite"], help="the second model")
    ap.add_argument("--smoke", action="store_true", help="pipeline check on other seeds; no selection")
    args = ap.parse_args()
    prof = models.get(args.profile)

    spec = rp.spec_state(SPEC, ROOT)
    if not spec["ok"]:
        say(f"REFUSING TO RUN: {spec['reason']} ({spec['path']}). "
            "Commit the pilot rule first and do not edit it.")
        return 2
    ok, why = models.revision_ok(prof)
    if not ok:
        say(f"REFUSING TO RUN: {why}")
        return 2
    if not os.path.exists(prof.pack_path):
        say(f"REFUSING TO RUN: no pack at {prof.pack_path}; "
            f"run derive_steering_pack.py --profile {args.profile}")
        return 2
    if rm.compiled_contract().contract_hash != CONTRACT_HASH:
        say("REFUSING TO RUN: the contract is not the registered one")
        return 2

    seeds = SMOKE_SEEDS if args.smoke else SEEDS
    gsm_n = SMOKE_GSM8K_N if args.smoke else GSM8K_FIRST_N
    tag = ".smoke" if args.smoke else ""
    os.makedirs(OUT_DIR, exist_ok=True)
    progress = os.path.join(ROOT, "benchmarks", f"pilot_{prof.key}_progress.jsonl{tag}")
    cap_progress = os.path.join(ROOT, "benchmarks", f"pilot_{prof.key}_capability_progress.json{tag}")
    out_path = os.path.join(OUT_DIR, f"pilot{tag}.json")
    db = DB.replace(".db", f"{tag}.db")
    note = "  [SMOKE: not the registered pilot]" if args.smoke else ""
    say(f"spec {spec['path']} committed in {spec['commit'][:10]}; weights revision {why[:10]}{note}")

    say(f"loading {prof.path} ({prof.dtype}) ...")
    up = HFUpstream.from_pretrained(prof.path, served_name=prof.served_name, max_new_tokens=96,
                                    dtype=prof.dtype)
    if up.tokenizer.pad_token is None:
        up.tokenizer.pad_token = up.tokenizer.eos_token
    up.tokenizer.padding_side = "left"
    pack = SignalPack.load_safetensors(prof.pack_path)
    norms = json.load(open(prof.pack_path + ".norms.json", encoding="utf-8"))
    configs: dict[str, SteeringConfig | None] = {"t2": None}
    for g in GAINS:
        configs[f"g{g}"] = SteeringConfig(pack, prof.band, g, gain_ceiling=PILOT_CEILING)
    up.enable_steering(configs[f"g{GAINS[-1]}"])
    say(f"pack {pack.hash()[:19]}...  band layers {prof.band[0]}..{prof.band[1] - 1}  gains {GAINS}")
    os.makedirs(os.path.dirname(db), exist_ok=True)

    t = time.time()
    say(f"\n[A] {len(seeds)} conversations x {len(configs)} arms on pool {POOL} "
        f"({TURNS} turns, shocks at {SHOCKS})")
    convs = run_conversations(up, prof, configs, seeds, Store(db), spec["blob"], progress)

    say(f"\n[B] GSM8K, the first {gsm_n} problems, steering always on, per gain")
    band_pack = configs[f"g{GAINS[0]}"].pack_in_band()
    flags = run_capability(up, prof, band_pack, gsm_n, cap_progress)

    rows, detail = [], {}
    for g in GAINS:
        comp = rp.compare_conversations(convs["t2"], convs[f"g{g}"])
        acc = rp.compare_accuracy(flags["none"], flags[f"g{g}"])
        rows.append({"gain": g, "recovery_diff": comp["mean_diff"], "gsm8k_drop_points": acc["drop_points"]})
        detail[str(g)] = {"recovery": comp, "gsm8k": acc}
    choice = rp.pilot_choice(rows)

    import torch
    import transformers
    result = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "model": {"key": prof.key, "revision": why, "dtype": prof.dtype, "band": list(prof.band),
                  "pack_hash": pack.hash(), "norm_report": norms["layers"]},
        "design": {"gains": list(GAINS), "ceiling_for_pilot": PILOT_CEILING, "seeds": [seeds[0], seeds[-1]],
                   "n_conversations": len(seeds), "gsm8k_first_n": gsm_n, "pool": POOL, "turns": TURNS,
                   "shocks": list(SHOCKS)},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "rows": rows, "detail": detail,
        "selection": None if args.smoke else choice,
        "smoke_selection_if_it_were_real": choice if args.smoke else None,
        "gsm8k_flags": flags, "conversations": convs,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    say("\n== pilot ==")
    say("  gain    recovery gain (vs t2)   GSM8K drop (points)   eligible")
    for r in rows:
        say(f"  {r['gain']:<6g}  {r['recovery_diff']:+.3f}                  {r['gsm8k_drop_points']:+6.1f}"
            f"                {'yes' if r['gsm8k_drop_points'] <= rp.PILOT_MAX_DROP_POINTS + 1e-9 else 'no'}")
    say(f"  selection: {choice['chosen']}  ({choice['reason']})"
        + ("   [smoke: not a selection]" if args.smoke else ""))
    if choice.get("chosen_recovery_not_positive"):
        say("  NOTE: the chosen gain's pilot recovery gain is not positive; report it, do not auto-proceed.")
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
