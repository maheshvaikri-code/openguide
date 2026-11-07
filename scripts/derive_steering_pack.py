"""Derive a T0 steering pack for a local model and save it, ready for the proxy (ADR-003).

    python scripts/derive_steering_pack.py                    # Qwen2.5-1.5B (the default profile)
    python scripts/derive_steering_pack.py --profile granite  # Granite-3.1-2B, its band mapped to its depth

The pack goes to .models/steering/<model>.safetensors, with a norm report beside it.

The direction is the mean difference of the model's residual stream at the last prompt token between
"the system prompt states the rules" and "it does not", per layer in a fixed band, scaled to the typical
residual norm there. It is derived on held-out prompts that no evaluation uses. A pack belongs to one
model: the proxy refuses a pack whose hidden size or layer range does not fit.
Needs the weights in .models/ and (for speed) a GPU. ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import json  # noqa: E402

import numpy as np  # noqa: E402

from benchmarks import models  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402

DEFAULT_OUT = models.QWEN.pack_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default="qwen", choices=sorted(models.PROFILES), help="which model")
    ap.add_argument("--model", default=None, help="override the weights path of the profile")
    ap.add_argument("--out", default=None, help="where to write the pack (default: the profile's pack path)")
    args = ap.parse_args()
    prof = models.get(args.profile)
    path = args.model or prof.path
    out = args.out or prof.pack_path
    if args.model is None:
        ok, why = models.revision_ok(prof)
        if not ok:
            print(f"REFUSING: {why}")
            return 2
        print(f"weights revision: {why}")

    print(f"loading {path} ({prof.dtype}) ...", flush=True)
    up = HFUpstream.from_pretrained(path, served_name=prof.served_name, max_new_tokens=96, dtype=prof.dtype)
    if up.tokenizer.pad_token is None:
        up.tokenizer.pad_token = up.tokenizer.eos_token
    up.tokenizer.padding_side = "left"
    pack = gate.derive(up, band=prof.band, key=prof.key)
    layers = [layer for layer in range(*prof.band) if pack.get(t0.SIGNAL, layer) is not None]
    typical = up._typical_residual_norms(prof.n_layers)
    report = {layer: {"pack_norm": float(np.linalg.norm(pack.get(t0.SIGNAL, layer))),
                      "typical_residual_norm_on_a_fixed_sequence": typical.get(layer)} for layer in layers}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    digest = pack.save_safetensors(out)
    with open(out + ".norms.json", "w", encoding="utf-8") as f:
        json.dump({"model": prof.key, "band": list(prof.band), "pack_hash": digest, "layers": report},
                  f, indent=1)
    print(f"saved {out}")
    print(f"  model id   : {pack.model_id}   hidden size {pack.d}   dtype {prof.dtype}")
    print(f"  band       : layers {prof.band[0]}..{prof.band[1] - 1}  ({len(layers)} with a direction)")
    print(f"  derived on : {len(gate.DERIVATION_PROMPTS)} held-out prompts")
    for layer in layers:
        r = report[layer]
        resid = r["typical_residual_norm_on_a_fixed_sequence"]
        print(f"  layer {layer:>2}: pack norm {r['pack_norm']:8.2f} | typical residual norm {resid:8.2f}")
    print(f"  pack hash  : {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
