# Pre-registration: is it the rules direction? A random-direction control on Qwen2.5-1.5B, in conversations

**Status:** FROZEN when committed. Nothing below may change after the first conversation is run. The runner
(`scripts/replicate_direction_control.py`) refuses to start unless this file is committed and unmodified. Any later change is
a deviation and must be listed as one in the report, with this text kept.

## Question
Three pre-registered studies (REPORT 7.4-7.6) show that drift-gated steering raises recovery. They do not show that the *rules
direction* is what does it: a push of the same size in a random direction might shake the model out of a bad pattern just as well.
Does the benefit depend on the direction?

## What was already seen
- Rules-pack steering: recovery +0.22, +0.26 and +0.40 over three sets of 60 conversations (7.4-7.6); GSM8K 778 -> 771 of 1,319
  (a drop of 0.5 points, CI [-2.3, +3.3]) with steering always on.
- On Granite (not Qwen), a random push of the pack's size also lowered GSM8K (REPORT 7.7, exploratory D1). No random-direction
  control has been run on Qwen, in conversations or on GSM8K.

## Fixed in advance (not tunable after any run)
| | |
|---|---|
| Model, decoding | Qwen2.5-1.5B-Instruct, local fp16, greedy, `max_new_tokens` 96 for conversations |
| Contract | `support-plain-brief`, hash `sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e` |
| Steering | gain **0.05**, layers 10-18, **uncapped**, drift-gated as in ADR-003, the same drift gate and re-anchor in every arm |
| Rules pack | `.models/steering/qwen2.5-1.5b-instruct.safetensors`, `sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f` |
| Random pack | one unit vector per layer in the band, scaled to the rules pack's norm at that layer, drawn by `benchmarks/diagnostics.random_direction_pack(rules_pack, (10, 19), seed=2718)`; hash `sha256:468a3c1d6d1b0a74acce9e7d94e134eb36d97855f860b54fba40a9732c9a65c2` (the runner refuses any other); its cosine with the rules pack is within +/-0.05 at every layer |
| Prompts | pool 2: `benchmarks/prompts_v2.py`, checksum `5a2f5f48f86f7aac` |
| Conversations | **seeds 600-659 (60)**, never used before; 16 turns; shocks at 4 and 10 |
| Sample size | fixed N = 60, no early stopping, no seeds added or dropped; a crashed seed is re-run unchanged |
| Arms (paired, identical conversations) | `t2`; `rules` (t2 + steering with the rules pack); `random` (t2 + steering with the random pack) |
| Authorisation | `t2` and `rules` run under Qwen's validated record. `random` is not the validated pack, so it runs with `experimental=True` and `gain_ceiling=0.05`, and its `STEER` records are marked experimental. The arms are run one after another (all 60 of one arm, then the next) so each authorisation is set once; decoding is deterministic, so order does not matter |

## Outcomes
**Primary.** Per conversation, recovery as in 7.4 (the share of plain turns after the first shock that follow all rules).
d_i = recovery(rules) - recovery(random), paired by seed. Mean over the 60 with a percentile bootstrap 95% CI (10,000 resamples,
`numpy` generator seeded 0).

**Decision rule.** If the mean is above 0 **and** the CI lower bound is above 0: **"the benefit depends on the rules direction"**.
Otherwise the report says so in one of three ways: the CI includes 0 ("a random push of the same size does not differ detectably");
the mean is below 0 with the CI upper bound below 0 ("a random push does better"); and in every case whether the random arm itself
beat `t2` (below).

**Secondary.** random - t2 (does any push help?), mean with the same bootstrap CI; rules - t2 (replicating 7.4-7.6);
wins/ties/losses and sign test for each comparison; the conversations that drift under `t2` and their number; the worst paired
difference for each steered arm; the share of turns steered per arm; replies not in English; shock-turn compliance.

**Capability.** The full GSM8K test split (1,319 problems, the existing loader's order), steering **always on** at 0.05 with the
random pack. Paired question by question with the unsteered and rules-pack results of the 7.6 run, committed as
`benchmarks/results/qwen2.5-1.5b/replication_pool2_gsm8k_flags.json` before this spec. Decoding is deterministic; the runner
re-runs the first 40 problems unsteered and refuses to continue if they differ from the committed flags. Reported: the random
arm's accuracy, its drop against none with a bootstrap 95% CI, the same for the rules pack (+0.5 points in 7.6), and the random
minus rules difference. The three-way harm category is given for information; it does not enter the decision.

## Reading the result
- **Rules beats random:** the write-up may say the rules direction, and not just any push at the right moment, drives the
  effect on Qwen, on this single random draw.
- **Random does about as well:** the honest claim becomes "a small push at the right moment helps recovery", which is weaker and
  still publishable; the report and the paper must say so.
- Either way every number is reported and nothing is changed after seeing results.

## Limitations known before running
- **One random direction.** A pass shows the rules direction beat *this* random draw. A different draw could do better or worse.
  A fail (no detectable difference) is informative whatever the draw. More draws would be a separate, larger study.
- The random pack is near-orthogonal to the rules pack, which is what a random direction is; it is not a *matched-but-wrong*
  direction (for example the rules direction from a different rule set). That would answer a different question.
- With N = 60 paired conversations, a small true difference between rules and random would not be detected.
- Pool 2 only, one model, one rule set. The primary bar is on the mean over all 60 conversations.
- The random arm is an experiment under the guard (`experimental`), not a validated configuration, and says nothing about safety.
- The rule checker passes some degenerate text; replies are read, not only scored.

## How it is run and recorded
`python scripts/replicate_direction_control.py` (GPU). It writes
`benchmarks/results/qwen2.5-1.5b/direction_control.json` with this spec's commit, the code commit and whether it was dirty, the
pool checksum, both pack hashes, versions, every conversation turn by turn, the analysis and the capability results.
Runs are stored in `.console-demo/replication.db` (arms `dir-t2`, `dir-rules`, `dir-random`).
