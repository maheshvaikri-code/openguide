# Pre-registration: a cap on consecutive steered turns

**Status:** FROZEN when committed. Nothing below may change after the first conversation is run. The runner
(`scripts/replicate_cap.py`) refuses to start unless this file is committed and unmodified, and records its commit.
Any later change is a deviation and must be listed as one in the report, with this text kept.

## Question
The T0 replication (`benchmarks/REPORT.md` 7.4) met its bars but showed a failure mode: when the gate keeps firing,
steering stays on and stops helping. Does limiting consecutive steered turns keep the benefit and reduce the harm?

## What was already seen (so this is not mistaken for a blind test)
- In the 7.4 data (seeds 100-159) the first steered turn followed all rules 87% of the time (n = 146), the second in a
  row 47%, the third 10%, the fourth 0%. In 7 of 60 conversations steering stayed on for 8 or more turns; their mean
  paired difference was -0.04 against +0.26 for the other 53. The worst, seed 130, went 1.00 -> 0.00 because the
  steered replies wrote `END` without the brackets, so the sign-off rule never passed and the gate never switched off.
- The cap values below (2 and 3) were **chosen from that data.** They are tested here on conversations never run before.
  That is the reason for this study; it is not a blind test of the idea.

## Fixed in advance (not tunable after any run)
| | |
|---|---|
| Model, decoding | Qwen2.5-1.5B-Instruct, local fp16, greedy, `max_new_tokens` 96 |
| Contract | `support-plain-brief`, hash `sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e` |
| Steering | gain 0.05, layers 10-18, the same pack `sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f` (pinned) |
| Conversations | **seeds 200-259 (60)**, never used before; 16 turns; shocks at 4 and 10; generator `benchmarks/real_model.user_turns` |
| Sample size | fixed N = 60, no early stopping, no seeds added or dropped; a crashed seed is re-run unchanged |
| Language / coherence sensor | **off in all arms.** It is a separate change and is tested separately |

## Arms (paired: identical conversations)
1. `t2`: the proxy's text re-anchoring only.
2. `uncapped`: `t2` plus drift-gated steering exactly as in 7.4.
3. `capped`: `uncapped` plus the cap.

**The cap (precise).** After each turn is scored, the gate decides whether the *next* generation is steered. It
counts consecutive steered generations (a generation counts as steered only if the upstream reports it was). When the
gate wants steering and 2 consecutive steered generations have just occurred, the next **3** turns are not steered,
whatever the gate says (the text re-anchor still runs). After those 3 turns steering is eligible again. With a gate
that fires every turn, the steered turns are therefore 1, 2, 6, 7, 11, 12, ...

## Outcomes
**Primary (recovery).** As in 7.4: per conversation, the share of its plain turns after its first shock turn whose reply
follows all rules (`benchmarks/real_model.check`). Differences are paired by seed.

**Registered comparisons** (each: mean paired difference with a percentile bootstrap 95% CI over conversations, 10,000
resamples, `numpy` generator seeded 0): `capped - t2`; `uncapped - t2`; `capped - uncapped`.

**Also reported:** the distribution of steered turns per conversation for each steered arm; shock-turn compliance per
arm; replies not in English; the drifting subset (t2 recovery < 1) and its size; the worst paired difference per arm.

**Operational definitions.** *Loss*: a conversation where the arm's recovery is lower than `t2`'s by more than 1e-9.
*Worst paired difference*: the minimum over seeds of (arm recovery - t2 recovery). *Not in English*: a reply that contains
at least one alphabetic character outside the Latin script (by Unicode name).

## Decision rule
**PASS requires all three:**
1. **Benefit kept:** `capped - t2` mean >= +0.10 **and** its CI lower bound > 0.
2. **Harm reduced:** losses of `capped` (vs `t2`) are **fewer than** losses of `uncapped` (vs `t2`), on the same seeds. The
   worst paired difference is reported for both arms.
3. **Not worse than uncapped:** the CI lower bound of `capped - uncapped` >= -0.05.

What the report will say: all three pass -> "supports"; the cap may then become the default, as a separate, reviewed
change. Fails (1) -> the benefit depended on sustained steering. Fails (2) -> the cap did not reduce losses. Fails (3) ->
the cap costs more than 5 points against uncapped. Every number is reported whatever the outcome; the cap values, gain,
seeds and thresholds are not re-tuned after seeing results.

## Not re-run
Capability (GSM8K, MMLU). The cap only removes steering relative to `uncapped`, so exposure can only fall; the worst case
(steering always on) was measured in 7.4. This is stated here so it is not mistaken for an omission.

## Limitations known before running
- The cap values come from data seen. Seeds 200-259 are fresh, but the prompts are the same 40-prompt pool (24 plain,
  16 tempting): new conversations, not new content.
- Condition 2 compares counts of losses, which are sensitive to small differences (a drop from 1.00 to 0.90 is a loss).
  It does not weigh how large the losses are; the worst paired difference is reported for that reason.
- Condition 1 is on the mean over all 60 conversations, as in 7.4, so it depends on how many conversations drift.
- One model, one rule set, one pack.
- The rule checker passes some degenerate text; replies are read, not only scored.

## How it is run and recorded
`python scripts/replicate_cap.py` (GPU). It writes `benchmarks/results/qwen2.5-1.5b/replication_cap.json` with the spec's
commit, the code commit and whether it was dirty, the hashes, versions, every turn of every conversation, the analysis,
and the verdict computed by `benchmarks/replication.py`. Runs are stored in `.console-demo/replication.db`
(arms `cap-t2`, `cap-uncapped`, `cap-capped`).
