# OpenGuide

**A control plane for LLM inference trajectories — the last unmanaged layer of the AI stack.**

The AI stack has seven data-plane layers and zero control plane. OpenGuide is
the control plane: the reconciliation loop between the *declared* behavior of an
agent and its *actual* behavior, running for the entire life of every trajectory.

A behavioral contract (**OBC**) declares invariants, phases, triggers, and
recovery. The runtime compiles it to the strongest enforcement channel each
model allows — activation steering on open weights → constrained decoding →
scheduled re-anchoring on closed APIs — measures behavioral state every turn
through typed sensors, reconciles drift against setpoints, and records
everything in a hash-chained, replayable trace. **One contract, any model,
provable behavior.**

## What's here

| Path | What |
|------|------|
| [`spec/`](spec/) | The standard — published first. OBC, behavioral state, trace, conformance vectors. |
| [`spec/obc/`](spec/obc/) | OBC v0.1 JSON Schema + 3 worked contracts |
| [`spec/state/`](spec/state/) | Behavioral State schema + `gen_ai.behavior.*` OTel mapping |
| [`spec/trace/`](spec/trace/) | Trace format: canonical encoding, chain construction, verification, replay |
| [`spec/conformance/`](spec/conformance/) | Golden vectors + an independent runner (the Phase 0 gate) |
| [`guidancegrid/`](guidancegrid/) | Reference runtime (numpy-only): `core/` `obc/` `compiler/` `sensors/` `channels/` `controller/` `store/` `tune/`. |
| [`proxy/`](proxy/) | The wedge — an OpenAI-compatible FastAPI proxy with header-activated governance. |
| [`integrations/`](integrations/) | OpenAI SDK drop-in, LiteLLM callback, LangGraph middleware. |
| [`deploy/compose/`](deploy/compose/) | `docker compose up` → proxy + Jaeger + postgres. |
| [`tests/`](tests/) | Test suite (core invariants, OBC, conformance, runtime gate, proxy). |
| [`docs/`](docs/) | Blueprint, positioning, architecture diagrams, replay-console prototype. |
| [`archive/`](archive/) | The original v0.1.0 reference drop, kept for provenance. |

## Layout

```
OpenGuide/
├── guidancegrid/        # the importable runtime package (no double-nesting)
│   ├── core/  obc/  compiler/  sensors/  channels/  controller/  store/  tune/
├── proxy/               # OpenAI-compatible governance proxy (FastAPI)
├── integrations/        # openai-sdk / litellm / langgraph
├── tests/               # pytest suite
├── spec/                # the standard (obc, state, trace, conformance)
├── docs/                # blueprint + design docs + diagrams
├── deploy/  packs/      # compose stack; SignalPack registry (later phases)
├── archive/             # original v0.1.0 reference
├── pyproject.toml  conftest.py  README.md
```

## Names

- **OpenGuide** — the open standard / project umbrella
- **OBC (Open Behavioral Contract)** — the contract file format
- **GuidanceGrid** — the reference runtime
- **Console** — the dashboard product surface (Phase 3)

## The differentiators

1. **Per-token hash-chained control-signal trace** — tamper-evident, replay-identical.
2. **The `(layer × step)` grid** as a persisted, addressable, composable, learnable artifact.
3. **Behavior as a content-addressed, versioned, eval-scored deployment artifact.**
4. **One contract compiling across the open/closed model divide** (tiered fidelity).

## Prior art, honestly

OpenGuide does **not** guarantee behavior — it biases trajectories
statistically. Control-theoretic steering is established work: **PID Steering**,
**LiSeCo**, and **RE-Control** occupy the closed-loop-control framing, and
**Dynamic Activation Composition** already does time-varying steering — we cite
them, we don't claim to have invented them. The honest delta is **persistence,
addressability, composition, replay, and universality**: the grid as a saved
artifact you can hash, diff, compose, learn, and replay across any model.
Soft floors are reconciled statistically; only `hard` invariants on tier 1/3
are mechanically enforced. Toy results are labeled toy.

## Quickstart (reference runtime)

```bash
python -m pytest          # from repo root: 18 core invariants + OBC + conformance
```

```python
from guidancegrid.obc import load_contract, validate_contract, contract_hash
c = validate_contract(load_contract("spec/obc/examples/coding-agent-default.toml"))
print(contract_hash(c))   # sha256:026d89e9...
```

Verify the spec is self-sufficient (independent of the runtime):

```bash
python spec/conformance/generate.py        # emit golden vectors from the ref impl
python spec/conformance/run_conformance.py # re-derive them from the spec rules alone
```

## Status

**Phase 0 — Spec Core: complete.** OBC schema + 3 contracts, behavioral state +
OTel mapping, trace format spec, golden conformance vectors, and an independent
runner that verifies a reference-runtime trace using the spec docs alone.

**Phase 1 — Universal Runtime: complete.** OBC→tier compiler (capability
resolver), T2 re-anchor + T3 validator channels, typed sensors, the per-turn
reconciler (drift + recovery, single write path through the trace), and a
sqlite CAS + fleet index. Gate: a 50-turn mock agent drifts at turn 30, the
reconciler re-anchors, drift recovers, the trace verifies, and replay is
bit-identical — while an ungoverned counterfactual runs to the halt threshold.

**Phase 2 — The Proxy Wedge: complete.** An OpenAI-compatible FastAPI proxy;
`X-OpenGuide-Contract: <hash>` activates governance with zero app changes
(pass-through by default). Streaming SSE with tool-call delta reassembly,
session continuity that feeds the re-anchor forward across calls, and
`gen_ai.behavior.*` spans. `docker compose up` → point any OpenAI SDK at it →
behavioral state in Jaeger. Governance overhead ≈ 0.4 ms p50.

**Phase 4 — Signal Tier (T0/T1): complete (steering core; real-model evals
pending weights).** Real PyTorch forward-hook activation steering
([`channels/t0_activation.py`](guidancegrid/channels/t0_activation.py)) with
norm-preserving injection, the mechanical Σ-cap, and replay-identical traces;
linear-probe sensors on the residual stream; safetensors SignalPacks + a build
script; and dependency-light constrained decoding for T1
([`channels/t1_decoding.py`](guidancegrid/channels/t1_decoding.py)). The T0
loop is proven on a tiny synthetic model in CI; the Qwen2.5-7B adherence/MMLU
gate is a runnable, honestly-labeled harness
([`scripts/qwen_t0_gate.py`](scripts/qwen_t0_gate.py)) that needs weights + a
GPU. 127 tests total. **Capability-retention numbers are not claimed until that
gate runs on real weights** — see [`packs/README.md`](packs/README.md).

Next: **Phase 3 — Console** (the dashboard). See
[`docs/blueprint.md`](docs/blueprint.md) for the full phase plan.

## License

Apache-2.0 throughout. The spec and runtime are never monetized.
