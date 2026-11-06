"""Seed data for the Console demo (SIMULATED; every model id is prefixed ``mock:``).

Produces, in one Store:
  * N fleet-index runs (benchmarks/fleet_gen.py) - summaries only, no stored trace
  * 4 featured runs WITH full reconciler traces: governed + baseline, two regimes
  * 1 deliberately tampered trace, so the Audit page has something to catch
  * the contracts those runs reference, and two synthetic SignalPacks

Featured traces come from the real Reconciler; only the agent's adherence signal
is simulated (benchmarks/agent_sim.py). ASCII-only output (Windows cp1252 consoles).
"""
from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks import fleet_gen  # noqa: E402
from benchmarks.agent_sim import FLOOR, RESTORE, _step_adherence, disturbance  # noqa: E402
from guidancegrid.compiler import compile_contract  # noqa: E402
from guidancegrid.controller import Reconciler  # noqa: E402
from guidancegrid.core.trace import Trace  # noqa: E402
from guidancegrid.obc import load_contract  # noqa: E402
from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure  # noqa: E402
from guidancegrid.store import RunRecord, Store  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXAMPLES = os.path.join(ROOT, "spec", "obc", "examples")
BENCH_CONTRACT = os.path.join(ROOT, "benchmarks", "console_contract.toml")
T = 60
FEATURED = (
    ("demo-governed-sparse", "contract", "sparse", 7),
    ("demo-baseline-sparse", "none", "sparse", 7),
    ("demo-governed-steady", "contract", "steady", 7),
    ("demo-baseline-steady", "none", "steady", 7),
)


@dataclass
class Seeded:
    store: Store
    contracts: list[dict]            # loaded OBC dicts to register
    packs_dir: str
    featured: list[str]


def traced_run(strategy: str, regime: str, seed: int, turns: int = T) -> tuple[Trace, str, list[float]]:
    """Run the real Reconciler over the simulated agent. ``contract`` applies its
    re-anchors; ``none`` only observes (so the baseline's drift is recorded too)."""
    contract = load_contract(BENCH_CONTRACT)
    cc = compile_contract(contract, "mock:bench")
    state = {"a": 0.95}

    def cesr(_ctx):                  # simulated codebase-health signal, tracks adherence loss
        return float(np.clip(0.95 - 0.8 * max(0.0, FLOOR - state["a"]), 0.0, 1.0))

    reg = MeasureRegistry()
    reg.register(JudgeMeasure("judge:instruction_adherence", lambda ctx: state["a"]))
    reg.register(StructuralMeasure("structural:tests_pass_before_commit",
                                   lambda ctx: state["a"] > 0.45))
    reg.register(StructuralMeasure("external:codemonk.cesr", cesr))
    manifest = {"model": "mock:bench", "contract_hash": cc.contract_hash,
                "runtime": "ggrid-console-seed-0.1", "regime": regime, "seed": seed,
                "simulated": True}
    rc = Reconciler(cc, reg, manifest)

    decay, shocks = disturbance(turns, seed, regime)
    a, restore, adherence = 0.95, False, []
    for t in range(turns):
        a = _step_adherence(a, t, decay, shocks, restore=restore)
        state["a"] = a
        adherence.append(round(a, 6))
        out = rc.step(t, {"adherence": round(a, 6), "turn": t})
        restore = strategy == "contract" and out.action in ("re_anchor", "escalate")
    return rc.trace, cc.tier_active, adherence


def _record(run_id: str, trace: Trace, tier: str, contract_hash: str, cas_key: str) -> RunRecord:
    states = [r for r in trace.records if r.get("ev") == "STATE"]
    return RunRecord(
        run_id=run_id, contract_hash=contract_hash, model="mock:bench", tier=tier, turns=len(states),
        max_drift=round(max((s["drift"] for s in states), default=0.0), 6),
        recoveries=sum(1 for s in states if s.get("recovery_fired")),
        halted=any(s.get("recovery_fired") == "halt" for s in states),
        verified=trace.verify(), trace_hash=trace.head, trace_cas_key=cas_key,
        created="2026-11-06",
    )


def tamper(trace: Trace) -> Trace:
    """Return a copy that erases the first recorded correction (drift zeroed, recovery
    removed) but leaves the stored head untouched - what someone who cannot recompute
    the whole chain would leave behind. verify() on the result is False."""
    bad = Trace(copy.deepcopy(trace.manifest))
    bad.records = copy.deepcopy(trace.records)
    bad.head = trace.head
    index = next((i for i, r in enumerate(bad.records) if r.get("recovery_fired")), 0)
    bad.records[index]["drift"] = 0.0
    bad.records[index]["recovery_fired"] = None
    bad.records[index]["reanchored"] = False
    return bad


def build_packs(packs_dir: str) -> None:
    import json

    from packs.build_pack import eval_card, synthetic_pack

    for model in ("qwen2.5-7b", "llama-3.1-8b"):
        d = os.path.join(packs_dir, model)
        os.makedirs(d, exist_ok=True)
        pack = synthetic_pack(model, 32, 64)
        pack.save_safetensors(os.path.join(d, "pack.safetensors"))
        with open(os.path.join(d, "eval_card.json"), "w", encoding="utf-8") as f:
            json.dump(eval_card(pack, model, 32, synthetic=True), f, indent=2)


def seed(workdir: str, n: int = 2000, db: str | None = None) -> Seeded:
    """``db`` defaults to a sqlite file in ``workdir``; pass ``":memory:"`` for a disposable store."""
    os.makedirs(workdir, exist_ok=True)
    store = Store(db if db is not None else os.path.join(workdir, "console-demo.db"))
    fleet_gen.generate(store, n, T=T)

    contracts = [load_contract(os.path.join(EXAMPLES, f)) for f in sorted(os.listdir(EXAMPLES))
                 if f.endswith(".toml")]
    contracts.append(load_contract(BENCH_CONTRACT))

    featured = []
    bench_hash = None
    for run_id, strategy, regime, seed_ in FEATURED:
        trace, tier, _ = traced_run(strategy, regime, seed_)
        bench_hash = trace.manifest["contract_hash"]
        store.put_run(_record(run_id, trace, tier, bench_hash, store.put_trace(trace)))
        featured.append(run_id)
        if run_id == "demo-governed-sparse":
            bad = tamper(trace)
            store.put_run(_record("demo-tampered", bad, tier, bench_hash, store.put_trace(bad)))
            featured.append("demo-tampered")

    packs_dir = os.path.join(workdir, "packs")
    build_packs(packs_dir)
    return Seeded(store=store, contracts=contracts, packs_dir=packs_dir, featured=featured)


def add_live_run(store: Store, i: int) -> str:
    """Insert one fleet-summary run (for the Console's live tail)."""
    from benchmarks.agent_sim import REGIMES, run_scenario

    regime = list(REGIMES)[i % len(REGIMES)]
    strat = ("contract", "naive", "none")[i % 3]
    r = run_scenario(strat, T=T, seed=10_000 + i, regime=regime)
    run_id = f"live-{i:05d}"
    drift = round(max(FLOOR - min(r.adherence), 0.0), 6)
    store.put_run(RunRecord(
        run_id=run_id, contract_hash=fleet_gen.CONTRACTS[i % len(fleet_gen.CONTRACTS)],
        model=fleet_gen.MODELS[i % len(fleet_gen.MODELS)], tier="t2", turns=T, max_drift=drift,
        recoveries=len(r.interventions), halted=drift >= 0.6, verified=True,
        trace_hash=r.trace_head or f"sha256:{i:064x}", created="2026-11-06",
    ))
    return run_id


__all__ = ["seed", "traced_run", "tamper", "add_live_run", "RESTORE"]
