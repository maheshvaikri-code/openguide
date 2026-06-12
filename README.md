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
| [`guidancegrid/`](guidancegrid/) | Reference runtime (Python, numpy-only): `core/` + `obc/` + `tune/`. The literal `(layer × step)` control grid. |
| [`tests/`](tests/) | Test suite (core invariants, OBC validation, conformance gate). |
| [`docs/`](docs/) | Blueprint, positioning, architecture diagrams, replay-console prototype. |
| [`deploy/`](deploy/), [`packs/`](packs/) | Compose skeleton and SignalPack registry (filled in later phases). |
| [`archive/`](archive/) | The original v0.1.0 reference drop, kept for provenance. |

## Layout

```
OpenGuide/
├── guidancegrid/        # the importable package (no double-nesting)
│   ├── core/  obc/  tune/
├── tests/               # pytest suite
├── spec/                # the standard (obc, state, trace, conformance)
├── docs/                # blueprint + design docs + diagrams
├── deploy/  packs/      # filled in later phases
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
runner that verifies a reference-runtime trace using the spec docs alone. The
reference runtime's 18 core invariants pass; 32 tests total.

Next: **Phase 1 — Universal Runtime** (OBC→tier compiler, T2/T3 channels,
sensors, per-turn reconciler, CAS store). See
[`docs/blueprint.md`](docs/blueprint.md) for the full phase plan.

## License

Apache-2.0 throughout. The spec and runtime are never monetized.
