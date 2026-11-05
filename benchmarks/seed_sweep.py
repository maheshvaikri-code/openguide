"""Seed sweep for the T1 intervention benchmark (SIMULATED).

`t1_bench.py` reports one seed. This repeats the identical protocol (naive
cadence matched to the contract arm's intervention count) over many seeds so the
result can be stated with a spread and a win-rate instead of a single draw.

    python benchmarks/seed_sweep.py            # seeds 0..49, T=60
    python benchmarks/seed_sweep.py --n 200
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks.agent_sim import REGIMES, run_scenario  # noqa: E402


def sweep(n: int = 50, T: int = 60) -> dict:
    out: dict = {"n_seeds": n, "T": T, "simulated": True, "regimes": {}}
    for regime in REGIMES:
        rows = []
        for seed in range(n):
            contract = run_scenario("contract", T=T, seed=seed, regime=regime).summary()
            ni = max(run_scenario("contract", T=T, seed=seed, regime=regime).n_interventions, 1)
            cadence = max(1, round(T / ni))
            naive = run_scenario("naive", T=T, seed=seed, regime=regime,
                                 naive_cadence=cadence).summary()
            rows.append((contract, naive))
        d_adh = [c["mean_adherence"] - v["mean_adherence"] for c, v in rows]
        d_tok = [c["tokens"] - v["tokens"] for c, v in rows]
        wins = sum(1 for d in d_adh if d > 0)
        out["regimes"][regime] = {
            "contract_mean_adherence": round(st.mean(c["mean_adherence"] for c, _ in rows), 4),
            "naive_mean_adherence": round(st.mean(v["mean_adherence"] for _, v in rows), 4),
            "delta_adherence_mean": round(st.mean(d_adh), 4),
            "delta_adherence_sd": round(st.stdev(d_adh), 4) if n > 1 else 0.0,
            "contract_win_rate": round(wins / n, 3),
            "delta_tokens_mean": round(st.mean(d_tok), 1),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--T", type=int, default=60)
    a = ap.parse_args()
    res = sweep(a.n, a.T)
    print(f"T1 seed sweep - SIMULATED (n={res['n_seeds']} seeds, T={res['T']})")
    print("| regime | contract adh | naive adh | delta (sd) | win rate | delta tokens |")
    print("|--------|-------------:|----------:|-----------:|---------:|-------------:|")
    for r, d in res["regimes"].items():
        print(f"| {r} | {d['contract_mean_adherence']} | {d['naive_mean_adherence']} "
              f"| {d['delta_adherence_mean']:+} ({d['delta_adherence_sd']}) "
              f"| {d['contract_win_rate']:.0%} | {d['delta_tokens_mean']:+} |")
    path = os.path.join(os.path.dirname(__file__), "seed_sweep_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
