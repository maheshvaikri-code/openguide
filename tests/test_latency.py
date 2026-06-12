"""Governance overhead stays within the Phase 2 gate (< 25 ms p50).

Uses a MockUpstream so the measured delta is the control plane's own cost. The
bound is the gate target; the actual overhead is far smaller, but we keep the
assertion at the gate to avoid CI flakiness on shared runners.
"""
from scripts.bench_proxy import run_bench


def test_governance_overhead_under_gate():
    r = run_bench(n=60)
    assert r["overhead_p50"] < 25.0, r          # the blueprint §2 Phase 2 gate
