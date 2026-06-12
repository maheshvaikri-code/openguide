"""Fleet generator, the killer demo, and case studies."""
import importlib.util
import os

from benchmarks.fleet_gen import generate
from guidancegrid.store import Store

EX = os.path.join(os.path.dirname(__file__), "..", "examples")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── fleet generator ─────────────────────────────────────────────────
def test_fleet_gen_populates_and_queries():
    store = Store()
    n = generate(store, 120, T=40)
    assert n == 120
    all_runs = store.query_runs(limit=1000)
    assert len(all_runs) == 120
    # mix of drift levels and some halts produced
    assert any(r.max_drift >= 0.27 for r in all_runs)
    by_contract = store.query_runs(
        contract_hash="sha256:026d89e96d7c473ec6c7f8a52d1b451b63792ff9e17fb024a5a36462a9ef783b")
    assert len(by_contract) > 0


# ── killer demo ─────────────────────────────────────────────────────
def test_demo_baseline_drifts_governed_holds():
    mod = _load(os.path.join(EX, "demo", "run.py"), "demo_run")
    d = mod.run_demo()
    base, gov = d["baseline"], d["governed"]
    assert gov.mean_adherence > base.mean_adherence + 0.2   # governance clearly helps
    assert gov.trace_verified is True
    assert d["reanchor_turn"] is not None
    # both runs persisted to the fleet store
    rows = {r.run_id for r in d["store"].query_runs(limit=10)}
    assert {"demo-baseline", "demo-governed"} <= rows


# ── case studies ────────────────────────────────────────────────────
def test_multi_tenant_distinct_composed_grids():
    mod = _load(os.path.join(EX, "multi-tenant", "run.py"), "mt_run")
    res = mod.run_case()
    assert res["_distinct_grids"] is True
    assert res["acme"]["warmth_at_layer12"] != res["globex"]["warmth_at_layer12"]


def test_injection_detection_fires_at_injection_turn():
    mod = _load(os.path.join(EX, "injection-detection", "run.py"), "inj_run")
    res = mod.run_case()
    assert res["first_detection"] == mod.INJECT_AT     # caught the moment it happens
    assert res["trace_verified"] is True
