"""Run the pre-registered replication of drift-gated T0 steering (docs/preregistration/t0-replication.md).

    python scripts/replicate_t0.py           # the registered run: 60 conversations x 2 arms, then capability
    python scripts/replicate_t0.py --smoke   # pipeline check on OTHER seeds and tiny samples; no verdict

The design (gain, seeds, N, thresholds) is fixed by the spec and is not a command-line option. The runner
refuses to start unless the spec is committed and unmodified. Every conversation is checkpointed to a progress
file, so a crash resumes without changing anything (decoding is deterministic). Runs are stored in
.console-demo/replication.db. Needs the weights in .models/ and a GPU. ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.derive_steering_pack import DEFAULT_OUT as PACK_PATH  # noqa: E402

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-replication.md")

# ── registered design (see the spec; not options) ─────────────────────
SEEDS = tuple(range(100, 160))
TURNS = 16
SHOCKS = (4, 10)
GAIN = 0.05
GSM8K_N, MMLU_N = 300, 500
PACK_HASH = "sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f"
CONTRACT_HASH = "sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e"

# smoke mode: different seeds and tiny samples, so the registered seeds stay unseen
SMOKE_SEEDS, SMOKE_GSM8K_N, SMOKE_MMLU_N = (900, 901), 20, 40

OUT = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b", "replication_t0.json")
PROGRESS = os.path.join(ROOT, "benchmarks", "replication_t0_progress.jsonl")
CAP_PROGRESS = os.path.join(ROOT, "benchmarks", "replication_t0_capability_progress.json")
DB = os.path.join(ROOT, ".console-demo", "replication.db")


def say(msg: str) -> None:
    print(msg, flush=True)


def code_state() -> dict:
    """The commit this ran from and whether the code that matters was modified, so a result names its code."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--", "scripts", "benchmarks/replication.py",
                              "benchmarks/real_model.py", "proxy", "guidancegrid"))}


def load_progress(path: str, blob: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    if any(r.get("spec_blob") != blob for r in rows):
        raise SystemExit(f"{path} was written under a different spec; move it away to start over")
    return rows


def run_conversations(up, config, seeds, store, blob: str, progress: str) -> dict[str, list[dict]]:
    done = {(r["seed"], r["arm"]): r for r in load_progress(progress, blob)}
    if done:
        say(f"resuming: {len(done)} of {2 * len(seeds)} conversations already complete")
    for i, seed in enumerate(seeds):
        t = time.time()
        for arm, steering in (("t2", None), ("t2+t0", config)):
            if (seed, arm) in done:
                continue
            res = asyncio.run(rm.run_contract(
                up, seed, TURNS, store, shocks=SHOCKS, steering=steering,
                arm="rep-t2" if arm == "t2" else "rep-t2t0"))
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


def run_capability(up, pack, gsm_n: int, mmlu_n: int, progress: str) -> dict:
    state = json.load(open(progress, encoding="utf-8")) if os.path.exists(progress) else {}
    gsm, mmlu = gate.load_gsm8k(gsm_n), gate.load_mmlu(mmlu_n)
    conditions = (("none", 0.0), ("steered", GAIN))          # steered = ALWAYS on: the worst case for harm
    for name, g in conditions:
        ctx = gate.ctx_for(up, pack, g)
        if f"gsm8k_{name}" not in state:
            flags = []
            for b in gate.batches(gsm, 20):
                replies = t0.generate_batch(up.model, up.tokenizer, gate.BASE_SYSTEM,
                                            [q + gate.GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
                flags += [int(t0.same_number(t0.extract_number(r), gold)) for r, (_, gold) in zip(replies, b)]
            state[f"gsm8k_{name}"] = flags
            json.dump(state, open(progress, "w", encoding="utf-8"))
            say(f"  GSM8K {name:8s}: {sum(flags)}/{len(flags)}")
        if f"mmlu_{name}" not in state:
            flags = []
            for b in gate.batches(mmlu, 25):
                picks = t0.mmlu_scores(up.model, up.tokenizer, [p for p, _ in b], ctx)
                flags += [int(p == gold) for p, (_, gold) in zip(picks, b)]
            state[f"mmlu_{name}"] = flags
            json.dump(state, open(progress, "w", encoding="utf-8"))
            say(f"  MMLU  {name:8s}: {sum(flags)}/{len(flags)}")
    return {"gsm8k": rp.compare_accuracy(state["gsm8k_none"], state["gsm8k_steered"]),
            "mmlu": rp.compare_accuracy(state["mmlu_none"], state["mmlu_steered"])}


def print_result(result: dict) -> None:
    a, cap = result["analysis"], result["capability"]
    say("\n== result ==")
    say(f"  recovery  t2 {a['mean_recovery']['t2']:.3f}   t2+t0 {a['mean_recovery']['t2+t0']:.3f}")
    lo, hi = a["ci95"]
    say(f"  paired difference {a['mean_diff']:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
    say(f"  {a['wins']} wins / {a['ties']} ties / {a['losses']} losses  "
        f"(sign test p = {a['sign_test_p']:.3f})")
    d = a["drifting"]
    line = f"  drifting under t2: {d['n']} conversations" + (" (UNDERPOWERED)" if d["underpowered"] else "")
    if d["n"]:
        line += f"; difference {d['mean_diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"
    say(line)
    say(f"  steered {a['steered_share']:.1%} of turns; shortest reply {a['shortest_reply_words']} words, "
        f"{a['replies_under_3_words']} under 3 words")
    for k in ("gsm8k", "mmlu"):
        c = cap[k]
        lo, hi = c["drop_ci95_points"]
        say(f"  {k.upper():6s} none {c['none']['acc']:.1%}  steered {c['steered']['acc']:.1%}  "
            f"drop {c['drop_points']:+.1f} points [{lo:+.1f}, {hi:+.1f}]")
    v = result["verdict"]
    if v:
        helps = "PASS" if v["helps_pass"] else "FAIL"
        safe = "PASS" if v["no_harm_pass"] else "FAIL"
        note = "   (harm not ruled out)" if v["harm_not_ruled_out"] else ""
        say(f"  helps: {helps}   no harm: {safe}   -> {v['outcome']}{note}")


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
    gsm_n, mmlu_n = (SMOKE_GSM8K_N, SMOKE_MMLU_N) if args.smoke else (GSM8K_N, MMLU_N)
    tag = ".smoke" if args.smoke else ""
    progress, cap_progress = PROGRESS + tag, CAP_PROGRESS + tag
    out_path = OUT.replace(".json", ".smoke.json") if args.smoke else OUT
    db = DB.replace(".db", ".smoke.db") if args.smoke else DB
    say(f"spec {spec['path']} committed in {spec['commit'][:10]} (blob {spec['blob'][:10]})"
        f"{'  [SMOKE: not the registered run]' if args.smoke else ''}")

    if rm.compiled_contract().contract_hash != CONTRACT_HASH:
        say("REFUSING TO RUN: the contract is not the registered one")
        return 2
    say(f"loading {gate.MODEL} ...")
    up = HFUpstream.from_pretrained(gate.MODEL, served_name=rm.MODEL_ID, max_new_tokens=96)
    up.tokenizer.padding_side = "left"
    pack = SignalPack.load_safetensors(PACK_PATH)
    config = SteeringConfig(pack, gate.BAND, GAIN, expected_pack_hash=PACK_HASH)    # refuses any other pack
    up.enable_steering(config)
    say(f"pack {config.pack_hash[:19]}...  gain {GAIN}  band layers {gate.BAND[0]}..{gate.BAND[1] - 1}")
    os.makedirs(os.path.dirname(db), exist_ok=True)

    t = time.time()
    say(f"\n[A] {len(seeds)} conversations x 2 arms ({TURNS} turns, shocks at {SHOCKS})")
    convs = run_conversations(up, config, seeds, Store(db), spec["blob"], progress)
    analysis = rp.compare_conversations(convs["t2"], convs["t2+t0"])

    say(f"\n[B] capability: GSM8K n={gsm_n}, MMLU n={mmlu_n}, none vs steering always on at {GAIN}")
    capability = run_capability(up, config.pack_in_band(), gsm_n, mmlu_n, cap_progress)

    import torch
    import transformers
    result = {
        "smoke": args.smoke,
        "spec": spec,
        "code": code_state(),
        "design": {"gain": GAIN, "seeds": [seeds[0], seeds[-1]], "n_conversations": len(seeds),
                   "turns": TURNS,
                   "shocks": list(SHOCKS), "gsm8k_n": gsm_n, "mmlu_n": mmlu_n, "pack_hash": config.pack_hash,
                   "contract_hash": CONTRACT_HASH},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "analysis": analysis, "capability": capability,
        "verdict": None if args.smoke else rp.verdict(analysis, capability),
        "conversations": convs,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    print_result(result)
    say(f"\nwrote {out_path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
