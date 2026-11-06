"""Console demo seed data: real traces, a caught tamper, contracts and packs."""
from fastapi.testclient import TestClient

from benchmarks import console_seed, fleet_gen
from guidancegrid.obc import contract_hash
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream


def _client(tmp_path):
    s = console_seed.seed(str(tmp_path), n=30)
    reg = ContractRegistry()
    for c in s.contracts:
        reg.register(c)
    app = create_app(registry=reg, upstream=MockUpstream(lambda b: "ok"), store=s.store,
                     packs_dir=s.packs_dir)
    return TestClient(app), s, reg


def test_seed_counts_and_featured_traces_verify(tmp_path):
    c, s, _ = _client(tmp_path)
    runs = c.get("/v1/openguide/runs?limit=1000").json()["runs"]
    assert len(runs) == 30 + len(s.featured)
    for rid in ("demo-governed-sparse", "demo-baseline-sparse"):
        t = c.get(f"/v1/openguide/runs/{rid}/trace").json()
        assert t["verified"] is True and len(t["records"]) == 60
        assert all(r["ev"] == "STATE" for r in t["records"])


def test_featured_traces_record_three_invariants_for_the_trajectory_view(tmp_path):
    c, _, _ = _client(tmp_path)
    rec = c.get("/v1/openguide/runs/demo-governed-sparse/trace").json()["records"][0]
    assert set(rec["invariants"]) == {"adherence", "tests_gate", "cesr"}


def test_governed_holds_better_than_baseline(tmp_path):
    c, _, _ = _client(tmp_path)
    g = c.get("/v1/openguide/runs/demo-governed-sparse").json()
    b = c.get("/v1/openguide/runs/demo-baseline-sparse").json()
    assert g["max_drift"] < b["max_drift"]
    assert g["recoveries"] > 0 and b["recoveries"] >= 0


def test_tampered_trace_is_reported_invalid(tmp_path):
    c, _, _ = _client(tmp_path)
    run = c.get("/v1/openguide/runs/demo-tampered").json()
    assert run["verified"] is False
    assert c.get("/v1/openguide/runs/demo-tampered/trace").json()["verified"] is False


def test_fleet_contracts_are_registered_so_the_console_can_link_them(tmp_path):
    _, _, reg = _client(tmp_path)
    for h in fleet_gen.CONTRACTS:
        assert reg.has(h), h


def test_featured_runs_reference_the_bench_contract(tmp_path):
    c, s, reg = _client(tmp_path)
    run = c.get("/v1/openguide/runs/demo-governed-sparse").json()
    assert reg.has(run["contract_hash"])
    assert run["contract_hash"] in {contract_hash(x) for x in s.contracts}


def test_packs_present_with_unmeasured_evals(tmp_path):
    c, _, _ = _client(tmp_path)
    packs = c.get("/v1/openguide/packs").json()["packs"]
    assert {p["model_id"] for p in packs} == {"qwen2.5-7b", "llama-3.1-8b"}
    assert all(p["evals"]["coherence_ok"] is None for p in packs)
    # the vectors are generated, so the card must say so even though it is named after a real model
    assert all(p["status"] == "synthetic" for p in packs)


def test_seed_is_deterministic_for_featured_traces(tmp_path):
    a = console_seed.traced_run("contract", "sparse", 7)[0]
    b = console_seed.traced_run("contract", "sparse", 7)[0]
    assert a.head == b.head


def test_add_live_run_inserts_a_summary(tmp_path):
    s = console_seed.seed(str(tmp_path), n=3)
    rid = console_seed.add_live_run(s.store, 1)
    assert s.store.get_run(rid) is not None
