"""Phase 4 synthetic gate: the T0 closed loop, CI-runnable.

ANCHOR steering raises a probe-measured adherence vs a no-grid baseline, the run
records to a verifiable trace, and replay is bit-identical. This is the
mechanical proxy for the real Qwen2.5-7B gate (scripts/qwen_t0_gate.py), which
needs weights + a GPU and is run offline.
"""
import pytest

pytest.importorskip("torch")

from scripts.qwen_t0_gate import run_synthetic_gate  # noqa: E402


def test_synthetic_t0_gate_closes_the_loop():
    r = run_synthetic_gate(steps=40, seed=0)
    assert r["improved"] is True                     # steering raised adherence
    assert r["delta"] > 0.0
    assert r["trace_verified"] is True               # everything recorded
    assert r["replay_identical"] is True             # replay key holds


def test_synthetic_gate_is_deterministic():
    a = run_synthetic_gate(steps=20, seed=3)
    b = run_synthetic_gate(steps=20, seed=3)
    assert a["steered_adherence"] == b["steered_adherence"]
    assert a["baseline_adherence"] == b["baseline_adherence"]
