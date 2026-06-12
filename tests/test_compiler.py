"""OBC compiler: lowering to CompiledContract."""
import os

from guidancegrid.compiler import compile_contract
from guidancegrid.compiler.compile import RecoveryPlan
from guidancegrid.obc import load_contract

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")


def _c(name):
    return load_contract(os.path.join(EX, name))


def test_compile_coding_agent_t2():
    cc = compile_contract(_c("coding-agent-default.toml"), "openai:gpt-4o")
    assert cc.tier_active == "t2"
    assert cc.contract_hash.startswith("sha256:")
    ids = {i.id for i in cc.invariants}
    assert ids == {"adherence", "tests_gate", "cesr"}
    # tests_gate is a hard structural invariant -> a T3 validator
    assert [v.id for v in cc.t3_validators] == ["tests_gate"]


def test_compile_separates_hard_and_soft():
    cc = compile_contract(_c("coding-agent-default.toml"), "openai:gpt-4o")
    assert {i.id for i in cc.hard_invariants()} == {"tests_gate"}
    assert {i.id for i in cc.soft_invariants()} == {"adherence", "cesr"}


def test_phases_active_signals():
    cc = compile_contract(_c("coding-agent-default.toml"), "openai:gpt-4o")
    assert "explore" in cc.active_signals(2)      # plan phase 0..5
    assert "anchor" in cc.active_signals(40)      # act phase 5..-1


def test_probe_invariants_collected():
    cc = compile_contract(_c("browsing-injection.toml"), "anthropic:claude")
    probe_ids = {p.id for p in cc.probe_specs}
    assert {"user_adherence", "context_obedience"} <= probe_ids


def test_recovery_ladder_parsing():
    cc = compile_contract(_c("coding-agent-default.toml"), "openai:gpt-4o")
    rp = cc.recovery
    assert rp.drift_threshold == 0.27
    assert rp.action_for(0.10) is None
    assert rp.action_for(0.30) == "re_anchor"
    assert rp.action_for(0.50) == "escalate"
    assert rp.action_for(0.65) == "halt"


def test_recovery_plan_unit():
    rp = RecoveryPlan(0.2, [("re_anchor", None), ("halt", 0.5)])
    assert rp.action_for(0.1) is None
    assert rp.action_for(0.2) == "re_anchor"
    assert rp.action_for(0.6) == "halt"


def test_t2_fragments_fold_in_boundaries():
    cc = compile_contract(_c("coding-agent-default.toml"), "openai:gpt-4o")
    frag = cc.t2_fragments["anchor"]
    assert "Persona" in frag and "Boundaries" in frag
