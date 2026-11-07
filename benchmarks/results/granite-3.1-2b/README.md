# Raw results: Granite-3.1-2B-Instruct (second model)

The data behind `benchmarks/REPORT.md` section 7.7.

| File | Produced by | What it is |
|------|-------------|------------|
| `pilot_capability.json` | `scripts/pilot_second_model.py --capability-only` | The registered capability filter of the gain pilot (`docs/preregistration/t0-second-model-pilot.md`): per-question GSM8K correctness on the first 300 test problems with no steering and with steering always on at 0.025, 0.05 and 0.075, the drops and their intervals, the eligibility result ("no gain is eligible; the rule says stop"), and the provenance (spec commit, code commit, weights revision, pack hash and norm report). |

The pilot's 80 conversations were not run: the rule stops the pilot when no gain is eligible, and conversations cannot change that.
A smoke run on two other seeds (not committed) was used only to check the pipeline.
