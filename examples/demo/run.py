"""The killer demo (CLI form) — one command, no network, no GPU.

A 60-step coding-agent scenario where the baseline visibly drifts (scope creep +
instruction decay) and the governed run holds. Both runs are recorded; the demo
prints a side-by-side drift timeline, persists runs to a Store (the Fleet view's
data source), and scrubs the governed run's replay to the exact re-anchor event.

This is the CLI surface of the Phase 5 demo; the Console (Phase 3) renders the
same artifacts. Runs cold in seconds.

    python examples/demo/run.py        # or:  make demo
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from benchmarks.agent_sim import FLOOR, run_scenario  # noqa: E402
from guidancegrid.store import RunRecord, Store  # noqa: E402

T = 60
SEED = 7
REGIME = "sparse"


def _bar(a: float, width: int = 24) -> str:
    fill = int(round(a * width))
    mark = "#" * fill + "." * (width - fill)
    flag = "    " if a >= FLOOR else " <-drift"
    return f"{mark} {a:0.2f}{flag}"


def run_demo() -> dict:
    baseline = run_scenario("none", T=T, seed=SEED, regime=REGIME)
    governed = run_scenario("contract", T=T, seed=SEED, regime=REGIME)

    store = Store()
    for r, rid, model in ((baseline, "demo-baseline", "mock:gpt-4o"),
                          (governed, "demo-governed", "mock:gpt-4o")):
        store.put_run(RunRecord(
            run_id=rid, contract_hash="sha256:026d89e9", model=model, tier="t2", turns=T,
            max_drift=round(max(FLOOR - min(r.adherence), 0.0), 6),
            recoveries=r.n_interventions, halted=False,
            verified=(r.trace_verified if r.trace_verified is not None else True),
            trace_hash=(r.trace_head or "sha256:baseline"), created="2026-06-12",
        ))

    # find the first re-anchor event in the governed trace (the scrub target)
    reanchor_turn = governed.interventions[0] if governed.interventions else None
    return {"baseline": baseline, "governed": governed, "store": store,
            "reanchor_turn": reanchor_turn}


def main() -> None:
    d = run_demo()
    base, gov = d["baseline"], d["governed"]
    print("OpenGuide demo — SIMULATED coding agent, 60 steps (baseline vs governed)\n")
    print(f"{'turn':>4}  {'baseline':<36}{'governed'}")
    for t in range(0, T, 3):
        print(f"{t:>4}  {_bar(base.adherence[t]):<36}{_bar(gov.adherence[t])}")

    print("\nsummary:")
    print(f"  baseline : mean {base.mean_adherence:.3f}  min {base.min_adherence:.3f}  "
          f"%violation {base.frac_in_violation*100:.0f}%  interventions {base.n_interventions}")
    print(f"  governed : mean {gov.mean_adherence:.3f}  min {gov.min_adherence:.3f}  "
          f"%violation {gov.frac_in_violation*100:.0f}%  interventions {gov.n_interventions}")
    print(f"  governed trace verified: {gov.trace_verified}")

    rt = d["reanchor_turn"]
    print("\nfleet (persisted to store):")
    for row in d["store"].query_runs(limit=10):
        print(f"  {row.run_id:<16} max_drift={row.max_drift:.3f} recoveries={row.recoveries} "
              f"verified={row.verified}")
    if rt is not None:
        print(f"\nscrub -> first re-anchor fired at governed turn {rt} "
              f"(adherence {gov.adherence[rt]:.2f} -> {gov.adherence[min(rt+1, T-1)]:.2f} next turn)")


if __name__ == "__main__":
    main()
