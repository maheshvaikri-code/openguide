# OpenGuide benchmark report (simulated)

**Status: SIMULATED.** Every number here comes from a deterministic mock-agent
simulation, not a real model. It exists to (a) fix the methodology and (b) wire
the harness end to end. Real closed-model (GPT/Claude) and open-model
(Qwen/Llama) numbers require API keys / weights and **replace** these results;
they are published regardless of outcome, per the blueprint's kill criteria.

Reproduce: `make bench` (or `python benchmarks/t1_bench.py` /
`python benchmarks/drift_bench.py`).

## 1. The intervention benchmark (T1 gate)

**Question (kill criterion):** does scheduled contract re-anchoring beat naive
fixed-cadence re-prompting *at equal token cost*? If naive matches at equal
cost, OpenGuide scopes to observability + open-weight tiers and says so.

**Method.** A coding agent over 60 turns under a disturbance (slow late-growing
decay + irregular scope-creep shocks). Three arms share the same restore
strength and per-intervention token cost, so only *timing* differs:

- `none` — no intervention (floor)
- `naive` — re-prompt every K turns; K tuned so naive's token spend matches the
  contract arm (adherence-at-equal-cost)
- `contract` — the real OpenGuide reconciler: re-anchor only when drift crosses
  the contract threshold (reactive). Runs the actual control path + trace.

Two regimes: `steady` (continuous decay, regular shocks) and `sparse` (mostly
healthy, rare large shocks).

**Simulated result.** Contract beats naive at equal cost in both regimes, and
decisively under sparse irregular shocks — fixed cadence either wastes budget
re-prompting a healthy agent or misses a shock, while reactive re-anchoring
spends only when drift demands it:

| regime | arm | mean adherence | % in violation | tokens |
|--------|-----|---------------:|---------------:|-------:|
| steady | naive | 0.819 | 57% | 11,710 |
| steady | **contract** | **0.869** | **38%** | 11,840 |
| sparse | naive | 0.802 | 62% | 11,190 |
| sparse | **contract** | **0.913** | **17%** | 11,320 |

**Sensitivity (honest caveat).** This depends on the contract's
`drift_threshold`. With the *default* coding-agent threshold (0.27), the
reconciler only re-anchors near catastrophe, and naive fixed-cadence holds the
floor better — i.e. a poorly-tuned contract loses this benchmark. The result
above uses a floor-targeting benchmark contract
([`bench_contract.toml`](bench_contract.toml), `drift_threshold = 0.05`). The
takeaway: the *value is in reactive timing*, and threshold tuning is a
first-class part of authoring a contract.

## 2. The drift benchmark

Turn-wise behavioral divergence (after "Drift No More?", arXiv:2510.07777),
summarized by area-under-drift (cumulative floor deficit), peak drift, turns in
violation, and recovery time.

**Simulated result (governed vs ungoverned):**

| regime | area-under-drift (ungoverned → governed) | peak drift | recovery |
|--------|-----------------------------------------:|-----------:|---------:|
| steady | 33.19 → 1.19 | 0.85 → 0.18 | never → 1 turn |
| sparse | 23.13 → 0.86 | 0.81 → 0.26 | never → 4 turns |

The governed trace verifies in both regimes — every recovery is recorded and
replayable.

## 3. Capability retention

MMLU + GSM8K delta at a gain ladder per pack — **requires a real model + GPU**;
slots are present and unfilled in each pack's `eval_card.json`. See
[`../scripts/qwen_t0_gate.py`](../scripts/qwen_t0_gate.py) and
[`../packs/README.md`](../packs/README.md). No retention numbers are claimed
until that harness runs on weights.

## 4. Case studies (reference scenarios — simulated)

- **Coding-agent fleet** — [`fleet_gen.py`](fleet_gen.py) generates realistic
  runs into the store's fleet index (drift / recovery / halt distributions).
- **Multi-tenant support** — [`../examples/multi-tenant/`](../examples/multi-tenant/):
  one model, per-tenant temperament as a composed `tenant ⊕ task` grid; each
  tenant is a distinct content-hashed grid.
- **Injection detection** — [`../examples/injection-detection/`](../examples/injection-detection/):
  a poisoned page is caught the moment context-obedience overtakes
  user-adherence — a behavioral-state shape, detected before the agent acts.

## 5. Threats to validity

The simulation is favorable to the control plane by construction (the restore
model is idealized and the disturbance is synthetic). It demonstrates the
*shape* of the expected result and exercises the real control path, but the
magnitude means nothing until the real-model harness runs. Treat §1–§2 as a
methodology preview, not evidence.
