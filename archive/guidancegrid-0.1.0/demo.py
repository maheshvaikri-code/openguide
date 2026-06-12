"""End-to-end demo: the full GuidanceGrid loop on a toy model.

  spec --compile--> grid --+--> runtime (triggers, live knobs, sigma-cap)
  pack -- vectors ---------+         |
                                     v
                          hash-chained trace --> verify / replay identity
  grid_tune: learn the schedule against a measurable setpoint
"""
import numpy as np
from guidancegrid import (
    SignalPack, GridRuntime, compile_spec, spec_hash,
    grid_tune, constant_baseline,
)

L, W, D, T = 32, 16, 64, 96

SPEC = {
    "layers": L, "frame": W,
    "signals": {
        "anchor":    {"layers": [12, 24], "schedule": {"type": "ramp", "t": [0, T - 1], "g": [0.08, 0.55]}},
        "explore":   {"layers": [8, 16],  "schedule": {"type": "window", "t": [0, 20], "g": 0.5}},
        "precision": {"layers": [20, 30], "schedule": {"type": "none"}},
    },
    "triggers": [
        {"on": "tool_call", "apply": {"signal": "precision", "layers": [20, 30], "g": 0.7, "tau": 8}}
    ],
}


def build_pack(seed=2):
    rng = np.random.default_rng(seed)
    pack = SignalPack("toy-model-v1", D)
    for sig, (lo, hi) in [("anchor", (12, 24)), ("explore", (8, 16)), ("precision", (20, 30))]:
        pos = rng.standard_normal((8, L, D)) + 0.4
        neg = rng.standard_normal((8, L, D))
        pack.derive_contrast(sig, pos, neg, range(lo, hi + 1))
    return pack


def governed_run():
    grid = compile_spec(SPEC)
    pack = build_pack()
    manifest = {"model": pack.model_id, "spec_hash": spec_hash(SPEC), "spec": SPEC,
                "pack_hash": pack.hash(), "seed": 7, "runtime": "ggrid-ref-0.1.0"}
    rt = GridRuntime(grid, pack, manifest)
    h = np.random.default_rng(7).standard_normal((L, D)).astype(np.float32)
    for t in range(T):
        if t in (30, 60):
            rt.fire("tool_call", t)            # trigger -> decay written into grid
        if t == 70:
            rt.set_gain("explore", 0.0, t)     # live knob, recorded
        h = rt.apply(h, t)
    return rt


def main():
    print("== identity ==")
    print("spec  ", spec_hash(SPEC)[:23], "…")
    pack = build_pack()
    print("pack  ", pack.hash()[:23], "…")
    grid = compile_spec(SPEC)
    print("grid  ", grid.hash()[:23], "…  (compiled, deterministic)")
    print("G[18, 48] =", round(grid.field('anchor').get(18, 48), 4), " (total: any cell answers)")

    print("\n== governed run ==")
    rt1, rt2 = governed_run(), governed_run()
    steps = [r for r in rt1.trace.records if r["ev"] == "STEP"]
    evs = [r["ev"] for r in rt1.trace.records]
    print(f"records: {len(rt1.trace.records)}  (STEP {evs.count('STEP')}, TRIGGER {evs.count('TRIGGER')}, OVERRIDE {evs.count('OVERRIDE')})")
    print("sigma peak across run:", round(max(r["sigma_peak"] for r in steps), 3), f"(cap {rt1.sigma_cap})")
    print("trace verify:", rt1.trace.verify())
    print("replay identity (two runs, same manifest):", rt1.trace.head == rt2.trace.head)
    print("trace head:", rt1.trace.head[:23], "…")
    rt1.trace.records[10]["applied"] = {}
    print("after tampering record 10 -> verify:", rt1.trace.verify())

    print("\n== grid tuning (learn the schedule) ==")
    res = grid_tune()
    g_const, _ = constant_baseline(T, W, 0.85, res["drift"])
    print("setpoint: adherence >= 0.85   |   learned min:", round(res["min_adherence"], 3))
    print("learned per-frame gains:", np.round(res["params"], 2))
    print(f"mean gain: learned {res['mean_gain']:.3f}  vs best-constant {g_const:.3f}"
          f"  ->  {(1 - res['mean_gain']/g_const)*100:.0f}% less intervention at the same floor")


if __name__ == "__main__":
    main()
