"""Tool-call authorization gates for governed agent actions."""
import os

from fastapi.testclient import TestClient

from guidancegrid.store import Store
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.tool_policy import ToolPolicy
from proxy.upstream import MockUpstream

CONTRACT = os.path.join(
    os.path.dirname(__file__), "..", "spec", "obc", "examples", "coding-agent-default.toml"
)


def _tool_completion(name: str, arguments: str = '{"id":"u-123"}'):
    return {
        "id": "chatcmpl-tool",
        "object": "chat.completion",
        "model": "mock:agent-v1",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _build(policy: ToolPolicy, responder=None):
    reg = ContractRegistry()
    h = reg.load_file(CONTRACT)
    store = Store()
    app = create_app(
        registry=reg,
        upstream=MockUpstream(responder or (lambda b: _tool_completion("search"))),
        store=store,
        tool_policy=policy,
    )
    return TestClient(app), h, store


def test_denied_tool_call_returns_403_and_records_trace_event():
    client, h, store = _build(
        ToolPolicy(deny=["delete_user"]),
        lambda b: _tool_completion("delete_user", '{"secret":"do-not-store"}'),
    )

    r = client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "tool-denied"},
        json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "delete"}]},
    )

    assert r.status_code == 403
    assert r.headers["x-openguide-blocked"] == "tool_policy"
    assert r.headers["x-openguide-tool-decision"] == "deny"
    assert r.json()["reason"] == "denylist:delete_user"

    run = store.get_run("tool-denied")
    trace = store.get_trace(run.trace_cas_key)
    event = [rec for rec in trace.records if rec.get("ev") == "TOOL_POLICY"][-1]
    assert event["decision"] == "deny"
    assert event["tools"] == [{"id": "call_1", "name": "delete_user"}]
    assert "do-not-store" not in str(event)
    assert trace.verify()


def test_allowed_tool_call_passes_through_with_audit_headers():
    client, h, store = _build(ToolPolicy(allow=["search"]))
    r = client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "tool-allowed"},
        json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "search"}]},
    )

    assert r.status_code == 200
    assert r.headers["x-openguide-tool-decision"] == "allow"
    assert r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "search"

    trace = store.get_trace(store.get_run("tool-allowed").trace_cas_key)
    event = [rec for rec in trace.records if rec.get("ev") == "TOOL_POLICY"][-1]
    assert event["decision"] == "allow"
    assert event["reason"] == "allowed"


def test_allowlist_denies_unlisted_tool():
    client, h, _ = _build(ToolPolicy(allow=["search"]), lambda b: _tool_completion("crm.write"))
    r = client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "tool-unlisted"},
        json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "write"}]},
    )

    assert r.status_code == 403
    assert r.json()["reason"] == "not_allowed:crm.write"


def test_streaming_tool_policy_denies_before_stream_bytes_are_returned():
    client, h, _ = _build(ToolPolicy(deny=["delete_user"]), lambda b: _tool_completion("delete_user"))
    r = client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "tool-stream-denied"},
        json={
            "model": "openai:gpt-4o",
            "stream": True,
            "messages": [{"role": "user", "content": "delete"}],
        },
    )

    assert r.status_code == 403
    assert r.headers["x-openguide-tool-decision"] == "deny"
    assert "data:" not in r.text
