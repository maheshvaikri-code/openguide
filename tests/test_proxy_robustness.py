"""Robustness: the data plane never breaks on control-plane trouble."""
import os

from fastapi.testclient import TestClient

from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.streaming import StreamAssembler
from proxy.upstream import MockUpstream

CONTRACT = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples",
                        "coding-agent-default.toml")


def _build(responder, measures=None):
    reg = ContractRegistry(measures=measures or MeasureRegistry())
    h = reg.load_file(CONTRACT)
    app = create_app(registry=reg, upstream=MockUpstream(responder))
    return TestClient(app), h


def test_malformed_sse_lines_are_ignored():
    a = StreamAssembler()
    a.feed_bytes(b"garbage not sse\n")
    a.feed_bytes(b"data: {not json}\n\n")
    a.feed_bytes(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n')
    assert a.content == "ok"                          # only the valid chunk counted


def test_sensor_exception_becomes_gap_not_500():
    def boom(ctx):
        raise RuntimeError("sensor down")
    meas = MeasureRegistry()
    meas.register(JudgeMeasure("judge:instruction_adherence", boom))
    meas.register(StructuralMeasure("structural:tests_pass_before_commit", lambda c: True))
    client, h = _build(lambda b: "ok", meas)
    r = client.post("/v1/chat/completions",
                    headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "s1"},
                    json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200                       # data plane proceeds
    sess = client.get("/v1/openguide/sessions/s1").json()
    assert sess["trace_verified"] is True
    spans = client.get("/v1/openguide/spans").json()["spans"]
    assert "adherence" in spans[-1]["attributes"].get("gen_ai.behavior.sensor_gaps", [])


def test_empty_choices_does_not_crash():
    client, h = _build(lambda b: {"id": "x", "object": "chat.completion",
                                  "model": "openai:gpt-4o", "choices": []})
    r = client.post("/v1/chat/completions",
                    headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "s2"},
                    json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    assert client.get("/v1/openguide/sessions/s2").json()["trace_verified"] is True


def test_governed_passthrough_returns_upstream_dict_verbatim():
    payload = {"id": "abc", "object": "chat.completion", "model": "openai:gpt-4o",
               "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                            "finish_reason": "stop"}]}
    client, h = _build(lambda b: payload)
    r = client.post("/v1/chat/completions",
                    headers={"X-OpenGuide-Contract": h},
                    json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]})
    body = r.json()
    assert body["id"] == "abc" and body["choices"][0]["message"]["content"] == "hi"
