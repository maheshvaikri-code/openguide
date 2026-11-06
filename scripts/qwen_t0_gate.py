"""Phase 4 gate harness: T0 activation steering, measured end to end.

Two modes:

  run_synthetic_gate()  - CI-runnable. A tiny torch model + a probe whose
      direction is the ANCHOR steering direction, so injecting ANCHOR provably
      raises the probe-measured adherence vs a no-grid baseline. Exercises the
      real hook path, records to a Trace, and checks replay identity. This is a
      mechanical demonstration of the closed loop, NOT a capability-retention
      result.

  The REAL gate is scripts/real_t0_gate.py (measured on Qwen2.5-1.5B-Instruct with local
      weights and a GPU; not run in CI). The blueprint's 7B/8B gate is still unrun here.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from guidancegrid.channels.t0_activation import ActivationSteerer  # noqa: E402
from guidancegrid.core.grid import Grid, SignalPack  # noqa: E402
from guidancegrid.sensors import LinearProbe  # noqa: E402


# ── synthetic gate (CI) ─────────────────────────────────────────────────
def _tiny(d, n):
    import torch.nn as nn

    class Layer(nn.Module):
        def __init__(s):
            super().__init__()
            s.lin = nn.Linear(d, d)

        def forward(s, h):
            return (h + 0.05 * __import__("torch").tanh(s.lin(h)),)

    class Inner(nn.Module):
        def __init__(s):
            super().__init__()
            s.layers = nn.ModuleList([Layer() for _ in range(n)])

        def forward(s, h):
            for layer in s.layers:
                h = layer(h)[0]
            return h

    class Model(nn.Module):
        def __init__(s):
            super().__init__()
            s.model = Inner()

        def forward(s, h):
            return s.model(h)

    return Model()


def run_synthetic_gate(steps: int = 50, d: int = 16, n: int = 6,
                       probe_layer: int = 4, seed: int = 0) -> dict:
    import torch

    rng = np.random.default_rng(seed)
    pack = SignalPack("synthetic", d)
    dirs = {}
    for layer in range(n):
        v = rng.standard_normal(d).astype(np.float32)
        v /= np.linalg.norm(v)
        pack.set_vector("anchor", layer, v)
        dirs[layer] = v
    # probe reads along the ANCHOR direction at probe_layer (b=0 -> baseline ~0.5)
    probe = LinearProbe(probe_layer, dirs[probe_layer], b=0.0)
    manifest = {"model": "synthetic", "pack_hash": pack.hash(), "runtime": "ggrid-t0-gate-0.1"}
    x = torch.ones(1, 3, d)

    def measure(grid):
        torch.manual_seed(seed)
        model = _tiny(d, n).eval()
        captured = {}

        def cap(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            captured["x"] = h[0, -1].detach().cpu().numpy()
            return out

        steerer = None
        if grid is not None:
            steerer = ActivationSteerer(grid, pack, manifest, num_layers=n).register(model=model)
        cap_handle = model.model.layers[probe_layer].register_forward_hook(cap)
        scores = []
        with torch.no_grad():
            for _ in range(steps):
                model(x)
                scores.append(probe.score(captured["x"]))
        cap_handle.remove()
        if steerer is not None:
            steerer.remove()
        return float(np.mean(scores)), steerer

    baseline, _ = measure(None)
    grid = Grid(n, frame=16)
    grid.field("anchor").write_ramp(0, n - 1, 0, steps, 0.1, 0.8)
    steered, steerer = measure(grid)

    # replay identity: same setup -> same trace head
    _, steerer2 = measure(grid)

    return {
        "baseline_adherence": round(baseline, 4),
        "steered_adherence": round(steered, 4),
        "improved": steered > baseline,
        "delta": round(steered - baseline, 4),
        "trace_verified": steerer.trace.verify(),
        "replay_identical": steerer.trace.head == steerer2.trace.head,
        "steps": steps,
    }


# ── real gate (requires weights + GPU) ──────────────────────────────────
def run_real_gate(model_id: str, steps: int = 50) -> dict:  # pragma: no cover
    raise NotImplementedError(
        "The real gate lives in scripts/real_t0_gate.py (implemented for local weights, tested on "
        "Qwen2.5-1.5B-Instruct). This file keeps only the synthetic CI gate. A 7B model does not fit in "
        "8 GB at full precision, so the Qwen2.5-7B / Llama-3.1-8B gate named in the blueprint is still "
        "unrun. Requested model: %s" % model_id
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="HF model id for the real gate")
    ap.add_argument("--steps", type=int, default=50)
    args = ap.parse_args()

    if args.model:
        print(run_real_gate(args.model, args.steps))
        return
    r = run_synthetic_gate(steps=args.steps)
    print("synthetic T0 gate (mechanical demo, not a capability result):")
    for k, v in r.items():
        print(f"  {k:20s}: {v}")


if __name__ == "__main__":
    main()
