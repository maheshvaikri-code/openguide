# OBC — Open Behavioral Contract (v0.1)

The contract file format. The procurement word: *"must support OBC v1."*

An OBC declares **what an agent's behavior must be** — invariants, phases,
triggers, recovery — independent of which model runs it. The runtime compiles
one contract to the strongest enforcement channel each model allows:

| Tier | Channel | Where |
|------|---------|-------|
| `t0` | Activation steering (residual-stream injection) | open weights (HF transformers, vLLM) |
| `t1` | Constrained decoding (grammar / logit mask) | local models |
| `t2` | Scheduled re-anchoring (contract fragments at frame boundaries) | closed APIs |
| `t3` | Structural validation (schema / regex / custom fn) | universal |

`enforcement_floor` is the minimum tier the runtime must achieve, or it
refuses to run.

## Structure

```toml
[contract]            # name, version, enforcement_floor
[identity]            # persona, boundaries
[[invariants]]        # measurable constraints (judge:/probe:/structural:/external:)
[[phases]]            # turn windows with active signals
[[triggers]]          # event -> signal application
[recovery]            # drift_threshold + escalation ladder
[signals]             # tier-binding: pack hash, t2 template, t1 grammar
```

A measure reference is typed by its prefix:

- `judge:<name>` — an LLM-as-judge reading (declared `determinism: stochastic`)
- `probe:<name>` — a linear probe on the residual stream (open weights only)
- `structural:<name>` — a deterministic check (schema, regex, file-scope)
- `external:<name>` — a webhook or registered Python callable

Every invariant needs **either** a `floor` (soft, contributes to drift) **or**
`hard = true` (enforced, never advisory). `weight` scales an invariant's
contribution to the drift scalar.

## Identity & hashing

A contract is content-addressed with the canonical encoding the trace plane
uses (see [`../trace/`](../trace/)):

```
contract_hash = sha256(canonical(contract))
```

sorted keys · 9-significant-digit floats · UTF-8 · no insignificant whitespace.
The same contract hashes identically across languages and TOML libraries. This
hash is the deployment identity — `X-OpenGuide-Contract: <hash>` activates
governance at the proxy.

## Examples

- [`coding-agent-default.toml`](examples/coding-agent-default.toml) — scope
  discipline + tests-before-commit + CESR setpoint
- [`support-tenant.toml`](examples/support-tenant.toml) — per-tenant
  temperament, composed `tenant + task`
- [`browsing-injection.toml`](examples/browsing-injection.toml) — prompt-
  injection detection via user-vs-context adherence divergence

Validate and hash an example:

```python
from guidancegrid.obc import load_contract, validate_contract, contract_hash
c = validate_contract(load_contract("examples/coding-agent-default.toml"))
print(contract_hash(c))
```

## Scope honesty

OBC biases trajectories; it does not *guarantee* behavior. `hard` invariants on
tier 1/3 are the only mechanically-enforced constraints — soft floors are
reconciled statistically. See the root README for the full prior-art positioning.
