"""Case study 2: multi-tenant support — behavior as config (SIMULATED).

One model, several tenant temperaments, expressed as composable grids: a shared
`task` grid plus a per-tenant `tenant` grid, combined with `Grid.compose` (the
`tenant ⊕ task` algebra). Shows the economics: a new tenant is a small grid, not
a new model or fine-tune.

Reference scenario — simulated until a design partner replaces it.

    python examples/multi-tenant/run.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from guidancegrid.core.grid import Grid  # noqa: E402

L, W = 32, 16


def task_grid() -> Grid:
    g = Grid(L, W)
    g.field("precision").write_ramp(18, 28, 0, 40, 0.2, 0.5)   # tighten as the ticket resolves
    return g


def tenant_grid(name: str, warmth: float, anchor: float) -> Grid:
    g = Grid(L, W)
    g.field("warmth").write_const(8, 16, 0, 40, warmth)
    g.field("anchor").write_const(12, 24, 0, 40, anchor)
    return g


TENANTS = {
    "acme":   {"warmth": 0.6, "anchor": 0.3},   # warm, lightly anchored
    "globex": {"warmth": 0.2, "anchor": 0.6},   # terse, strongly anchored
    "initech": {"warmth": 0.45, "anchor": 0.45},
}


def run_case() -> dict:
    task = task_grid()
    out = {}
    for name, cfg in TENANTS.items():
        composed = tenant_grid(name, **cfg).compose(task)   # tenant ⊕ task
        col = composed.total_column(20)                      # mid-conversation column
        out[name] = {
            "signals": sorted(composed.fields.keys()),
            "grid_hash": composed.hash(),
            "warmth_at_layer12": round(float(composed.field("warmth").get(12, 20)), 4),
            "precision_at_layer22": round(float(composed.field("precision").get(22, 20)), 4),
            "column_peak": round(float(col.max()), 4),
        }
    # distinct tenants -> distinct composed grids (behavior-as-config identity)
    hashes = {v["grid_hash"] for v in out.values()}
    out["_distinct_grids"] = len(hashes) == len(TENANTS)
    return out


def main() -> None:
    res = run_case()
    print("multi-tenant support - SIMULATED (one model, composed tenant (+) task grids)\n")
    for name in TENANTS:
        r = res[name]
        print(f"  {name:8s} signals={r['signals']} warmth@L12={r['warmth_at_layer12']} "
              f"precision@L22={r['precision_at_layer22']} grid={r['grid_hash'][:19]}...")
    print(f"\n  each tenant is a distinct composed grid: {res['_distinct_grids']}")
    print("  a new tenant = one small grid, not a new model or fine-tune.")


if __name__ == "__main__":
    main()
