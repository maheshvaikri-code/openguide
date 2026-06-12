"""Deterministic mock-agent simulation for the intervention benchmarks.

A coding agent's instruction adherence decays under a disturbance (slow
late-growing drift + irregular scope-creep shocks). Three intervention
strategies decide *when* to re-anchor:

  none      - no intervention (the floor)
  naive     - re-prompt on a fixed cadence, regardless of state
  contract  - the real OpenGuide Reconciler: sense drift, re-anchor only when
              it crosses the contract threshold (reactive)

All three share the same restore strength and per-intervention token cost, so
the comparison isolates *timing*. Everything is deterministic given a seed —
the contract arm runs the actual reconciler + trace, so its numbers come from
the real control path, not a stand-in.

SIMULATED. Real closed/open-model numbers require keys/weights and replace these.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from guidancegrid.compiler import compile_contract
from guidancegrid.controller import Reconciler
from guidancegrid.obc import load_contract
from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure

CONTRACT = os.path.join(os.path.dirname(__file__), "bench_contract.toml")

BASE_TOKENS_PER_TURN = 180
INTERVENTION_TOKENS = 130
RESTORE = 0.22                      # adherence regained the turn after an intervention
FLOOR = 0.85                        # the contract's adherence floor
STRATEGIES = ("none", "naive", "contract")

# Disturbance regimes (decay_scale, shock_mag, shock_min_gap, shock_max_gap).
# steady : continuous decay, regular-ish shocks  -> fixed cadence does fine
# sparse : agent mostly healthy, rare big shocks  -> reactive should win at equal cost
REGIMES = {
    "steady": (1.0, 0.12, 8, 15),
    "sparse": (0.25, 0.30, 16, 26),
}


def disturbance(T: int, seed: int, regime: str = "steady") -> tuple[np.ndarray, dict[int, float]]:
    """Per-turn decay rate (grows late) + a map of shock turn -> magnitude."""
    decay_scale, shock_mag, gmin, gmax = REGIMES[regime]
    rng = np.random.default_rng(seed)
    decay = (0.012 + 0.018 * (np.arange(T) / T)) * decay_scale
    shocks: dict[int, float] = {}
    t = int(rng.integers(4, gmin + 1))
    while t < T:
        shocks[t] = shock_mag
        t += int(rng.integers(gmin, gmax))
    return decay, shocks


@dataclass
class ScenarioResult:
    strategy: str
    adherence: list[float]
    interventions: list[int]            # turns an intervention was decided
    tokens: int
    drift: list[float] = field(default_factory=list)
    trace_head: str | None = None
    trace_verified: bool | None = None

    @property
    def mean_adherence(self) -> float:
        return float(np.mean(self.adherence))

    @property
    def min_adherence(self) -> float:
        return float(np.min(self.adherence))

    @property
    def final_adherence(self) -> float:
        return float(self.adherence[-1])

    @property
    def frac_in_violation(self) -> float:
        return float(np.mean([a < FLOOR for a in self.adherence]))

    @property
    def n_interventions(self) -> int:
        return len(self.interventions)

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "mean_adherence": round(self.mean_adherence, 4),
            "min_adherence": round(self.min_adherence, 4),
            "final_adherence": round(self.final_adherence, 4),
            "frac_in_violation": round(self.frac_in_violation, 4),
            "interventions": self.n_interventions,
            "tokens": self.tokens,
            "trace_verified": self.trace_verified,
        }


def _step_adherence(a: float, t: int, decay: np.ndarray, shocks: dict[int, float], restore: bool) -> float:
    nxt = a - float(decay[t]) - shocks.get(t, 0.0) + (RESTORE if restore else 0.0)
    return float(min(max(nxt, 0.0), 1.0))


def _contract_reconciler():
    cc = compile_contract(load_contract(CONTRACT), "mock:bench")
    reg = MeasureRegistry()
    holder = {"a": 0.95}
    reg.register(JudgeMeasure("judge:instruction_adherence", lambda ctx: holder["a"]))
    reg.register(StructuralMeasure("structural:tests_pass_before_commit", lambda c: True))
    reg.register(StructuralMeasure("external:codemonk.cesr", lambda c: 0.9))
    manifest = {"model": "mock:bench", "contract_hash": cc.contract_hash, "runtime": "ggrid-bench-0.1"}
    return Reconciler(cc, reg, manifest), holder


def run_scenario(strategy: str, T: int = 60, seed: int = 7, naive_cadence: int = 6,
                 regime: str = "steady") -> ScenarioResult:
    """Run one strategy over T turns. Returns per-turn adherence + token cost."""
    assert strategy in STRATEGIES, strategy
    decay, shocks = disturbance(T, seed, regime)
    a = 0.95
    adherence: list[float] = []
    interventions: list[int] = []
    drift_series: list[float] = []
    tokens = 0

    rc = holder = None
    if strategy == "contract":
        rc, holder = _contract_reconciler()

    restore_next = False
    for t in range(T):
        a = _step_adherence(a, t, decay, shocks, restore=restore_next)
        adherence.append(a)
        tokens += BASE_TOKENS_PER_TURN
        restore_next = False

        if strategy == "naive":
            if t > 0 and t % naive_cadence == 0:
                interventions.append(t)
                tokens += INTERVENTION_TOKENS
                restore_next = True
        elif strategy == "contract":
            holder["a"] = a
            out = rc.step(t, {"adherence": round(a, 6), "turn": t})
            drift_series.append(out.drift)
            if out.action in ("re_anchor", "escalate"):
                interventions.append(t)
                tokens += INTERVENTION_TOKENS
                restore_next = True

    return ScenarioResult(
        strategy=strategy, adherence=adherence, interventions=interventions, tokens=tokens,
        drift=drift_series,
        trace_head=(rc.trace.head if rc else None),
        trace_verified=(rc.trace.verify() if rc else None),
    )
