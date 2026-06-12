"""T1 intervention benchmark (the commercial gate, simulated).

Compares three strategies at a *matched token budget*:
  none      - no intervention
  naive     - re-prompt on a fixed cadence (cadence tuned to match the contract's
              token spend, so the comparison is adherence-at-equal-cost)
  contract  - the real OpenGuide reconciler (reactive re-anchoring)

across disturbance regimes. The headline question (blueprint kill criterion):
does scheduled contract re-anchoring beat naive re-prompting at equal cost? We
report the answer per regime, whatever it is.

SIMULATED. Real closed/open-model numbers require API keys + matched real token
budgets and replace these; the methodology is what transfers.

    python benchmarks/t1_bench.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from benchmarks.agent_sim import REGIMES, STRATEGIES, run_scenario  # noqa: E402


def run(T: int = 60, seed: int = 7) -> dict:
    out: dict = {"T": T, "seed": seed, "simulated": True, "regimes": {}}
    for regime in REGIMES:
        contract = run_scenario("contract", T=T, seed=seed, regime=regime)
        # match naive's token budget to the contract's by setting its cadence
        ni = max(contract.n_interventions, 1)
        cadence = max(1, round(T / ni))
        arms = {}
        for s in STRATEGIES:
            kw = {"naive_cadence": cadence} if s == "naive" else {}
            arms[s] = run_scenario(s, T=T, seed=seed, regime=regime, **kw).summary()
        verdict = _verdict(arms["contract"], arms["naive"])
        out["regimes"][regime] = {"naive_cadence": cadence, "arms": arms, "verdict": verdict}
    return out


def _verdict(contract: dict, naive: dict) -> dict:
    # contract "wins" if it holds higher mean adherence at <= the naive token cost
    better_adherence = contract["mean_adherence"] >= naive["mean_adherence"]
    not_more_tokens = contract["tokens"] <= naive["tokens"] * 1.05
    return {
        "contract_mean": contract["mean_adherence"],
        "naive_mean": naive["mean_adherence"],
        "contract_tokens": contract["tokens"],
        "naive_tokens": naive["tokens"],
        "contract_wins_at_equal_cost": bool(better_adherence and not_more_tokens),
    }


def render_table(results: dict) -> str:
    lines = []
    for regime, data in results["regimes"].items():
        lines.append(f"\n### regime: {regime}  (matched naive cadence = {data['naive_cadence']})")
        lines.append("| strategy | mean adh | min adh | % in violation | interventions | tokens |")
        lines.append("|----------|---------:|--------:|---------------:|--------------:|-------:|")
        for s in STRATEGIES:
            a = data["arms"][s]
            lines.append(f"| {s} | {a['mean_adherence']:.3f} | {a['min_adherence']:.3f} | "
                         f"{a['frac_in_violation']*100:.0f}% | {a['interventions']} | {a['tokens']} |")
        v = data["verdict"]
        win = "YES" if v["contract_wins_at_equal_cost"] else "NO"
        lines.append(f"\n_contract beats naive at equal cost: **{win}** "
                     f"(contract {v['contract_mean']:.3f} @ {v['contract_tokens']} tok vs "
                     f"naive {v['naive_mean']:.3f} @ {v['naive_tokens']} tok)_")
    return "\n".join(lines)


def main() -> None:
    results = run()
    print("T1 intervention benchmark — SIMULATED (mock agent; real-model numbers pending keys)")
    print(render_table(results))
    out_path = os.path.join(os.path.dirname(__file__), "t1_bench_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
