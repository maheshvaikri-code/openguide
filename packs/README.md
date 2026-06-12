# SignalPacks

A **SignalPack** holds the per-layer steering vectors a model needs for the T0
(activation) tier — one set of vectors per signal, content-addressed by hash and
referenced from an OBC contract's `[signals]` table by `pack = "sha256:…"`.

Reference signals (starter pack v0):

| Signal | Intent |
|--------|--------|
| `anchor` | hold the declared task / instruction adherence |
| `precision` | tighten output around tool-call / structured moments |
| `explore` | widen during planning phases |
| `syc-damp` | damp sycophantic drift toward the user's framing |

## Build

```bash
# deterministic synthetic pack (tests / demos):
python packs/build_pack.py --synthetic --model synthetic-7b --layers 32 --dim 64 --out packs/synthetic/
```

Each build writes `pack.safetensors` (content-addressed vectors) and
`eval_card.json` (pack hash, signals/layers, and eval slots).

## Honest scope

Real packs derive vectors from **activations captured on a specific model**
(contrast pairs → `unit(mean(pos) − mean(neg))` per layer) and are validated
with capability-retention evals (MMLU / GSM8K delta at a gain ladder, coherence
check). Those numbers require the actual weights + a GPU and are produced by
the offline harness — see [`scripts/qwen_t0_gate.py`](../scripts/qwen_t0_gate.py).
Until a pack's `eval_card.json` has real deltas, it is labeled `synthetic` and
must not be presented as a capability-retention result.
