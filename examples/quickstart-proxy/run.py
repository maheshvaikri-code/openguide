"""Smallest end-to-end OpenGuide loop, in-process (no Docker, no network).

A mock model whose instruction adherence collapses mid-conversation; the proxy
governs it, re-anchors when drift crosses the contract's threshold, and records
a verifiable hash-chained trace.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient  # noqa: E402

from guidancegrid.sensors import (  # noqa: E402
    ExternalMeasure,
    JudgeMeasure,
    MeasureRegistry,
    StructuralMeasure,
)
from guidancegrid.store import Store  # noqa: E402
from proxy.app import create_app  # noqa: E402
from proxy.registry import ContractRegistry  # noqa: E402
from proxy.upstream import MockUpstream  # noqa: E402

CONTRACT = os.path.join(os.path.dirname(__file__), "..", "..", "spec", "obc",
                        "examples", "coding-agent-default.toml")

# adherence per turn: stable, then a sharp decay, then re-anchored recovery
ADHERENCE = [0.95, 0.93, 0.55, 0.58, 0.95, 0.94]


def build():
    seq = {"i": 0}
    meas = MeasureRegistry()

    def adherence(ctx):
        v = ADHERENCE[min(seq["i"], len(ADHERENCE) - 1)]
        seq["i"] += 1
        return v

    meas.register(JudgeMeasure("judge:instruction_adherence", adherence))
    meas.register(StructuralMeasure("structural:tests_pass_before_commit", lambda c: True))
    meas.register(ExternalMeasure("external:codemonk.cesr", lambda c: 0.9))
    reg = ContractRegistry(measures=meas)
    h = reg.load_file(CONTRACT)
    app = create_app(registry=reg, upstream=MockUpstream(lambda b: "patch applied"), store=Store())
    return TestClient(app), h


def demo() -> dict:
    client, contract = build()
    hdrs = {"X-OpenGuide-Contract": contract, "X-OpenGuide-Session": "quickstart"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "refactor"}]}

    rows = []
    for turn in range(len(ADHERENCE)):
        r = client.post("/v1/chat/completions", headers=hdrs, json=body)
        drift = float(r.headers["x-openguide-drift"])
        recovery = r.headers.get("x-openguide-recovery", "-")
        rows.append((turn, drift, recovery))

    sess = client.get("/v1/openguide/sessions/quickstart").json()
    return {"rows": rows, "session": sess}


def main() -> None:
    out = demo()
    print(f"{'turn':>4}  {'drift':>6}  recovery")
    for turn, drift, recovery in out["rows"]:
        print(f"{turn:>4}  {drift:>6.3f}  {recovery}")
    s = out["session"]
    print(f"\nturns={s['turns']}  max_drift={s['max_drift']}  "
          f"recoveries={s['recoveries']}  trace_verified={s['trace_verified']}")
    print(f"tier={s['tier']}  trace_head={s['trace_head'][:23]}…")


if __name__ == "__main__":
    main()
