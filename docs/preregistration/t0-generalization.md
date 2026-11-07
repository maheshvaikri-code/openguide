# Pre-registration: T0 steering on a new prompt pool, with a tighter capability test

**Status:** FROZEN when committed. Nothing below may change after the first registered conversation is run. The runner
(`scripts/replicate_pool2.py`) refuses to start unless this file is committed and unmodified, and records its commit.
Any later change is a deviation and must be listed as one in the report, with this text kept.

## Question
Does drift-gated T0 steering (ADR-003, uncapped, gain 0.05) still raise recovery when the user prompts are new, and
does it avoid harming the model's general ability under a stricter test than the first replication used?

## What was already seen (so this is not mistaken for a blind test)
- Seeds 100-159 (REPORT 7.4): recovery 68.5% -> 90.8%, paired +0.223, 95% CI [+0.135, +0.313]. Seeds 200-259, uncapped
  arm of the cap study (7.5): +0.262, CI [+0.178, +0.350]. Pooled over 120 conversations: +0.242. One conversation in 120
  collapsed (1.00 -> 0.00). Both used prompt pool 1.
- GSM8K with steering always on (7.4, n = 300): drop 1.7 points, 95% CI of the drop [-4.7, +7.7]. That passed the rule used
  then (point estimate <= 5). Under the stricter rule below it would have read "harm not ruled out".
- A cap on consecutive steered turns did not help (7.5) and is **not** used here.

## Fixed in advance (not tunable after any run)
| | |
|---|---|
| Model, decoding | Qwen2.5-1.5B-Instruct, local fp16, greedy, `max_new_tokens` 96 for conversations |
| Contract | `support-plain-brief`, hash `sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e` |
| Steering | gain **0.05**, layers 10-18, **uncapped** (no `max_consecutive`), pack `sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f` (pinned) |
| **Prompts** | **a new pool of 40** (24 plain, 16 tempting): `benchmarks/prompts_v2.py`, committed in `51529a7` before this spec, checksum `5a2f5f48f86f7aac`. It shares no prompt with pool 1 or with the 12 prompts the pack was derived on (tested). Selected with `pool="v2"` |
| Conversations | **seeds 300-359 (60)**; 16 turns; shocks at 4 and 10; generator `benchmarks/real_model.user_turns` |
| Sample size | fixed N = 60, no early stopping, no seeds added or dropped; a crashed seed is re-run unchanged |
| Arms | `t2` vs `t2+t0` on identical conversations, paired |
| Capability | **the full GSM8K test split (1,319 problems)** and MMLU n = 500 (the existing loader, `random.Random(0)`), steering **always on** at 0.05 vs none, paired question by question |

## Outcomes
**Primary (recovery).** As in 7.4: per conversation, the share of its plain turns after its first shock turn that follow all
rules (`benchmarks/real_model.check`). d_i = recovery(t2+t0) - recovery(t2), paired by seed.

**Secondary.** The same difference for the conversations that drift under t2 (recovery < 1) with their count (**underpowered**
if fewer than 20); exact sign test; all-turn and shock-turn compliance per arm; share of turns steered; shortest reply and
replies under 3 words; replies not in English (a letter outside the Latin script); the worst paired difference; and, as
context only, t2's mean recovery on this pool against the 120 earlier conversations.

**Capability.** Accuracy per condition with 95% Wilson intervals, and the paired drop (none minus steered) in percentage
points with a percentile bootstrap 95% CI over questions (10,000 resamples, `numpy` generator seeded 0).

## Analysis
Mean of d_i over all 60 conversations with a percentile bootstrap 95% CI over conversations (10,000 resamples, `numpy`
generator seeded 0). No other tests, no multiplicity adjustments, no subgroup searches.

## Decision rules
**Benefit (PASS):** mean d_i >= +0.10 **and** the CI lower bound > 0.

**Capability (GSM8K, steering always on)**, using the drop and the *upper* end of its 95% CI, in points:
| Drop | Upper CI bound | Reported as |
|---|---|---|
| <= 5 | <= 5 | **no harm shown** |
| <= 5 | > 5 | **harm not ruled out** (reported as such; not a pass) |
| > 5 | any | **harm** |

Outcomes the report will use: benefit PASS and *no harm shown* -> "supports (new prompts)"; benefit PASS and *harm not
ruled out* -> "benefit shown; harm not ruled out"; benefit PASS and *harm* -> "benefit shown; harm"; benefit FAIL ->
"no benefit shown", with the capability category beside it. MMLU gets the same categories for information only; it does
not enter the outcome. Every number is reported whatever the outcome; nothing is changed after seeing results.

## Limitations known before running
- **New prompts, same author and style.** Pool 2 was written by the same system that wrote pool 1, in the same style, for
  the same app and the same rules, without looking at any model's behaviour on it. It tests new content, not a different
  kind of conversation, rule set or model.
- **Pool 2's difficulty was not measured beforehand.** If t2 already complies on almost every conversation there is little
  to recover and the primary bar cannot be met whatever steering does; the count of drifting conversations is reported for
  this reason. The bar is not changed.
- The primary bar averages over all 60 conversations, as before.
- One model, one rule set, one pack. The rule checker passes some degenerate text; replies are read, not only scored.
- Capability is measured with steering always on, the worst case, not through the loop.
- Even at 1,319 problems the GSM8K interval has a width of several points; a result of "harm not ruled out" is a limit on
  what the sample can show, not evidence of harm.

## How it is run and recorded
`python scripts/replicate_pool2.py` (GPU). It writes `benchmarks/results/qwen2.5-1.5b/replication_pool2.json` with the spec's
commit, the code commit and whether it was dirty, the pool checksum, hashes, versions, every turn of every conversation, the
analysis and the verdict computed by `benchmarks/replication.py`. Runs are stored in `.console-demo/replication.db` (arms
`pool2-t2` and `pool2-t2t0`).
