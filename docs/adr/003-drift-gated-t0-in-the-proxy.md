# ADR-003: Drift-gated T0 activation steering in the proxy

**Status:** accepted (2026-11-06) · **Deciders:** project owner (asked for T0 to be wired in), Chief Architect

## Context
GuidanceGrid has two enforcement channels that change what the model does: T2 (re-state the rules in text)
and T0 (add a steering vector to the model's activations). The proxy only ever used T2. T0 existed in the
experiments (`benchmarks/real_t0.py`) and nowhere in the product.

What we measured on the real model (Qwen2.5-1.5B-Instruct, `benchmarks/REPORT.md` §7.2):
- gain 0.05 helps and showed no detectable capability loss (GSM8K 66% -> 60%, p = 0.46, n = 100); 0.1 collapses
  multi-step reasoning (GSM8K 24%) and broke a healthy conversation;
- gain >= 0.2 produces degenerate output;
- steering that is **always on** at 0.1 broke a conversation that was fine (88% -> 0%).

## Decision
Wire T0 into the proxy as a **drift-gated closed loop**, opt-in:
1. After a turn whose recovery action fired (`re_anchor`, `escalate` or `halt`; the same trigger that prepares a
   T2 re-anchor), the **next** generation of that session is steered at the configured gain.
2. When a turn is clean, the following generation is not steered. The decision is re-made every turn.
3. The T2 re-anchor is still sent; T0 adds to it, it does not replace it.
4. **Steering fails closed.** There is no default gain and no default ceiling. Steering is allowed only on weights that have
   a validation record (`proxy/validation.py`): the weights' identity (SHA-256 of the weight files), the band, the steering
   pack, a gain ceiling and the evidence (results files with their commits). The only record is Qwen2.5-1.5B-Instruct: band
   10-18, ceiling 0.05, the three pre-registered studies. `HFUpstream.enable_steering` checks the loaded model against the
   records and refuses anything else, naming the missing evidence. (An earlier draft capped the gain at 0.1 for all models and
   called that usable; the capability table shows it is not, and a second model showed no gain is general.)
5. Every steered turn appends a `STEER` record (turn, peak gain, layer band, pack hash) to the hash-chained trace,
   so what was steered is as auditable as what was measured. The record is written only when the upstream reports (through a `SteerReceipt`) that a steered reply was
   produced. A reply that was produced but never scored (the client closed the stream) is recorded marked
   `"scored": false`; a client that cancels while the model is still writing gets no reply, so nothing is recorded.
6. It only works with an upstream that owns the weights (`HFUpstream`). Governor construction fails if
   steering is requested for an upstream that cannot steer, so a trace never claims steering that did not happen.
7. The gain reaches the upstream through a typed argument (`steer=`) that only the Governor sets. It is never
   read from a request header or body, so a client cannot turn steering on or raise it.

## Hardening from the security review
- The gain bounds the push only if the pack's vectors are on the model's own scale (injection is renormalised to
  the hidden state's norm, so a huge vector would replace the state whatever the gain). `enable_steering` therefore
  refuses a pack whose norm at any band layer exceeds 4x the model's measured residual norm there, and the config
  refuses non-finite or mis-shaped vectors. An operator can pin the reviewed pack with `expected_pack_hash`.
- Only the band's layers are steered (the pack is cut to the band), `gain` is documented as the peak of the
  envelope, and `max_new_tokens` is refused if it exceeds what the gain field covers.
- Accepted, not fixed: the session id is client-chosen and unauthenticated (pre-existing), so a client that knows a
  session id can make that session's next generation steered; the effect is one generation, at most gain 0.1, in
  that session only. A client can also register a contract that always triggers recovery, if no admin token is set,
  and so steer its own requests.

## Consequences
- Two simultaneous requests on one session both read the same steering state (the same pattern as the pending
  re-anchor). The `STEER` record still states exactly what each applied.
- There is no command-line or environment switch yet: steering is configured in Python (`docs/t0-steering.md`).
- Steering reacts one turn late (it acts on the turn after the drift was seen). That is inherent in a
  reconciler that measures replies.
- A steering pack is specific to one model. It must be derived for that model (`scripts/derive_steering_pack.py`)
  and is checked against the model's hidden size and the layer band at start-up.
- Validated only on Qwen2.5-1.5B-Instruct and on this rule set. Three pre-registered studies (60 conversations
  each, `benchmarks/REPORT.md` §7.4-7.6) support it: recovery +0.22, +0.26 and, on a new prompt pool, +0.40; GSM8K drop 1.7
  points (n = 300) and 0.5 points on all 1,319 problems with the upper end of the interval at 3.3.
- **Known weakness:** when the gate keeps firing, steering stays on and those conversations do worse (7 of 60 in the
  replication ran 8+ steered turns; mean paired difference -0.04; one fell 1.00 -> 0.00 because the steered replies dropped
  the brackets of `[END]`). That is not shown to be caused by steering (they are the conversations where the model keeps
  failing). A cap on consecutive steered turns exists as an opt-in setting (`max_consecutive`, `pause_turns`; off by
  default). A pre-registered study on fresh seeds (`docs/preregistration/t0-cap-study.md`, REPORT 7.5) found it did **not**
  help (5 losses against 3 uncapped; capped - uncapped -0.03, CI lower bound -0.08). Steering stays uncapped by default.
- **The gain ceiling is per model, and now enforced as such.** A pilot on Granite-3.1-2B (REPORT 7.7) found no eligible gain:
  even the lowest relative gain, 0.025, cost 6.3 GSM8K points. So the Qwen ceiling of 0.05 is no longer an implicit default:
  an unvalidated model is refused. To experiment, a `SteeringConfig` must say `experimental=True` and give an explicit
  `gain_ceiling`; that can only be done in code (no server or environment setting reaches it), and every steered turn under
  it carries `"experimental": true` in its `STEER` record and is labelled in the Console. A model gains a record only with
  its own pre-registered evidence.
- Hosted APIs (OpenAI, Anthropic, ...) cannot be steered this way; they stay T2/T3.

## Alternatives rejected
- *Always-on steering:* measured to hurt a healthy conversation.
- *Gain taken from a request header:* spoofable by any client.
- *A `ContextVar` carrying the gain:* resetting it across the yields of a streaming generator is fragile.
- *Putting the pack derivation in the proxy:* it needs prompts and a baseline that belong to the experiment, not to a
  server; derive offline, load a file.
