"""Exploratory diagnostics: why was Granite more sensitive to steering than Qwen? (REPORT 7.7, "Diagnostics")

    python scripts/diagnose_granite_sensitivity.py --d2   # how much does each layer write? (no generation)
    python scripts/diagnose_granite_sensitivity.py --d1   # random-direction control on Granite (GPU; ~25 min)

EXPLORATORY: nothing here is pre-registered and nothing here changes a pilot's verdict. D1 uses the
registered pilot's unsteered GSM8K results as its baseline (the same first 300 problems, deterministic
decoding). D2 measures, on one fixed chat, the median over tokens of ||layer output - layer input|| /
||layer input|| for every decoder layer of both models, and compares the steering push with it.
ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import diagnostics as diag  # noqa: E402
from benchmarks import models  # noqa: E402
from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import STEER_SIGNAL, SignalPack  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.pilot_second_model import load_gsm8k_first  # noqa: E402

OUT = os.path.join(ROOT, "benchmarks", "results", "granite-3.1-2b", "diagnostics.json")
PILOT = os.path.join(ROOT, "benchmarks", "results", "granite-3.1-2b", "pilot_capability.json")
RANDOM_SEEDS = (0, 1, 2)
D1_GAIN = 0.025
GSM8K_N = 300
FIXED_CHAT = [
    {"role": "system", "content": rm.SYSTEM_PROMPT},
    {"role": "user", "content": "How do I reset my password?"},
    {"role": "assistant", "content": "Open Settings, tap Account, then choose Reset Password. [END]"},
]
# the push is shown at the gains each model was actually tried at
PUSH_GAINS = {"qwen": (0.05,), "granite": (0.025, 0.05, 0.075)}


def say(msg: str) -> None:
    print(msg, flush=True)


def code_state() -> dict:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--", "scripts", "benchmarks", "proxy",
                              "guidancegrid"))}


def load(prof):
    up = HFUpstream.from_pretrained(prof.path, served_name=prof.served_name, max_new_tokens=96,
                                    dtype=prof.dtype)
    if up.tokenizer.pad_token is None:
        up.tokenizer.pad_token = up.tokenizer.eos_token
    up.tokenizer.padding_side = "left"
    return up


def run_d2() -> dict:
    """Write size per layer for both models, and the push-to-write ratio over each model's band."""
    out = {}
    for key in ("qwen", "granite"):
        prof = models.get(key)
        say(f"\n[D2] {prof.key}: loading ({prof.dtype}) ...")
        up = load(prof)
        ids = up.tokenizer.apply_chat_template(FIXED_CHAT, tokenize=True, return_tensors="pt",
                                               return_dict=True)
        input_ids = ids["input_ids"]
        stats = diag.layer_write_stats(up.model, input_ids)
        stats_skip = diag.layer_write_stats(up.model, input_ids, skip_first=True)
        pack = SignalPack.load_safetensors(prof.pack_path)
        pack_norms = {layer: float(np.linalg.norm(pack.get(STEER_SIGNAL, layer)))
                      for layer in range(*prof.band)}
        push = {str(g): diag.push_to_write(g, prof.band, prof.n_layers, pack_norms, stats)
                for g in PUSH_GAINS[key]}
        band_write = [stats[layer]["median_write_ratio"] for layer in range(*prof.band)]
        out[key] = {
            "model": prof.key, "n_layers": prof.n_layers, "band": list(prof.band),
            "tokens": int(input_ids.shape[1]),
            "layers": {str(i): {**stats[i], "median_write_ratio_skipping_first_token":
                                stats_skip[i]["median_write_ratio"]} for i in stats},
            "band_median_write_ratio": float(np.median(band_write)),
            "push_to_write": {g: {str(layer): v for layer, v in d.items()} for g, d in push.items()},
            "push_to_write_band_median": {g: float(np.median(list(d.values()))) for g, d in push.items()},
        }
        del up
        import gc

        import torch
        gc.collect()
        torch.cuda.empty_cache()
    return out


def print_d2(d2: dict) -> None:
    say("\n== D2: how much does each layer write? (median over tokens of ||out - in|| / ||in||) ==")
    say("  layer | qwen (28)  | granite (40)")
    q, g = d2["qwen"]["layers"], d2["granite"]["layers"]
    for i in range(max(len(q), len(g))):
        qa = f"{q[str(i)]['median_write_ratio']:.3f}" if str(i) in q else "  -  "
        ga = f"{g[str(i)]['median_write_ratio']:.3f}" if str(i) in g else "  -  "
        mark_q = "*" if d2["qwen"]["band"][0] <= i < d2["qwen"]["band"][1] else " "
        mark_g = "*" if d2["granite"]["band"][0] <= i < d2["granite"]["band"][1] else " "
        say(f"  {i:>5} | {qa}{mark_q}     | {ga}{mark_g}")
    say("  (* = inside that model's steering band)")
    for key in ("qwen", "granite"):
        r = d2[key]
        say(f"\n  {key}: band median write ratio {r['band_median_write_ratio']:.3f}")
        for gain, v in r["push_to_write_band_median"].items():
            say(f"    steering at gain {gain}: push / write, median over the band = {v:.2f}")
    ratio = d2["granite"]["band_median_write_ratio"] / d2["qwen"]["band_median_write_ratio"]
    say(f"\n  Granite writes {ratio:.2f}x what Qwen writes per layer, over each model's own band")


def run_d1() -> dict:
    """Random directions with the pack's per-layer norms, Granite, gain 0.025, GSM8K first 300, always on."""
    prof = models.GRANITE
    pilot = json.load(open(PILOT, encoding="utf-8"))
    flags_none = pilot["gsm8k_flags"]["none"]
    flags_pack = pilot["gsm8k_flags"][f"g{D1_GAIN}"]
    say(f"[D1] baseline from the registered pilot: none {sum(flags_none)}/{len(flags_none)}, "
        f"rules pack at {D1_GAIN}: {sum(flags_pack)}/{len(flags_pack)}")
    say(f"\n[D1] loading {prof.key} ({prof.dtype}) ...")
    up = load(prof)
    pack = SignalPack.load_safetensors(prof.pack_path)
    gsm = load_gsm8k_first(GSM8K_N)
    progress = os.path.join(ROOT, "benchmarks", "diagnostics_d1_progress.json")
    state = json.load(open(progress, encoding="utf-8")) if os.path.exists(progress) else {}
    for seed in RANDOM_SEEDS:
        if str(seed) in state:
            continue
        rnd = diag.random_direction_pack(pack, prof.band, seed)
        ctx = t0.steering_context(up.model, rnd, prof.band, D1_GAIN, {"model": prof.key, "random_seed": seed})
        flags = []
        for b in gate.batches(gsm, 20):
            replies = t0.generate_batch(up.model, up.tokenizer, gate.BASE_SYSTEM,
                                        [q + gate.GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
            flags += [int(t0.same_number(t0.extract_number(r), gold)) for r, (_, gold) in zip(replies, b)]
        state[str(seed)] = flags
        json.dump(state, open(progress, "w", encoding="utf-8"))
        say(f"  random direction, seed {seed}: {sum(flags)}/{len(flags)}")
    rows = {str(s): rp.compare_accuracy(flags_none, state[str(s)]) for s in RANDOM_SEEDS}
    rows["rules_pack"] = rp.compare_accuracy(flags_none, flags_pack)
    return {"gain": D1_GAIN, "n": GSM8K_N, "results": rows, "flags": {s: state[s] for s in state}}


def print_d1(d1: dict) -> None:
    say(f"\n== D1: random directions (same per-layer norms), Granite, gain {d1['gain']}, "
        f"first {d1['n']} problems ==")
    say("  arm                   accuracy   drop vs none, 95% CI (points)")
    for name, r in d1["results"].items():
        lo, hi = r["drop_ci95_points"]
        label = "rules pack (registered)" if name == "rules_pack" else f"random direction, seed {name}"
        say(f"  {label:<22} {r['steered']['acc']:.1%}    {r['drop_points']:+5.1f}  [{lo:+.1f}, {hi:+.1f}]")
    drops = [r["drop_points"] for n, r in d1["results"].items() if n != "rules_pack"]
    say(f"  random directions: mean drop {np.mean(drops):+.1f} points "
        f"(range {min(drops):+.1f} to {max(drops):+.1f})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--d1", action="store_true", help="random-direction control (GPU, ~25 min)")
    ap.add_argument("--d2", action="store_true", help="write size per layer for both models")
    args = ap.parse_args()
    if not (args.d1 or args.d2):
        args.d1 = args.d2 = True
    result = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    result.update({"exploratory": True, "code": code_state()})
    if args.d2:
        result["d2"] = run_d2()
        print_d2(result["d2"])
    if args.d1:
        result["d1"] = run_d1()
        print_d1(result["d1"])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    say(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
