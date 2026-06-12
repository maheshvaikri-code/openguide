"""Phase 1 acceptance gate (blueprint §2).

A 50-turn scripted agent (mock LLM) under contract:
  - drift injected at turn 30,
  - the sensor detects it,
  - the reconciler fires a re-anchor,
  - drift recovers,
  - the trace verifies,
  - replay produces a bit-identical head.

A governed run is compared against an ungoverned counterfactual: with recovery
disabled the same disturbance drives drift past the halt threshold. That
contrast is the point — the control plane changes the trajectory.
"""
import os

from guidancegrid.compiler import compile_contract
from guidancegrid.controller import Reconciler
from guidancegrid.obc import load_contract
from guidancegrid.sensors import (
    ExternalMeasure,
    JudgeMeasure,
    MeasureRegistry,
    StructuralMeasure,
)
from guidancegrid.store import RunRecord, Store

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")
MODEL = "mock:agent-v1"
TURNS = 50
INJECT_AT = 30


def _registry():
    reg = MeasureRegistry()
    reg.register(JudgeMeasure("judge:instruction_adherence", lambda ctx: ctx["adherence"]))
    reg.register(StructuralMeasure("structural:tests_pass_before_commit", lambda ctx: True))
    reg.register(ExternalMeasure("external:codemonk.cesr", lambda ctx: 0.9))
    return reg


def _compiled():
    return compile_contract(load_contract(os.path.join(EX, "coding-agent-default.toml")), MODEL)


def run_agent(governed: bool):
    """Deterministic mock agent. Adherence is stable until an injected decay at
    turn 30; re-anchoring (when governed) restores it, otherwise it keeps
    degrading. Returns (reconciler, per-turn outputs)."""
    cc = _compiled()
    reg = _registry()
    manifest = {"model": MODEL, "contract_hash": cc.contract_hash,
                "seed": 7, "runtime": "ggrid-ref-0.1.0", "governed": governed}
    rc = Reconciler(cc, reg, manifest)

    outs = []
    adherence = 0.95
    last_action = None
    for t in range(TURNS):
        # exogenous + control dynamics, computed before sensing
        if t == INJECT_AT:
            adherence = 0.55                      # injected instruction-decay event
        elif t > INJECT_AT:
            if governed and last_action in ("re_anchor", "escalate"):
                adherence = min(0.95, adherence + 0.20)   # re-anchor pulls it back
            else:
                adherence = max(0.0, adherence - 0.06)    # ungoverned: keeps degrading

        out = rc.step(t, {"adherence": round(adherence, 6), "turn": t})
        last_action = out.action
        outs.append(out)
        if out.halted:
            break
    return rc, outs


# ── the gate ──────────────────────────────────────────────────────────
def test_drift_injected_and_detected():
    _, outs = run_agent(governed=True)
    inj = outs[INJECT_AT]
    assert inj.drift >= 0.27                       # disturbance visible
    assert inj.action == "re_anchor"               # reconciler fired recovery
    assert inj.reanchor_text is not None           # actuation emitted


def test_drift_recovers_after_reanchor():
    _, outs = run_agent(governed=True)
    # within 3 turns of the injection, drift falls back below threshold
    recovered = [o.drift for o in outs[INJECT_AT + 1:INJECT_AT + 4]]
    assert min(recovered) < 0.27


def test_governed_run_never_halts_and_stays_bounded():
    rc, outs = run_agent(governed=True)
    assert not outs[-1].halted
    assert max(o.drift for o in outs) < 0.60       # held below the halt gate
    assert len(outs) == TURNS


def test_trace_verifies():
    rc, _ = run_agent(governed=True)
    assert rc.trace.verify()


def test_replay_is_bit_identical():
    rc1, _ = run_agent(governed=True)
    rc2, _ = run_agent(governed=True)
    assert rc1.trace.head == rc2.trace.head        # the replay key holds


def test_ungoverned_counterfactual_halts():
    """Same disturbance, recovery disabled -> drift runs to the halt threshold."""
    rc, outs = run_agent(governed=False)
    assert outs[-1].halted is True
    assert max(o.drift for o in outs) >= 0.60


def test_recovery_count_and_store_indexing():
    rc, outs = run_agent(governed=True)
    recoveries = sum(1 for o in outs if o.action in ("re_anchor", "escalate"))
    assert recoveries >= 1
    max_drift = max(o.drift for o in outs)

    store = Store()
    cc = _compiled()
    store.put_blob(load_contract(os.path.join(EX, "coding-agent-default.toml")), "contract")
    store.put_run(RunRecord(
        run_id="gate-run", contract_hash=cc.contract_hash, model=MODEL, tier=cc.tier_active,
        turns=len(outs), max_drift=round(max_drift, 6), recoveries=recoveries,
        halted=False, verified=rc.trace.verify(), trace_hash=rc.trace.head, created="2026-06-12",
    ))
    hits = store.query_runs(contract_hash=cc.contract_hash, min_drift=0.27)
    assert [r.run_id for r in hits] == ["gate-run"]
    assert hits[0].verified is True


def test_governed_vs_ungoverned_max_drift():
    _, g = run_agent(governed=True)
    _, u = run_agent(governed=False)
    assert max(o.drift for o in g) < max(o.drift for o in u)   # governance helps
