"""Per-turn reconciler: drift math, recovery dispatch, single write path."""
import os

from guidancegrid.compiler import compile_contract
from guidancegrid.controller import Reconciler
from guidancegrid.controller.reconciler import _eval_state_pred
from guidancegrid.obc import load_contract
from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")


def _setup(adherence, model="openai:gpt-4o", tests_pass=True):
    cc = compile_contract(load_contract(os.path.join(EX, "coding-agent-default.toml")), model)
    reg = MeasureRegistry()
    reg.register(JudgeMeasure("judge:instruction_adherence", lambda ctx: ctx["adherence"]))
    reg.register(StructuralMeasure("structural:tests_pass_before_commit",
                                   lambda ctx: ctx.get("tests_pass", True)))
    reg.register(StructuralMeasure("external:codemonk.cesr", lambda ctx: ctx.get("cesr", 0.9)))
    manifest = {"model": model, "contract_hash": cc.contract_hash, "runtime": "ggrid-ref-0.1.0"}
    return Reconciler(cc, reg, manifest)


def test_no_drift_when_above_floors():
    rc = _setup(0.95)
    out = rc.step(0, {"adherence": 0.95, "cesr": 0.9})
    assert out.drift == 0.0 and out.action is None


def test_drift_triggers_reanchor():
    rc = _setup(0.55)
    out = rc.step(0, {"adherence": 0.55, "cesr": 0.9})
    # adherence floor 0.85 -> violation 0.30; cesr fine. weighted drift > 0.27
    assert out.drift >= 0.27
    assert out.action == "re_anchor"
    assert out.reanchor_text is not None


def test_halt_at_severe_drift():
    rc = _setup(0.0)
    out = rc.step(0, {"adherence": 0.0, "cesr": 0.0})
    assert out.action == "halt" and out.halted is True


def test_hard_validation_failure_forces_reanchor():
    rc = _setup(0.95)
    out = rc.step(0, {"adherence": 0.95, "cesr": 0.9, "tests_pass": False})
    assert "tests_gate" in out.validation_failures
    assert out.action == "re_anchor"          # forced even though drift is low


def test_sensor_gap_recorded_not_fatal():
    rc = _setup(0.95)
    # omit cesr and adherence -> judge/external read as gaps
    reg = rc.registry
    reg._measures.pop("judge:instruction_adherence")
    out = rc.step(0, {"cesr": 0.9})
    assert "adherence" in out.sensor_gaps
    assert rc.trace.verify()                  # loop proceeded, trace intact


def test_every_step_is_recorded_once():
    rc = _setup(0.95)
    for t in range(5):
        rc.step(t, {"adherence": 0.95, "cesr": 0.9})
    state_records = [r for r in rc.trace.records if r.get("ev") == "STATE"]
    assert len(state_records) == 5
    assert rc.trace.verify()


def test_state_record_has_normative_fields():
    rc = _setup(0.7)
    out = rc.step(3, {"adherence": 0.7, "cesr": 0.9})
    s = out.state
    for k in ("turn", "tier_active", "invariants", "drift", "signals_active",
              "recovery_fired", "sensor_gaps"):
        assert k in s
    assert s["invariants"]["adherence"]["determinism"] == "stochastic"
    assert s["invariants"]["adherence"]["violated"] is True


def test_state_predicate_eval():
    assert _eval_state_pred("drift>0.3", {"drift": 0.4})
    assert not _eval_state_pred("drift>0.3", {"drift": 0.2})
    assert _eval_state_pred("context_obedience>=0.40", {"context_obedience": 0.40})
    assert not _eval_state_pred("nope", {})
