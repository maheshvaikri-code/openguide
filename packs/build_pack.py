"""Build a starter SignalPack from labeled contrast activations.

A pack holds the four reference signals — anchor, precision, explore, syc-damp —
as per-layer steering vectors derived by contrast (unit(mean(pos) - mean(neg))).
Real packs derive vectors from activations captured on a target model; this
script accepts either captured activations (a .npz of pos/neg stacks per signal)
or, with --synthetic, generates a deterministic toy pack for tests and demos.

    python packs/build_pack.py --synthetic --model qwen2.5-7b --out packs/qwen2.5-7b/

Writes:
    pack.safetensors   - content-addressed steering vectors
    eval_card.json     - pack hash, signals, layers, and eval slots (MMLU delta,
                         coherence) to be filled by the offline eval harness.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from guidancegrid.core.grid import SignalPack

SIGNALS = ["anchor", "precision", "explore", "syc-damp"]


def synthetic_pack(model_id: str, layers: int, d: int, seed: int = 7) -> SignalPack:
    rng = np.random.default_rng(seed)
    pack = SignalPack(model_id, d)
    for si, name in enumerate(SIGNALS):
        for layer in range(layers):
            pos = rng.standard_normal((16, d)) + (0.4 + 0.1 * si)
            neg = rng.standard_normal((16, d))
            pack.derive_contrast(name, pos[:, None, :].repeat(layers, 1),
                                 neg[:, None, :].repeat(layers, 1), range(layer, layer + 1))
    return pack


def eval_card(pack: SignalPack, model_id: str, layers: int) -> dict:
    return {
        "model_id": model_id,
        "pack_hash": pack.hash(),
        "signals": SIGNALS,
        "layers": layers,
        "dim": pack.d,
        # filled by the offline eval harness against a real model:
        "evals": {
            "mmlu_delta_at_gain": {"0.2": None, "0.4": None, "0.6": None},
            "gsm8k_delta_at_gain": {"0.2": None, "0.4": None, "0.6": None},
            "coherence_ok": None,
        },
        "status": "synthetic" if "synthetic" in model_id else "derived",
        "note": "MMLU/GSM8K deltas require a real model + GPU; see scripts/qwen_t0_gate.py.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="synthetic-7b")
    ap.add_argument("--layers", type=int, default=32)
    ap.add_argument("--dim", type=int, default=64)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--out", default="packs/synthetic/")
    args = ap.parse_args()

    if not args.synthetic:
        raise SystemExit("only --synthetic is supported offline; real derivation needs captured activations")

    os.makedirs(args.out, exist_ok=True)
    pack = synthetic_pack(args.model, args.layers, args.dim)
    h = pack.save_safetensors(os.path.join(args.out, "pack.safetensors"))
    card = eval_card(pack, args.model, args.layers)
    with open(os.path.join(args.out, "eval_card.json"), "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2)
    print(f"wrote pack {h} for {args.model} -> {args.out}")


if __name__ == "__main__":
    main()
