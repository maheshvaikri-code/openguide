"""Phase 5 benchmark harnesses (simulated)."""
from benchmarks import run_scenario
from benchmarks.agent_sim import STRATEGIES
from benchmarks.drift_bench import run as drift_run
from benchmarks.t1_bench import run as t1_run


def test_scenario_is_deterministic():
    a = run_scenario("contract", T=40, seed=3, regime="steady")
    b = run_scenario("contract", T=40, seed=3, regime="steady")
    assert a.adherence == b.adherence
    assert a.trace_head == b.trace_head            # real reconciler trace, replay-identical


def test_contract_arm_uses_real_verifiable_trace():
    r = run_scenario("contract", T=40, seed=7, regime="sparse")
    assert r.trace_verified is True
    assert r.n_interventions >= 1


def test_none_arm_drifts_worst():
    none = run_scenario("none", T=60, seed=7, regime="steady")
    contract = run_scenario("contract", T=60, seed=7, regime="steady")
    assert none.mean_adherence < contract.mean_adherence


def test_all_strategies_run():
    for s in STRATEGIES:
        r = run_scenario(s, T=30, seed=1, regime="steady")
        assert len(r.adherence) == 30
        assert r.tokens > 0


def test_t1_bench_contract_beats_naive_at_equal_cost():
    res = t1_run(T=60, seed=7)
    for regime in ("steady", "sparse"):
        v = res["regimes"][regime]["verdict"]
        assert v["contract_wins_at_equal_cost"] is True, (regime, v)
    assert res["simulated"] is True


def test_drift_bench_reduces_area_under_drift():
    res = drift_run(T=60, seed=7)
    for regime in ("steady", "sparse"):
        d = res["regimes"][regime]
        assert d["auc_drift_reduction"] > 0
        assert d["governed"]["area_under_drift"] < d["ungoverned"]["area_under_drift"]
        assert d["trace_verified"] is True
