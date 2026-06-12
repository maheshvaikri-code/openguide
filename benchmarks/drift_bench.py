"""Drift benchmark (simulated).

Turn-wise behavioral divergence with vs without a contract, after the
methodology of "Drift No More?" (arXiv:2510.07777): track adherence each turn
and summarize the trajectory with area-under-drift (cumulative floor deficit),
peak drift, and recovery time after the largest shock.

SIMULATED. Real numbers use τ-Bench-style tasks + a judge; the trajectory
summaries are what transfer.

    python benchmarks/drift_bench.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks.agent_sim import FLOOR, REGIMES, run_scenario  # noqa: E402


def _drift_series(adherence: list[float]) -> np.ndarray:
    return np.maximum(0.0, FLOOR - np.asarray(adherence))


def _recovery_time(adherence: list[float]) -> int | None:
    """Turns from the worst adherence back above the floor (None if never)."""
    a = np.asarray(adherence)
    worst = int(np.argmin(a))
    for t in range(worst, len(a)):
        if a[t] >= FLOOR:
            return t - worst
    return None


def summarize(adherence: list[float]) -> dict:
    d = _drift_series(adherence)
    return {
        "area_under_drift": round(float(d.sum()), 4),
        "peak_drift": round(float(d.max()), 4),
        "turns_in_violation": int((d > 0).sum()),
        "recovery_time": _recovery_time(adherence),
    }


def run(T: int = 60, seed: int = 7) -> dict:
    out: dict = {"T": T, "seed": seed, "simulated": True, "regimes": {}}
    for regime in REGIMES:
        governed = run_scenario("contract", T=T, seed=seed, regime=regime)
        ungoverned = run_scenario("none", T=T, seed=seed, regime=regime)
        g = summarize(governed.adherence)
        u = summarize(ungoverned.adherence)
        out["regimes"][regime] = {
            "governed": g,
            "ungoverned": u,
            "auc_drift_reduction": round(u["area_under_drift"] - g["area_under_drift"], 4),
            "trace_verified": governed.trace_verified,
        }
    return out


def render(results: dict) -> str:
    lines = []
    for regime, d in results["regimes"].items():
        lines.append(f"\n### regime: {regime}")
        lines.append("| | area-under-drift | peak drift | turns in violation | recovery |")
        lines.append("|--|----------------:|-----------:|-------------------:|---------:|")
        for k in ("ungoverned", "governed"):
            s = d[k]
            lines.append(f"| {k} | {s['area_under_drift']} | {s['peak_drift']} | "
                         f"{s['turns_in_violation']} | {s['recovery_time']} |")
        lines.append(f"\n_area-under-drift reduced by {d['auc_drift_reduction']} "
                     f"(governed trace verified: {d['trace_verified']})_")
    return "\n".join(lines)


def main() -> None:
    results = run()
    print("Drift benchmark — SIMULATED (mock agent; real-model numbers pending)")
    print(render(results))
    out_path = os.path.join(os.path.dirname(__file__), "drift_bench_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
