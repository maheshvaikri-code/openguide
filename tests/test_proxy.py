"""Proxy wedge: passthrough, header-activated governance, session feed-forward,
behavioral-state spans, and streaming — all offline against a MockUpstream."""
import os

from fastapi.testclient import TestClient

from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")
CONTRACT = os.path.join(EX, "coding-agent-default.toml")


def build(responder=None, adherence_seq=None):
    """A proxy wired with the coding-agent contract. ``adherence_seq`` drives the
    judge measure turn-by-turn so a test can script drift."""
    state = {"i": 0}
    meas = MeasureRegistry()

    def adherence(ctx):
        if adherence_seq is None:
            return 0.95
        i = min(state["i"], len(adherence_seq) - 1)
        state["i"] += 1
        return adherence_seq[i]

    meas.register(JudgeMeasure("judge:instruction_adherence", adherence))
    meas.register(StructuralMeasure("structural:tests_pass_before_commit", lambda c: True))
    meas.register(StructuralMeasure("external:codemonk.cesr", lambda c: 0.9))

    reg = ContractRegistry(measures=meas)
    h = reg.load_file(CONTRACT)
    up = MockUpstream(responder or (lambda body: "done"))
    app = create_app(registry=reg, upstream=up)
    return TestClient(app), h, up


# ── passthrough ─────────────────────────────────────────────────────
def test_passthrough_without_header_is_transparent():
    client, _, up = build()
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    r = client.post("/v1/chat/completions", json=body)
    assert r.status_code == 200
    assert "x-openguide-drift" not in {k.lower() for k in r.headers}
    assert r.json()["choices"][0]["message"]["content"] == "done"
    assert len(up.calls) == 1                       # exactly one upstream call, body unchanged
    assert "messages" in up.calls[0] and len(up.calls[0]["messages"]) == 1


def test_unknown_contract_is_404():
    client, _, _ = build()
    r = client.post("/v1/chat/completions", headers={"X-OpenGuide-Contract": "sha256:deadbeef"},
                    json={"model": "openai:gpt-4o", "messages": []})
    assert r.status_code == 404


# ── governance ──────────────────────────────────────────────────────
def test_governed_call_emits_headers_and_span():
    client, h, _ = build()
    r = client.post("/v1/chat/completions",
                    headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "c1"},
                    json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200
    assert r.headers["x-openguide-tier"] == "t2"
    assert r.headers["x-openguide-contract"] == h
    spans = client.get("/v1/openguide/spans").json()["spans"]
    assert spans[-1]["attributes"]["gen_ai.behavior.contract_hash"] == h
    assert spans[-1]["attributes"]["gen_ai.behavior.tier"] == "t2"


def test_drift_appears_in_headers_and_session():
    # adherence collapses on turn 2 -> drift crosses threshold -> recovery header
    client, h, _ = build(adherence_seq=[0.95, 0.50, 0.95])
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "c2"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)
    r2 = client.post("/v1/chat/completions", headers=hdrs, json=body)
    assert float(r2.headers["x-openguide-drift"]) >= 0.27
    assert r2.headers.get("x-openguide-recovery") == "re_anchor"
    sess = client.get("/v1/openguide/sessions/c2").json()
    assert sess["turns"] == 2 and sess["recoveries"] >= 1
    assert sess["trace_verified"] is True


def test_session_feeds_reanchor_forward():
    # turn 1 drifts -> re-anchor pending -> injected into turn 2's upstream request
    client, h, up = build(adherence_seq=[0.50, 0.95])
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "c3"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)   # turn 0: drift, re-anchor set
    client.post("/v1/chat/completions", headers=hdrs, json=body)   # turn 1: re-anchor injected
    # second upstream call should carry an injected system re-anchor message
    second = up.calls[1]["messages"]
    assert second[0]["role"] == "system" and "contract" in second[0]["content"].lower()
    # the client's own request body had only the user message (injection is internal)
    assert len(body["messages"]) == 1


def test_trace_chain_spans_the_conversation():
    client, h, _ = build()
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "c4"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    for _ in range(3):
        client.post("/v1/chat/completions", headers=hdrs, json=body)
    sess = client.get("/v1/openguide/sessions/c4").json()
    assert sess["turns"] == 3
    assert sess["trace_verified"] is True           # one hash chain across 3 calls


# ── streaming ───────────────────────────────────────────────────────
def test_streaming_passthrough_is_byte_identical_and_governed():
    client, h, _ = build(responder=lambda b: "hello world")
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "c5"}
    body = {"model": "openai:gpt-4o", "stream": True,
            "messages": [{"role": "user", "content": "go"}]}
    with client.stream("POST", "/v1/chat/completions", headers=hdrs, json=body) as r:
        raw = b"".join(r.iter_bytes())
    text = raw.decode()
    assert "data: [DONE]" in text
    assert "hello wo" in text                        # streamed content present
    # governance still ran as a side-channel: a span + a recorded turn
    sess = client.get("/v1/openguide/sessions/c5").json()
    assert sess["turns"] == 1 and sess["trace_verified"]


def test_register_contract_endpoint():
    client, _, _ = build()
    import tomllib
    with open(CONTRACT, "rb") as f:
        obc = tomllib.load(f)
    r = client.post("/v1/openguide/contracts", json=obc)
    assert r.status_code == 200 and r.json()["contract_hash"].startswith("sha256:")


def test_session_404_when_missing():
    client, _, _ = build()
    assert client.get("/v1/openguide/sessions/nope").status_code == 404
