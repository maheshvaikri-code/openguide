# Raw results: Qwen2.5-1.5B-Instruct (real model)

The data behind `benchmarks/REPORT.md` section 7. Every reply, rule check and number in that section
comes from these files. Greedy decoding, so a re-run on the same software should reproduce them, though
GPU kernels can differ across machines.

| File | Produced by | What it is |
|------|-------------|------------|
| `real_recovery_results_shock.json` | `scripts/real_placement_ablation.py` | The recovery experiment: 5 conversations x 16 turns x 5 arms (none, proxy, re-anchor front/end), shocks at turns 4 and 10. Every turn is in here. |
| `real_ablation_results.json` | an earlier version of the same script | Plain prompts only, 3 conversations x 12 turns, arms none / front3 / end3 / front1 / end1. The arm labels are `front3` etc.; there is no proxy arm. |
| `real_t0_results.json` | `scripts/real_t0_gate.py` | The steering gate: instruction replacement, GSM8K and MMLU at each gain, replay check, and conversation recovery at gains 0.1 / 0.2 / 0.4. |
| `real_t0_results_drift.json` | `scripts/real_t0_gate.py --only-drift --drift-gains 0.05` | Recovery at gain 0.05, added after the capability results (see the report's "What changed after seeing results"). |

## Read before citing

- **Rule scores at steering gain >= 0.2 are artifacts.** The output there is degenerate text (runs of quote
  marks, fragments), which the checker passes on brevity and plain text. Do not cite those cells.
- The `"gain"` keys are exact (0.05 is `0.05`). Progress output from the run printed 0.05 as "0.1"; that was a
  display bug, since fixed, and the data is unaffected.
- `n` is small: 24 prompts per behavior cell, 100 GSM8K and 300 MMLU questions, 5 conversations per arm, of
  which 3 never drifted without help.
