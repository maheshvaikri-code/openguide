"""T2 re-anchor assembler and T3 validator."""
import os

from guidancegrid.channels import ReanchorAssembler, Validator
from guidancegrid.compiler import compile_contract
from guidancegrid.obc import load_contract
from guidancegrid.sensors import MeasureRegistry, StructuralMeasure

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")


def _cc(model="openai:gpt-4o"):
    return compile_contract(load_contract(os.path.join(EX, "coding-agent-default.toml")), model)


def test_reanchor_due_on_cadence_and_recovery():
    a = ReanchorAssembler(_cc())
    assert a.due(8, recovery_fired=False)         # cadence (every=8)
    assert not a.due(3, recovery_fired=False)
    assert a.due(3, recovery_fired=True)          # recovery overrides cadence


def test_reanchor_text_includes_recovery_marker():
    a = ReanchorAssembler(_cc())
    txt = a.assemble(8, ["anchor"], recovery_fired=True)
    assert txt and "re-anchor" in txt.lower()
    assert a.assemble(3, ["anchor"], recovery_fired=False) is None   # not due


def test_reanchor_budget_cap():
    cc = _cc()
    cc.reanchor_plan["budget_chars"] = 20
    a = ReanchorAssembler(cc)
    txt = a.assemble(8, ["anchor"], recovery_fired=True)
    assert len(txt) <= 22                         # budget + ellipsis slack


def test_t3_tier_never_injects():
    # force a t3-only contract by raising the floor on a t3-capable target
    cc = _cc()
    object.__setattr__(cc, "tier_active", "t3")
    a = ReanchorAssembler(cc)
    assert a.assemble(8, ["anchor"], recovery_fired=True) is None


def test_validator_pass_fail_gap():
    cc = _cc()
    reg = MeasureRegistry()
    reg.register(StructuralMeasure("structural:tests_pass_before_commit",
                                   lambda ctx: ctx.get("tests_pass", True)))
    v = Validator(cc.t3_validators, reg)
    assert v.validate({"tests_pass": True}).ok
    bad = v.validate({"tests_pass": False})
    assert not bad.ok and "tests_gate" in bad.failures
    # unregistered measure -> gap, not a failure
    v2 = Validator(cc.t3_validators, MeasureRegistry())
    res = v2.validate({})
    assert res.ok and "tests_gate" in res.gaps


def test_validator_retry_policy():
    cc = _cc()
    v = Validator(cc.t3_validators, MeasureRegistry(), max_retries=2)
    from guidancegrid.channels.t3_validate import ValidationResult
    fail = ValidationResult(ok=False, failures=["x"])
    assert v.should_retry(0, fail) and v.should_retry(1, fail)
    assert not v.should_retry(2, fail)
    assert not v.should_retry(0, ValidationResult(ok=True))
