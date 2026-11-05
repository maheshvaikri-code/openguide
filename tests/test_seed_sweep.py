"""Seed sweep (simulated): deterministic and well-formed."""
from benchmarks.seed_sweep import sweep


def test_sweep_is_deterministic_and_shaped():
    a = sweep(n=3, T=40)
    b = sweep(n=3, T=40)
    assert a == b
    assert a["simulated"] is True
    for d in a["regimes"].values():
        assert 0.0 <= d["contract_win_rate"] <= 1.0
        assert 0.0 <= d["contract_mean_adherence"] <= 1.0
