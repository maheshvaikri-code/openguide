# GuidanceGrid (reference implementation)

A **literal** control grid over `(layer × step)` for LLM inference:
total, frame-tiled, algebraic, hash-addressed, learnable. numpy only.

> Prompts set initial conditions. Weights are the physics.
> GuidanceGrid governs the trajectory.

## The five commitments that make it a grid

1. **Totality** — `G[l, t]` answers at every coordinate; unset = 0.
2. **Frames** — time discretized into fixed-width frames; storage is a
   sparse dict of dense `(L × W)` float32 tiles. Sparse globally, dense
   locally. Triggers write into upcoming frames; nothing breaks.
3. **Algebra** — fields close under `+`, scalar `*`, `mask`, `shift_t`,
   `crop`; grids compose: `G3 = G1 ⊕ α·G2`. Behavior profiles mix.
4. **Tiles** — columns are contiguous arrays; one fused evaluation per step.
5. **Differentiability** — the grid is a parameter. `grid_tune()` learns
   the schedule by gradient descent against a measurable setpoint and
   finds the minimal sufficient intervention (62% less gain than the
   best constant steering at the same adherence floor, on the toy plant).

## Parts

| artifact     | role                          | identity        |
|--------------|-------------------------------|-----------------|
| Spec         | declarative program           | `spec_hash`     |
| SignalPack   | per-model steering vectors    | content hash    |
| Grid         | compiled gain fields          | `grid.hash()`   |
| Trace        | hash-chained flight recorder  | head hash       |
| Manifest     | replay key (all of the above) | `chash`         |

## Properties enforced by tests (18/18)

- any cell, any time: totality + bounds
- schedule semantics: ramp monotone, decay halves at τ·ln2
- algebra closure: cellwise add, mask/shift/crop, grid compose
- determinism: spec/pack/grid hashes stable, sensitive to any change
- physics: norm-preserving injection (‖h′‖ = ‖h‖, direction moves)
- Σ-cap enforced mechanically, correction recorded
- control channel: knobs + triggers effective AND recorded (no side doors)
- tamper detection: edit any record → `verify()` fails
- replay identity: same manifest ⇒ bit-identical trace heads
- grid tuning: converges, holds the setpoint, beats constant baseline,
  learned profile ramps where drift grows

## Run

```
python -m pytest tests/ -q      # 18 passed
python demo.py                  # end-to-end loop
```

## Honest scope

This is the **control plane**, proven on a toy plant and toy vectors.
Not yet included: real model hooks (PyTorch/vLLM/llama.cpp), real signal
derivation (probes/SAEs on actual activations), capability-retention
evals, `(layer, site, step)` sub-layer addressing. The grid governs
trajectories statistically; it does not command outputs.
