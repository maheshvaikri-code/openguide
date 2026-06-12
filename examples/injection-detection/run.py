"""Case study 3: prompt-injection detection (SIMULATED).

A browsing agent runs two probes each turn: adherence-to-user and
adherence-to-context. Normally both track together. When a fetched page carries
an injected instruction, the agent starts obeying the *context* over the *user*
— context-obedience spikes while user-adherence drops. That divergence is the
detection signal, and it fires *before* the agent acts. This is the novel
channel: an injection is visible as a behavioral-state shape, not a string match.

The browsing-injection contract's trigger
(`state:context_obedience>0.40`) re-anchors the agent to the user goal.

Reference scenario — simulated until a design partner replaces it.

    python examples/injection-detection/run.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from guidancegrid.compiler import compile_contract  # noqa: E402
from guidancegrid.controller import Reconciler  # noqa: E402
from guidancegrid.obc import load_contract  # noqa: E402
from guidancegrid.sensors import MeasureRegistry  # noqa: E402
from guidancegrid.sensors.base import Measure  # noqa: E402

CONTRACT = os.path.join(os.path.dirname(__file__), "..", "..", "spec", "obc",
                        "examples", "browsing-injection.toml")
T = 24
INJECT_AT = 10            # a poisoned page is fetched at turn 10


class ScriptedProbe(Measure):
    """Stands in for a residual-stream probe by returning a scripted score —
    so the case study runs offline without a real model."""

    def __init__(self, measure_id, fn):
        super().__init__(measure_id)
        self._fn = fn

    def _read(self, ctx):
        return self._fn(ctx)


def _scenario():
    """Deterministic user/context adherence traces. Before the injection both
    are healthy; at turn 10 a poisoned page flips context-obedience up and pulls
    user-adherence down for a few turns until the re-anchor recovers it."""
    user = []
    context = []
    u, c = 0.9, 0.1
    for t in range(T):
        if t == INJECT_AT:
            u, c = 0.55, 0.65        # injection: obey context over user
        elif t > INJECT_AT:
            u = min(0.9, u + 0.12)   # re-anchor pulls back to the user goal
            c = max(0.1, c - 0.12)
        user.append(round(u, 4))
        context.append(round(c, 4))
    return user, context


def run_case() -> dict:
    cc = compile_contract(load_contract(CONTRACT), "mock:browser")
    reg = MeasureRegistry()
    # probes read from ctx["residual"]; here we feed synthetic scores directly
    user_seq, ctx_seq = _scenario()
    state = {"t": 0}

    def user_probe(ctx):
        return user_seq[state["t"]]

    def ctx_probe(ctx):
        return ctx_seq[state["t"]]

    reg.register(ScriptedProbe("probe:adherence_to_user", user_probe))
    reg.register(ScriptedProbe("probe:adherence_to_context", ctx_probe))
    reg.register(ScriptedProbe("structural:no_action_without_confirm", lambda c: 1.0))

    manifest = {"model": "mock:browser", "contract_hash": cc.contract_hash, "runtime": "ggrid-inj-0.1"}
    rc = Reconciler(cc, reg, manifest)

    detections = []
    for t in range(T):
        state["t"] = t
        out = rc.step(t, {"turn": t})
        # the contract's trigger fires on context_obedience>0.40
        ctx_reading = out.state["invariants"]["context_obedience"]["reading"]
        if ctx_reading is not None and ctx_reading > 0.40:
            detections.append(t)
    return {"user": user_seq, "context": ctx_seq, "detections": detections,
            "trace_verified": rc.trace.verify(), "first_detection": detections[0] if detections else None}


def main() -> None:
    res = run_case()
    print("prompt-injection detection - SIMULATED (user-vs-context adherence divergence)\n")
    print(f"  poisoned page fetched at turn {INJECT_AT}\n")
    print(f"{'turn':>4}  {'user':>5}  {'context':>7}  signal")
    for t in range(T):
        u, c = res["user"][t], res["context"][t]
        flag = "  <-- INJECTION (context > user)" if c > 0.40 else ""
        print(f"{t:>4}  {u:>5.2f}  {c:>7.2f}{flag}")
    print(f"\n  first detection at turn {res['first_detection']} "
          f"(same turn the page was fetched, before acting)")
    print(f"  trace verified: {res['trace_verified']}")


if __name__ == "__main__":
    main()
