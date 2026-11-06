# Trace format (v0.1)

The flight recorder. A hash-chained, replayable record of every control event
in a run. The differentiator: **per-step, tamper-evident, replay-identical.**

> Invariant (enforced by construction in the runtime): run state mutates only
> via the control channel, and the control channel's only side effect is
> appending a record here. There is no side door.

## 1. Canonical encoding

Every hashable artifact — contracts, fields, packs, trace records — passes
through one canonical JSON encoding so a hash is stable across platforms, dict
orderings, and float-repr quirks.

Rules:

1. **Atoms** — `null`, booleans, integers, and strings encode as-is.
2. **Floats** — rounded to **9 significant digits** (`%.9g`), then parsed back
   to a number. Stable across float32 round-trips.
3. **Objects** — keys coerced to strings and **sorted** lexicographically by
   the string key.
4. **Arrays** — preserved in order; elements encoded recursively.
5. **Serialization** — `json.dumps` with `sort_keys=True`,
   `separators=(",", ":")` (no insignificant whitespace), `ensure_ascii=True`
   (UTF-8 escaped to ASCII).
6. Non-encodable types (sets, bytes, objects) are an error — callers reduce to
   atoms/objects/arrays first.

```
canonical(obj) -> str        # the rules above
chash(obj)     = "sha256:" + sha256(utf8(canonical(obj))).hexdigest()
bhash(bytes)   = "sha256:" + sha256(bytes).hexdigest()
```

The reference implementation is
[`guidancegrid/core/canonical.py`](../../guidancegrid/core/canonical.py);
golden vectors are in [`../conformance/vectors/canonical/`](../conformance/vectors/canonical/).
A conforming implementation in any language must reproduce every golden hash.

## 2. Chain construction

A trace is a manifest plus an append-only list of records. The chain:

```
genesis = chash(manifest)
head_0  = genesis
record_i is stored as  { "prev": head_{i-1}, **event_i }
head_i  = chash(record_i)
```

So each stored record embeds the prior head in its `prev` field, and the
running `head` is the hash of the most recent stored record. The **manifest**
is the run's identity tuple:

```json
{
  "model": "<model id>",
  "spec_hash": "sha256:...",
  "spec": { ...the OBC / spec object... },
  "pack_hash": "sha256:...",
  "seed": 7,
  "runtime": "ggrid-ref-0.1.0"
}
```

### Record types

| `ev` | Meaning | Key fields |
|------|---------|-----------|
| `STEP` | one per-step grid evaluation | `step`, `applied`, `sigma_peak`, `norm_corr` |
| `OVERRIDE` | live gain knob change | `step`, `signal`, `old`, `new`, `source` |
| `TRIGGER` | event-driven signal application | `step`, `on`, `signal`, `g`, `tau`, `layers`, `source` |
| `STATE` | one behavioral-state reading per governed turn | `turn`, `drift`, `invariants`, `recovery_fired`, `reanchored`, `sensor_gaps` |
| `TOOL_POLICY` | a tool-call decision | `turn`, `decision`, `reason`, `tools` |
| `TURN` | **optional** message text for one turn | `turn`, `user`, `output`, `restated`, `truncated` |
| `STEER` | activation steering (T0) was applied to a turn's generation; only steered turns have one | `turn`, `gain`, `band` (`[lo, hi)` decoder layers), `pack_hash` |

**`STEER` exists only when the proxy runs with a steering pack** (ADR-003). A turn gets one when its generation
was steered at the model's activations: it follows that turn's `STATE`, carries the `gain` (the peak of a gaussian envelope across the band, so edge
layers get less), the `band` of layers and the hash of the pack. A turn is steered only after a turn whose recovery action fired, so a clean run has
no `STEER` records. It rides in the same hash chain, so what was steered is as tamper-evident as what was measured.
The proxy writes one only when the upstream reports that a steered reply was actually produced.
One exception, marked `"scored": false`: a reply was produced but its turn was never scored (the client closed the
stream, or scoring failed). That record has no `STATE` of its own and precedes the `STATE` of the turn that is
retried, so a turn number can then appear in two `STEER` records. A client that cancels while the model is still
writing receives no reply, so nothing is recorded for it.

**`TURN` is opt-in and off by default.** A trace holds behavioral state only unless the proxy runs with
`OPENGUIDE_CAPTURE_CONTENT=1`, because captured text is the prompts and replies themselves. When on, a `TURN`
record follows each turn's `STATE` and carries: `user`, the newest user message only (never the system prompt or
earlier history); `output`, the model's reply; `restated`, the re-anchor text sent with that request, or `null`;
and `truncated`, true if any field was clipped to 8000 characters. It is inside the hash chain like every other
record, so captured text is tamper-evident. The metadata-only view of a trace (`?metadata_only=true`) never
includes it. See `docs/adr/002-opt-in-content-capture.md`.

Records are extensible: unknown `ev` values and extra fields are permitted and
participate in the hash (canonical encoding sorts them deterministically).

## 3. Verification procedure

```
head := genesis
for record in records:
    if record["prev"] != head: return INVALID
    head := chash(record)
return head == stored_head
```

Editing, reordering, inserting, or deleting any record breaks the chain:
the recomputed `head` will not match the stored `head`. See chain golden
vectors (valid + tampered) in
[`../conformance/vectors/chain/`](../conformance/vectors/chain/).

## 4. Replay identity

Same manifest + same recorded events ⇒ **bit-identical head hash.** Because the
manifest pins `spec_hash`, `pack_hash`, `seed`, and `runtime`, a replay that
re-derives the same events reproduces the same chain head exactly. This is the
replay key the Console's scrub/replay relies on, and the property a CI test
asserts on every change (blueprint §7.1).

## 5. Persistence

The on-disk form is a single JSON object:

```json
{ "manifest": {...}, "head": "sha256:...", "records": [ {...}, ... ] }
```

`to_json` / `from_json` round-trip it. `canonical()` returns
`canonical({manifest, records})` for cross-store content addressing (the `head`
is derivable, so it is excluded from the canonical body).

## 6. Storage sizing

A record is ≈ 50–200 bytes/turn/signal. 10M runs × 100 turns ≈ low-GB range in
object storage — storage is never the cost driver; judge-sensor API calls are.
Make judge sampling a contract-level knob.
