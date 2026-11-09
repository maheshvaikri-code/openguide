# Pre-registration: a gain ladder for Granite-3.1-2B-Instruct (GSM8K only)

**Status:** FROZEN when committed, before any ladder gain has been run. The runner (`scripts/granite_gain_ladder.py`) refuses to
start unless this file is committed and unmodified.

## Question
The Granite pilot (REPORT 7.7, `t0-second-model-pilot.md`) stopped because no gain in {0.025, 0.05, 0.075} had a GSM8K drop of 2
points or less; the lowest, 0.025, cost 6.3 points. Is there any lower gain at which the capability cost disappears?

## What was already seen
GSM8K, first 300 problems, steering always on: drops of +6.3 [+1.0, +11.7] (0.025), +19.7 (0.05) and +42.3 (0.075). Random
directions of the same per-layer norms at 0.025 also cost 3.7 points on average (exploratory, 7.7).

## Fixed in advance
| | |
|---|---|
| Model | `ibm-granite/granite-3.1-2b-instruct`, revision `bbc2aed595bd38bd770263dc3ab831db9794441d` (the runner refuses any other), bfloat16 |
| Steering | the Granite pack `sha256:2744d39efb975a6c456e2fa2ff3807db19a337c1866995cf4fb7a50bcedcd1b5`, layers 14-26, the same envelope and norm-preserving injection |
| **Gains** | **{0.0125, 0.00625}** (half and a quarter of the lowest pilot gain). No other gain is run |
| Data | the first 300 problems of the GSM8K test split, in dataset order, steering always on; the generation settings of the pilot (`max_new_tokens` 320, batch 20, the same prompt) |
| Baseline | the unsteered results of the registered pilot (`benchmarks/results/granite-3.1-2b/pilot_capability.json`), paired question by question. Decoding is deterministic; the runner re-runs the first 40 problems unsteered and refuses to continue if they differ |
| Conversations | **none** in this run |

## Outcomes and rule
For each gain: accuracy, the drop against none in points and its bootstrap 95% CI (10,000 resamples, `numpy` seeded 0), and whether
it is **eligible** (drop <= 2 points, the pilot's rule). The report states one of:
- **"eligible at g"** for the highest eligible gain; or
- **"no eligible gain found down to 0.00625"** if neither qualifies.
Every number is reported whatever the outcome. The gains are not changed after seeing results.

## What a result would and would not mean
- An eligible gain would say only that the capability cost is within noise at 300 problems, where a 2-point difference is well inside
  sampling noise (an interval of roughly +/-5 points). It would **not** show that steering helps recovery on Granite (no
  conversations are run), and it would **not** make Granite validated: the guard still refuses it until it has a record with its own
  recovery evidence.
- A "none eligible" result would complete the transfer finding with a measured floor: no gain down to 0.00625 is capability-safe on
  Granite by this rule.
- Going further (Granite conversations) would first need a stop rule for its sign-off behaviour (it does not end its turn after
  `[END]`), and is only worth doing if a gain is eligible.

## How it is run and recorded
`python scripts/granite_gain_ladder.py` (GPU). It writes `benchmarks/results/granite-3.1-2b/ladder.json` with this spec's commit,
the code commit and whether it was dirty, the weights revision, the pack hash, versions, the per-question results and the analysis.
