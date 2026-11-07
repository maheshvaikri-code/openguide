# Pre-registration: the pilot that sets the steering gain for a second model (Granite-3.1-2B-Instruct)

**Status:** FROZEN when committed, before the Granite pack is derived and before any pilot data exists. The runner
(`scripts/pilot_second_model.py`) refuses to start unless this file is committed and unmodified. The registered study
(`t0-second-model.md`) is written only after this pilot, with the values it selects.

## Question
The T0 recipe was developed and tested on Qwen2.5-1.5B-Instruct. Before a registered test on a second model, what gain does
that model need, chosen by a rule fixed in advance rather than by hand?

## Model
`ibm-granite/granite-3.1-2b-instruct`, **Hugging Face revision `bbc2aed595bd38bd770263dc3ab831db9794441d`** (the runner
refuses weights that record any other revision), bfloat16, greedy decoding, `max_new_tokens` 96, 40 decoder layers, hidden size
2048. It was chosen because it is open (Apache-2.0), needs no token, comes from a different lab with different training, and
fits the 8 GB GPU without quantization. Its chat template supports a system role, so the prompt format is unchanged.

**Architecture note (a limit, stated now):** Granite is a Llama-style dense decoder (`GraniteForCausalLM`), like Qwen. This tests
transfer to another lab's training, not to a different architecture.

## What is held the same as the Qwen studies
Contract (`sha256:14014a6e8584ac07f8a78cb575e83c6fd7572b773acdb348223e9b644fd0a12e`), the drift gate, uncapped steering,
rule checker, 16 turns, shocks at turns 4 and 10, the paired t2 / t2+t0 design.

## What is set for this model, and how
1. **Pack.** Derived for Granite by the same procedure as Qwen's: the same 12 held-out derivation prompts, the same system
   prompts with and without the rules, the mean difference of the residual stream at the last prompt token per layer, scaled to
   the typical residual norm there. Its hash and a per-layer norm report are recorded after derivation and before the pilot.
2. **Layers, fixed a priori, not swept.** Qwen's band is layers 10 to 18 of 28. Mapped to Granite's depth by
   `lo = round(40 x 10/28) = 14`, `hi = round(40 x 19/28) = 27` (exclusive): **layers 14 to 26** (13 layers). If this band does
   not work on Granite, that is the finding; a search over bands would be its own study.
3. **Gain is relative, so no rescaling.** Each pack vector has the norm of the typical residual at that layer, and injection is
   renormalised to the hidden state's norm (`inject_torch`), so a gain of 0.05 means about 5% of a typical residual norm on any
   model. Granite's embedding (x12) and residual (x0.22) multipliers change its absolute residual norms, which the pack's own
   measurement absorbs. The candidate gains therefore stay **{0.025, 0.05, 0.075}**; the norm report is kept as the check.
4. **A different cumulative dose, stated.** The gain is the *peak* of a gaussian envelope across the band. A 13-layer band has a
   larger envelope sum than Qwen's 9 (in-band sum 8.8 against 5.9), so the same peak gain is about 1.5x the total push on
   Granite. The candidate grid brackets the Qwen-equivalent dose (Granite 0.025 is about 0.7x of it, 0.05 about 1.5x). The grid is not changed.
5. **Gain ceiling.** The code's default ceiling (0.05) is Qwen's measured one. For this pilot only, the runner passes
   `gain_ceiling = 0.075` so that 0.075 can be tried. It can never exceed the hard limit of 0.1.

## Pilot data (not reused in the registered study)
- **Conversations:** pool 1, **seeds 400-419** (20), 16 turns, shocks at 4 and 10. Arms on identical conversations: `t2`, and
  `t2+t0` at each of the three gains.
- **Capability:** the **first 300 problems of the GSM8K test split, in dataset order**; steering always on at each gain, against none.

## Selection rule
For each gain g: **R(g)** = mean over the 20 conversations of (recovery with steering at g) minus (recovery under t2), with
recovery defined as in the earlier studies (`benchmarks/replication.recovery`); **D(g)** = GSM8K accuracy under no steering minus
under steering at g, in percentage points (point estimate).

A gain is **eligible** if D(g) <= 2.0. Choose the eligible gain with the **highest R(g)**; if two are equal (within 1e-9), the
lower gain. **If no gain is eligible, stop and report; the registered study is not run.** The pack, layers and gain are then frozen
and written into the second-model study's spec before any registered run.

## Reporting
Every number for all three gains is reported, including the ones not chosen.

## Limitations known before running
- The pilot is small (20 conversations): R(g) is noisy, and ties or near-ties are likely between gains.
- With 300 problems, a GSM8K difference of 2 points is well inside sampling noise (an interval of about +/-5 points), so eligibility
  is a coarse filter, not evidence of no harm. The registered study uses all 1,319 problems and the stricter three-way rule.
- The rule does not require R(g) to be positive for the chosen gain. If the chosen gain has R(g) <= 0 the result is reported as it
  stands and whether to proceed is left to the project owner.
- The pilot uses prompt pool 1 and the registered study pool 2.
- One extra constraint of this pilot: the ceiling is raised to 0.075 only here, on no evidence for Granite beyond the pilot itself.

## How it is run and recorded
`python scripts/pilot_second_model.py --profile granite` (GPU). It writes `benchmarks/results/granite-3.1-2b/pilot.json` with this
spec's commit, the code commit and whether it was dirty, the weights revision, the pack hash and norm report, versions, every
conversation turn by turn, the GSM8K per-question results, the computed R(g) and D(g), and the selected gain or the reason
for stopping.
