"""The Granite gain ladder: GSM8K only (docs/preregistration/t0-granite-ladder.md).

    python scripts/granite_gain_ladder.py           # gains 0.0125 and 0.00625, GSM8K first 300 (~20 min)
    python scripts/granite_gain_ladder.py --smoke   # pipeline check on the first 20 problems; no statement

The design is fixed by the spec and is not an option. The runner refuses to start unless the spec is
committed and unmodified, the weights are the pinned revision, and the pack is the registered one. The
unsteered baseline is the registered pilot's; the first 40 problems are re-run unsteered and the runner
stops if they differ. ASCII-only output (Windows consoles).
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

from benchmarks import models  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from benchmarks import replication as rp  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from proxy.steering import SteeringConfig  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402
from scripts.pilot_second_model import load_gsm8k_first  # noqa: E402
from scripts.replicate_t0 import code_state, say  # noqa: E402

SPEC = os.path.join(ROOT, "docs", "preregistration", "t0-granite-ladder.md")
PILOT = os.path.join(ROOT, "benchmarks", "results", "granite-3.1-2b", "pilot_capability.json")
OUT_DIR = os.path.join(ROOT, "benchmarks", "results", "granite-3.1-2b")

# registered design (see the spec; not options)
GAINS = (0.0125, 0.00625)
GSM8K_FIRST_N, SMOKE_N = 300, 20
CHECK_N = 40
PACK_HASH = "sha256:2744d39efb975a6c456e2fa2ff3807db19a337c1866995cf4fb7a50bcedcd1b5"


def flags_for(up, prof, band_pack, problems, gain: float) -> list[int]:
    ctx = t0.steering_context(up.model, band_pack, prof.band, gain, {"model": prof.key})
    flags: list[int] = []
    for b in gate.batches(problems, 20):
        replies = t0.generate_batch(up.model, up.tokenizer, gate.BASE_SYSTEM,
                                    [q + gate.GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
        flags += [int(t0.same_number(t0.extract_number(r), gold)) for r, (_, gold) in zip(replies, b)]
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--smoke", action="store_true", help="pipeline check on 20 problems; no statement")
    args = ap.parse_args()
    prof = models.GRANITE

    spec = rp.spec_state(SPEC, ROOT)
    if not spec["ok"]:
        say(f"REFUSING TO RUN: {spec['reason']} ({spec['path']}). "
            "Commit the pre-registration first and do not edit it.")
        return 2
    ok, why = models.revision_ok(prof)
    if not ok:
        say(f"REFUSING TO RUN: {why}")
        return 2
    n = SMOKE_N if args.smoke else GSM8K_FIRST_N
    note = "  [SMOKE: not the registered run]" if args.smoke else ""
    say(f"spec {spec['path']} committed in {spec['commit'][:10]}; weights revision {why[:10]}{note}")

    say(f"loading {prof.path} ({prof.dtype}) ...")
    up = HFUpstream.from_pretrained(prof.path, served_name=prof.served_name, max_new_tokens=96,
                                    dtype=prof.dtype)
    if up.tokenizer.pad_token is None:
        up.tokenizer.pad_token = up.tokenizer.eos_token
    up.tokenizer.padding_side = "left"
    pack = SignalPack.load_safetensors(prof.pack_path)
    if pack.hash() != PACK_HASH:
        say("REFUSING TO RUN: the pack is not the registered one")
        return 2
    # an experiment by definition: Granite has no validation record (used only to build the band-only pack)
    cfg = SteeringConfig(pack, prof.band, GAINS[0], gain_ceiling=GAINS[0], experimental=True)
    band_pack = cfg.pack_in_band()

    pilot = json.load(open(PILOT, encoding="utf-8"))
    none = pilot["gsm8k_flags"]["none"][:n]
    problems = load_gsm8k_first(n)
    say(f"\nchecking determinism: re-running the first {min(CHECK_N, n)} problems unsteered ...")
    again = flags_for(up, prof, band_pack, problems[:min(CHECK_N, n)], 0.0)
    if again != none[:len(again)]:
        say("REFUSING TO CONTINUE: the unsteered results do not reproduce the pilot's")
        return 2
    say("  reproduced exactly")

    t = time.time()
    results = {}
    for g in GAINS:
        flags = flags_for(up, prof, band_pack, problems, g)
        results[str(g)] = {"flags": flags, **rp.compare_accuracy(none, flags)}
        r = results[str(g)]
        lo, hi = r["drop_ci95_points"]
        eligible = r["drop_points"] <= rp.PILOT_MAX_DROP_POINTS + 1e-9
        say(f"  gain {g:<8g}: {r['steered']['correct']}/{n}  drop {r['drop_points']:+.1f} points "
            f"[{lo:+.1f}, {hi:+.1f}]   {'eligible' if eligible else 'NOT eligible'}")
    drops = {g: results[str(g)]["drop_points"] for g in GAINS}
    statement = rp.ladder_outcome(drops)

    import torch
    import transformers
    out = {
        "smoke": args.smoke, "spec": spec, "code": code_state(),
        "model": {"key": prof.key, "revision": why, "dtype": prof.dtype, "band": list(prof.band),
                  "pack_hash": pack.hash()},
        "design": {"gains": list(GAINS), "gsm8k_first_n": n, "baseline": "pilot_capability.json (unsteered)"},
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__,
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "none_correct": sum(none), "results": results,
        "statement": "smoke: no statement" if args.smoke else statement,
    }
    path = os.path.join(OUT_DIR, "ladder.smoke.json" if args.smoke else "ladder.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    say(f"\n== {'smoke (not a statement)' if args.smoke else statement} ==")
    say(f"wrote {path}  ({time.time() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
