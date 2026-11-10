# Pre-registration: do random directions, as a class, lose to the rules direction? Five more draws on Qwen2.5-1.5B

**Status:** FROZEN when committed. Nothing below may change after the first conversation is run. The runner
(`scripts/replicate_direction_draws.py`) refuses to start unless this file is committed and unmodified. Any later change is a
deviation and must be listed as one in the report, with this text kept.

## Question
The direction control (REPORT 7.8, spec `t0-direction-control.md`) compared the rules direction with **one** random direction
(seed 2718) and found the rules direction better by +0.293 recovery. That is a statement about that draw. A skeptic can say the
draw was unlucky for the random arm. Do random directions, as a class, lose to the rules direction? This study draws five more.

## What was already seen
- The single draw, in full (REPORT 7.8): rules - random +0.293, 95% CI [+0.190, +0.400], 37 wins / 19 ties / 4 losses; random - t2
  +0.058, CI [-0.027, +0.147]; GSM8K drop for that draw 0.3 points [-2.2, +2.9]. Raw data
  `benchmarks/results/qwen2.5-1.5b/direction_control.json` (spec commit `f890c30`, code commit `36e9fc4`).
- The `t2` and `rules` arms for conversation seeds 600-659 (same file). **The conversations are therefore not new; the directions are.**
  This study keeps the 60 conversations fixed so that every draw is paired with the same two reference arms.
- Nothing about any of the five draws below has been run. Their packs have been built (to pin their hashes and screen them), but no
  model has been run with them.

## Fixed in advance (not tunable after any run)
| | |
|---|---|
| Model, decoding, contract, gain, layers, gate, prompts | exactly as in `t0-direction-control.md`: Qwen2.5-1.5B-Instruct fp16, greedy, `max_new_tokens` 96; contract hash `sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e`; gain **0.05**, layers 10-18, uncapped, drift-gated as in ADR-003; pool 2 checksum `5a2f5f48f86f7aac`; 16 turns, shocks at 4 and 10 |
| Conversations | **seeds 600-659 (60)**, the same as the single-draw study; fixed N = 60, none added or dropped; a crashed seed is re-run unchanged |
| Rules pack | `sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f` |
| Random packs | five, each `benchmarks/diagnostics.random_direction_pack(rules_pack, (10, 19), seed)` (one unit vector per layer scaled to the rules pack's norm at that layer): seed 31415 `sha256:9b2083afdbce840f2a64966a2bf954f320085309cf320aad7e17d344c74cc7bf`; seed 27183 `sha256:f643be029dce5d3d68791e76717d1b76e7ac7b647905063b2f1d775870ebf91d`; seed 16180 `sha256:ce4880797ba50af9faa6da0bb810c02442c9dd7c5881adb2c5c99430a13e0be7`; seed 14142 `sha256:1476272ff428ea47589091f556cc426c9bd79074a6a517b3d55b66f4972639b3`; seed 13579 `sha256:16fc2906bc1b204bc3c78bd90575c27f30a237d1b4814a50c0047c250ecafe1b`. The runner refuses any other |
| How the five seeds were chosen | Fixed in advance from the ordered list 31415, 27183, 16180, 14142, 17320, 13579, 11235, 24680: take the first five whose largest absolute per-layer cosine with the rules pack is at most **0.05** (the near-orthogonality screen of the single-draw spec). Seed 17320 was skipped by that screen (0.0704). 11235 and 24680 (also above 0.05) were not reached. The screen does not look at any model output. The runner re-checks it and refuses a pack above 0.05 |
| Reference arms (reused, not re-run) | `t2` and `rules` for seeds 600-659 from `direction_control.json` above. Decoding is deterministic, so a re-run would reproduce them. The runner **verifies this** by re-running seeds 600, 601 and 602 under both arms and requiring every reply and every rule flag to match the committed ones, and refuses to continue (writing no result) if any differs |
| Authorisation | each random arm is `experimental=True` with `gain_ceiling=0.05`, its `STEER` records marked experimental; the arms run one after another (all 60 conversations of one draw, then the next) so each authorisation is set once. The rules re-run for the check runs under Qwen's validated record |

## Outcomes
**Primary.** Per conversation i, `r_i` = the mean over the five draws of recovery (as in 7.4: the share of plain turns after the first
shock that follow all rules), and `d_i = recovery(rules)_i - r_i`. Mean of `d` over the 60 conversations with a percentile
bootstrap 95% CI (10,000 resamples, `numpy` generator seeded 0).

**Decision rule** (implemented and tested as `benchmarks/replication.draws_verdict`). Let *on average* mean(d) > 0 **and** the CI lower
bound > 0, and *every draw* mean of (rules - random draw) > 0 in all five draws separately.
- on average **and** every draw: **"random directions lose to the rules direction (5 of 5 draws)"**
- on average but not every draw: **"the rules direction beats random directions on average, not in every draw (k of 5)"**, naming
  the draws where it did not
- mean(d) < 0 and the CI upper bound < 0: **"random directions do better"**
- otherwise: **"not established across draws"**

In every case the statement also says whether the random arms beat `t2` on average, and in which draws.

**Secondary (all reported).** Per draw: rules - random mean, 95% CI, wins / ties / losses; the spread across draws (minimum, maximum,
standard deviation); the number of draws where rules is ahead and the one-sided sign probability of that count under "each draw is
equally likely to favour either arm" (1/32 if all five); random - t2 averaged over draws and per draw, with the draws whose CI lower
bound is above 0 named; the worst paired difference per draw; the share of turns steered per draw; replies not in English per draw
(`benchmarks/replication.not_english`, the tested function); the trace-mark count per draw. The original draw (seed 2718) is shown
next to the five, as a sixth row, and **enters no decision**.

**Capability.** For every draw, the full GSM8K test split (1,319 problems) with steering always on, paired question by question
with the committed unsteered flags (`replication_pool2_gsm8k_flags.json`); the runner re-runs the first 40 unsteered and refuses to
continue if they differ. Reported: each draw's accuracy and drop with a bootstrap 95% CI, and the mean drop over draws. The pilot's
2-point limit is shown for information only. **No capability result enters the decision.**

## Reading the result
- **"random directions lose" (5 of 5):** the report may say that on Qwen2.5-1.5B, in these conversations, random directions of the
  pack's per-layer size lose to the rules direction, across six draws counting the original. That is a statement about directions
  drawn this way (isotropic Gaussian, near-orthogonal to the pack). It is **not** "the steering direction must be semantically
  correct": that needs a plausible-but-wrong direction, a separate study.
- **On average, not every draw:** the direction matters on average, but some random directions do about as well. The report names them
  and says the single-draw statement was too clean.
- **Not established, or random does better:** the 7.8 statement is weakened to "this one draw" and the report and the paper say so.
- Every number is reported and nothing is changed after seeing results.

## Limitations known before running
- **Five draws is a small sample of directions.** If all five favour rules, the one-sided sign probability is 1/32 = 0.031, and no
  smaller. The bootstrap CI in the primary rule is over the 60 conversations; it does **not** express how much a sixth draw might
  differ. The per-draw rows and the spread are what carry that information. The primary decision therefore also requires every draw to
  be ahead.
- The same 60 conversations are reused. A different set of conversations could differ; this study varies the direction only.
- "Random" here means isotropic Gaussian directions rescaled to the pack's per-layer norms, screened to be near-orthogonal to the
  rules pack. It is not "all directions", and it is not a plausible-but-wrong direction.
- Pool 2 only, one model, one rule set, N = 60 conversations; a small true difference would not be detected.
- Reusing the reference arms depends on determinism, verified on three conversations only (and the check refuses rather than
  guesses). A different GPU or library version could make the check fail; then no result is written.
- The random arms are experiments under the guard and say nothing about safety. The rule checker passes some degenerate text;
  replies are read, not only scored.

## How it is run and recorded
`python scripts/replicate_direction_draws.py` (GPU, about 3.5 hours: roughly 40 minutes per draw, of which about 30 are
conversations and about 10 GSM8K). It writes `benchmarks/results/qwen2.5-1.5b/direction_draws.json` with this spec's commit, the
code commit and whether it was dirty, the pool checksum, all pack hashes and cosines, versions, the determinism check, every random
conversation turn by turn, the analysis and the capability results. The reference arms are cited by file, not copied. Runs are
stored in `.console-demo/replication.db` (arms `dir-draw31415` and so on).
