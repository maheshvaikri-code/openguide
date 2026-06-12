# Behavioral State → OpenTelemetry mapping

Every governed turn emits one OTel span carrying the behavioral state as
`gen_ai.behavior.*` attributes. This is the first-mover schema OpenGuide will
propose to the OTel GenAI SIG; it composes with the existing `gen_ai.*`
semantic conventions rather than replacing them.

Span name: `gen_ai.behavior.turn` · Span kind: `INTERNAL` (child of the model
call span when one exists).

| Behavioral State field | OTel attribute | Type | Notes |
|------------------------|----------------|------|-------|
| `turn` | `gen_ai.behavior.turn` | int | zero-based |
| `tier_active` | `gen_ai.behavior.tier` | string | `t0`..`t3` |
| `drift` | `gen_ai.behavior.drift` | double | [0,1] |
| `invariants.<id>.reading` | `gen_ai.behavior.invariant.<id>` | double | one attr per invariant |
| `invariants.<id>.violated` | `gen_ai.behavior.invariant.<id>.violated` | bool | |
| `recovery_fired` | `gen_ai.behavior.recovery` | string | absent when null |
| `sigma_peak` | `gen_ai.behavior.sigma_peak` | double | tier 0 only |
| `norm_correction` | `gen_ai.behavior.norm_correction` | double | tier 0 only |
| `sensor_gaps` | `gen_ai.behavior.sensor_gaps` | string[] | invariant ids |
| `hash` | `gen_ai.behavior.record_hash` | string | trace chain head after this turn |
| contract identity | `gen_ai.behavior.contract_hash` | string | resource/span-level, stable per run |

## Resource attributes (per run)

| Field | Attribute |
|-------|-----------|
| contract hash | `gen_ai.behavior.contract_hash` |
| pack hash | `gen_ai.behavior.pack_hash` |
| runtime build | `gen_ai.behavior.runtime` |
| model id | `gen_ai.request.model` (reuse existing convention) |

## Event semantics

- A `recovery` attribute present on a span marks a reconciliation event; a span
  event `gen_ai.behavior.recovery` may additionally carry `{from_drift, action,
  to_drift}` for the Trajectory view.
- Drift is monotone-comparable across turns within a run; it is **not**
  comparable across contracts (different invariant weightings). Dashboards must
  scope drift comparisons to a single `contract_hash`.

## Why a span per turn, not a metric

Drift is a per-trajectory time series with causal structure (a trigger at turn
N explains a snap-back at N+1). Metrics aggregate that structure away. The span
stream preserves it and links back to the hash-chained trace for replay — see
[`../trace/`](../trace/).
