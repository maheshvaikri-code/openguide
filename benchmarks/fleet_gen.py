"""Synthetic fleet generator.

Produces N realistic runs into a Store's fleet index so the Console's Fleet view
(and the query API) have data to render before real traffic exists. Each run
varies contract, model, regime, and seed; metrics come from the mock-agent sim,
so drift/recovery/halt distributions look like real fleet telemetry.

    python benchmarks/fleet_gen.py --n 10000 --db fleet.db

SIMULATED data, clearly tagged via the model id prefix `mock:`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks.agent_sim import FLOOR, REGIMES, run_scenario  # noqa: E402
from guidancegrid.store import RunRecord, Store  # noqa: E402

CONTRACTS = [
    "sha256:026d89e96d7c473ec6c7f8a52d1b451b63792ff9e17fb024a5a36462a9ef783b",  # coding-agent
    "sha256:290920ba43da8309b68053070458bf2ffc076701c0cfea911435370f3f0ddaf0",  # support-tenant
    "sha256:b680c760c86c73d09eb6a5795619c0485cb2719786c235e961acad7f6211ba22",  # browsing-injection
]
MODELS = ["mock:gpt-4o", "mock:claude", "mock:qwen2.5-7b"]
TIERS = {"mock:gpt-4o": "t2", "mock:claude": "t2", "mock:qwen2.5-7b": "t0"}
STRATS = ["contract", "naive", "none"]


def generate(store: Store, n: int, T: int = 60, base_seed: int = 0) -> int:
    regimes = list(REGIMES)
    for i in range(n):
        regime = regimes[i % len(regimes)]
        model = MODELS[i % len(MODELS)]
        contract = CONTRACTS[i % len(CONTRACTS)]
        strat = STRATS[i % len(STRATS)]
        r = run_scenario(strat, T=T, seed=base_seed + i, regime=regime)
        drift_max = round(max(FLOOR - min(r.adherence), 0.0), 6)
        halted = drift_max >= 0.60
        store.put_run(RunRecord(
            run_id=f"run-{i:06d}", contract_hash=contract, model=model, tier=TIERS[model],
            turns=T, max_drift=drift_max, recoveries=r.n_interventions, halted=halted,
            verified=(r.trace_verified if r.trace_verified is not None else True),
            trace_hash=(r.trace_head or f"sha256:{i:064x}"), created="2026-06-12",
        ))
    return n


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--turns", type=int, default=60)
    args = ap.parse_args()

    store = Store(args.db)
    n = generate(store, args.n, T=args.turns)
    hi = store.query_runs(min_drift=0.27, limit=5)
    halted = store.query_runs(halted=True, limit=1000000)
    print(f"generated {n} runs into {args.db} (SIMULATED, model ids prefixed mock:)")
    print(f"  high-drift (>=0.27): top-5 ids {[r.run_id for r in hi]}")
    print(f"  halted runs: {len(halted)}")


if __name__ == "__main__":
    main()
