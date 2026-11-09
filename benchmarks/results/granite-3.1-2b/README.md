# Raw results: Granite-3.1-2B-Instruct (second model)

The data behind `benchmarks/REPORT.md` section 7.7.

| File | Produced by | What it is |
|------|-------------|------------|
| `pilot_capability.json` | `scripts/pilot_second_model.py --capability-only` | The registered capability filter of the gain pilot (`docs/preregistration/t0-second-model-pilot.md`): per-question GSM8K correctness on the first 300 test problems with no steering and with steering always on at 0.025, 0.05 and 0.075, the drops and their intervals, the eligibility result ("no gain is eligible; the rule says stop"), and the provenance (spec commit, code commit, weights revision, pack hash and norm report). |
| `diagnostics.json` | `scripts/diagnose_granite_sensitivity.py` | **Exploratory** (not pre-registered; run after the pilot stopped): D2, the median write ratio of every decoder layer of Qwen and Granite on one fixed chat with the steering push-to-write ratios; D1, three random-direction controls on Granite's GSM8K (gain 0.025, same per-layer norms as the rules pack), per-question results included. |
| `ladder.json` | `scripts/granite_gain_ladder.py` | The pre-registered gain ladder (`docs/preregistration/t0-granite-ladder.md`): per-question GSM8K results at gains 0.0125 and 0.00625 against the pilot's unsteered baseline, the drops and intervals, the statement "eligible at 0.0125", and the provenance. |

The pilot's 80 conversations were not run: the rule stops the pilot when no gain is eligible, and conversations cannot change that.
A smoke run on two other seeds (not committed) was used only to check the pipeline.
