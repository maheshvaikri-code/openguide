"""Latency benchmark: governance overhead vs pass-through.

Isolates the cost the control plane adds on top of a forward, using a MockUpstream
(instant) so the measured delta is governance only. The Phase 2 gate target is
< 25 ms p50 overhead for non-streaming pass-through.

    python scripts/bench_proxy.py [N]
"""
from __future__ import annotations

import os
import statistics
import sys
import time

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure  # noqa: E402
from proxy.app import create_app  # noqa: E402
from proxy.registry import ContractRegistry  # noqa: E402
from proxy.upstream import MockUpstream  # noqa: E402

CONTRACT = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples",
                        "coding-agent-default.toml")


def _client():
    meas = MeasureRegistry()
    meas.register(JudgeMeasure("judge:instruction_adherence", lambda c: 0.95))
    meas.register(StructuralMeasure("structural:tests_pass_before_commit", lambda c: True))
    meas.register(StructuralMeasure("external:codemonk.cesr", lambda c: 0.9))
    reg = ContractRegistry(measures=meas)
    h = reg.load_file(CONTRACT)
    app = create_app(registry=reg, upstream=MockUpstream(lambda b: "ok"))
    return TestClient(app), h


def _time_calls(client, headers, n):
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        client.post("/v1/chat/completions", headers=headers, json=body)
        samples.append((time.perf_counter() - t0) * 1000.0)   # ms
    return samples


def run_bench(n: int = 100) -> dict:
    client, h = _client()
    warm = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "bench"}
    _time_calls(client, {}, 10)                  # warmup
    _time_calls(client, warm, 10)
    passthrough = _time_calls(client, {}, n)
    governed = _time_calls(client, warm, n)

    def pct(xs, p):
        return statistics.quantiles(xs, n=100)[p - 1]

    return {
        "n": n,
        "passthrough_p50": statistics.median(passthrough),
        "governed_p50": statistics.median(governed),
        "overhead_p50": statistics.median(governed) - statistics.median(passthrough),
        "overhead_p95": pct(governed, 95) - pct(passthrough, 95),
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    r = run_bench(n)
    print(f"n={r['n']}")
    print(f"  pass-through p50 : {r['passthrough_p50']:.3f} ms")
    print(f"  governed     p50 : {r['governed_p50']:.3f} ms")
    print(f"  overhead     p50 : {r['overhead_p50']:.3f} ms   (gate: < 25 ms)")
    print(f"  overhead     p95 : {r['overhead_p95']:.3f} ms")
