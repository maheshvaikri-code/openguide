"""Derive a T0 steering pack for the local model and save it, ready for the proxy (ADR-003).

    python scripts/derive_steering_pack.py        # -> .models/steering/qwen2.5-1.5b-instruct.safetensors

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

from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402
from scripts import real_t0_gate as gate  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, ".models", "steering", "qwen2.5-1.5b-instruct.safetensors")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=gate.MODEL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    print(f"loading {args.model} ...", flush=True)
    up = HFUpstream.from_pretrained(args.model, served_name=rm.MODEL_ID, max_new_tokens=96)
    up.tokenizer.padding_side = "left"
    pack = gate.derive(up)
    layers = [layer for layer in range(*gate.BAND) if pack.get(t0.SIGNAL, layer) is not None]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    digest = pack.save_safetensors(args.out)
    print(f"saved {args.out}")
    print(f"  model id   : {pack.model_id}   hidden size {pack.d}")
    print(f"  band       : layers {gate.BAND[0]}..{gate.BAND[1] - 1}  ({len(layers)} with a direction)")
    print(f"  derived on : {len(gate.DERIVATION_PROMPTS)} held-out prompts")
    print(f"  pack hash  : {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
