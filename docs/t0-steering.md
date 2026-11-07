# T0 activation steering in the proxy

**What it is.** A way to correct a model by nudging its *internal activations* while it writes, instead of only
reminding it in text. OpenGuide's proxy can do this for a model it runs itself, and only after the model has
slipped.

**Why.** A text reminder (T2) is something the model can ignore: on the local Qwen2.5-1.5B model the proxy's
re-anchoring alone gave essentially no benefit (`benchmarks/REPORT.md` 7.1). Steering acts below the prompt, so it
does not depend on the model choosing to obey. It is also dangerous in excess: measured gains of 0.2 and above
destroy the output, and steering that is always on broke a conversation that was fine. So it is **gated on
drift** and **capped at gain 0.05**, the only gain measured not to damage the model's reasoning (at 0.1, GSM8K fell from 66% to 24%).

**Where it applies.**

- Only to a model whose weights are loaded in the proxy's own process (`proxy/hf_upstream.py`, `HFUpstream`).
  Hosted APIs (OpenAI, Anthropic, ...) expose no activations and cannot be steered; they stay on T2/T3.
- Only to governed requests (those with `X-OpenGuide-Contract`), and only for sessions that have just needed a correction.
- Only when you configure it. By default nothing is steered.

**What happens.** Turn N is scored. If the recovery ladder fired (`re_anchor`, `escalate` or `halt`), turn N+1 is
generated with the steering vector added at the configured gain, *in addition to* the T2 reminder. If turn N+1 is
clean, turn N+2 is not steered. Each steered turn adds a `STEER` record (gain, layers, pack hash) to the
hash-chained trace, and the Console's turn panel says "Activation steering was on for this turn".

## Using it

```bash
python scripts/derive_steering_pack.py     # once per model: writes .models/steering/<model>.safetensors
```

```python
from guidancegrid.core.grid import SignalPack
from proxy.app import create_app
from proxy.hf_upstream import HFUpstream
from proxy.steering import SteeringConfig

up = HFUpstream.from_pretrained(".models/Qwen2.5-1.5B-Instruct")
pack = SignalPack.load_safetensors(".models/steering/qwen2.5-1.5b-instruct.safetensors")
cfg = SteeringConfig(pack, band=(10, 19), gain=0.05)      # layers 10..18; gain must be in (0, 0.1]
up.enable_steering(cfg)                                   # checks the pack against this model now
app = create_app(upstream=up, steering=cfg)               # register contracts as usual (POST /v1/openguide/contracts)
```

There is no command-line or environment switch yet; it is configured in Python as above.

`create_app(..., steering=cfg)` raises if the upstream cannot steer, so a trace never claims steering that did not
happen. A client cannot switch steering on or change the gain: the gain travels from the Governor to the model
as a typed argument, never from a header or body.

## Optional cap on consecutive steered turns

`SteeringConfig(..., max_consecutive=2, pause_turns=3)` limits steering to 2 turns in a row, then pauses it for 3
turns (the text re-anchor still runs). It is **off by default and not recommended.** It was tested on 60 fresh
conversations under a pre-registered plan ([docs/preregistration/t0-cap-study.md](preregistration/t0-cap-study.md)) and
**did not pass**: it kept the benefit (+0.23) but did not reduce losses (5, against 3 uncapped) and was slightly worse than
no cap (-0.03, CI [-0.08, +0.01]). Pausing steering let some conversations that steering had been holding relapse.

## Limits (read before relying on it)

- `gain` is the peak of a gaussian envelope across the layer band: the middle layers get about that much and the
  edge layers less. A pack must be on the model's own scale (the derive script makes it so); `enable_steering`
  refuses one that is not, and `SteeringConfig(..., expected_pack_hash=...)` pins the pack you reviewed.
- A pack belongs to one model and one rule set. It was derived and tested only on Qwen2.5-1.5B-Instruct with the
  support-assistant rules (brevity, plain text, `[END]`).
- It reacts one turn late: it acts on the turn after the drift was seen, so it cannot prevent the first failure.
- Measured, not assumed. A pre-registered replication on 60 new conversations (`benchmarks/REPORT.md` 7.4) raised
  recovery from 68.5% to 90.8% (paired +0.22, 95% CI [+0.14, +0.31]), mostly in conversations that drift, and GSM8K
  dropped 1.7 points with steering always on (CI [-4.7, +7.7]). A second set (7.5) gave +0.26. A third, pre-registered
  study on a **new pool of prompts** (7.6) gave +0.40 (CI [+0.31, +0.49], 48 wins / 11 ties / 1 loss) and, on all 1,319 GSM8K
  problems with steering always on, a drop of 0.5 points with the interval's upper end at 3.3 ("no harm shown" under the
  stricter rule). The new prompts are in the same style and written by the same system; no other model or rule set was tested.
- **Conversations where the gate keeps firing do worse** (7 of 60 ran 8 or more steered turns; mean paired difference
  -0.04), and in one the steered replies dropped the brackets of `[END]` so the gate never switched off (1.00 -> 0.00).
  These are the conversations where the model keeps breaking the rules, so this is not shown to be caused by steering. A
  second 60-conversation set had no such catastrophe (worst -0.20), and its uncapped arm gained +0.26 again.
- The rule checker can pass broken output, so look at the replies as well as the scores.

See [ADR-003](adr/003-drift-gated-t0-in-the-proxy.md) for the decision and the alternatives rejected.
