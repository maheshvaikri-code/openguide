"""Store wired into the proxy: fleet index populated, trace persisted."""
import os

from fastapi.testclient import TestClient

from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure
from guidancegrid.store import Store
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream

CONTRACT = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples",
                        "coding-agent-default.toml")


def build(adherence_seq=None):
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
    store = Store()
    app = create_app(registry=reg, upstream=MockUpstream(lambda b: "ok"), store=store)
    return TestClient(app), h, store


def test_runs_populate_fleet_index():
    client, h, store = build(adherence_seq=[0.95, 0.50, 0.95])
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "run-a"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    for _ in range(3):
        client.post("/v1/chat/completions", headers=hdrs, json=body)

    # fleet query API over HTTP
    runs = client.get("/v1/openguide/runs", params={"contract": h}).json()["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-a" and runs[0]["turns"] == 3
    assert runs[0]["verified"] is True
    assert runs[0]["trace_cas_key"].startswith("sha256:")
    assert store.get_trace(runs[0]["trace_cas_key"]) is not None

    # high-drift filter
    hi = client.get("/v1/openguide/runs", params={"min_drift": 0.27}).json()["runs"]
    assert [r["run_id"] for r in hi] == ["run-a"]


def test_run_trace_endpoint_persists_and_verifies():
    client, h, store = build()
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "run-b"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)

    tr = client.get("/v1/openguide/runs/run-b/trace").json()
    assert tr["verified"] is True
    assert tr["cas_key"].startswith("sha256:")
    # the persisted blob reloads and re-verifies from the store
    reloaded = store.get_trace(tr["cas_key"])
    assert reloaded is not None and reloaded.verify()
    assert reloaded.head == tr["head"]


def test_run_trace_endpoint_metadata_only_omits_records():
    client, h, _ = build()
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "run-meta"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)

    tr = client.get("/v1/openguide/runs/run-meta/trace", params={"metadata_only": "true"}).json()
    assert tr["verified"] is True
    assert tr["metadata_only"] is True
    assert tr["record_count"] == 1
    assert tr["event_counts"] == {"STATE": 1}
    assert "records" not in tr


def test_run_trace_endpoint_loads_persisted_trace_after_session_drop():
    client, h, store = build()
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "run-c"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)
    client.app.state.governor.sessions.drop("run-c")

    tr = client.get("/v1/openguide/runs/run-c/trace").json()
    assert tr["verified"] is True
    assert tr["cas_key"] == store.get_run("run-c").trace_cas_key
    assert tr["records"][0]["ev"] == "STATE"


def test_run_trace_endpoint_metadata_only_after_session_drop():
    client, h, _ = build()
    hdrs = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "run-meta-cas"}
    body = {"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "go"}]}
    client.post("/v1/chat/completions", headers=hdrs, json=body)
    client.app.state.governor.sessions.drop("run-meta-cas")

    tr = client.get(
        "/v1/openguide/runs/run-meta-cas/trace",
        params={"metadata_only": "true"},
    ).json()
    assert tr["verified"] is True
    assert tr["record_count"] == 1
    assert "records" not in tr


def test_runs_endpoint_501_without_store():
    # an app with no store returns 501 for fleet queries
    reg = ContractRegistry()
    app = create_app(registry=reg, upstream=MockUpstream())
    client = TestClient(app)
    assert client.get("/v1/openguide/runs").status_code == 501


def test_store_put_get_trace_roundtrip_unit():
    from guidancegrid.core.trace import Trace
    s = Store()
    t = Trace({"model": "m", "runtime": "r"})
    t.append({"ev": "STATE", "turn": 0, "drift": 0.1})
    t.append({"ev": "STATE", "turn": 1, "drift": 0.2})
    key = s.put_trace(t)
    assert s.put_trace(t) == key                 # idempotent
    back = s.get_trace(key)
    assert back.head == t.head and back.verify()
