"""Optional admin-token protection for control-plane endpoints."""
import os

from fastapi.testclient import TestClient

from guidancegrid.obc import load_contract
from guidancegrid.store import Store
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream

CONTRACT = os.path.join(
    os.path.dirname(__file__), "..", "spec", "obc", "examples", "coding-agent-default.toml"
)
ADMIN = "secret-admin-token"


def _build():
    reg = ContractRegistry()
    h = reg.load_file(CONTRACT)
    store = Store()
    app = create_app(
        registry=reg,
        upstream=MockUpstream(lambda b: "ok"),
        store=store,
        admin_token=ADMIN,
    )
    return TestClient(app), h


def test_admin_token_protects_control_plane_but_not_health_or_chat():
    client, h = _build()
    assert client.get("/healthz").status_code == 200

    r = client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "auth-run"},
        json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200

    assert client.get("/v1/openguide/sessions/auth-run").status_code == 401
    assert client.get(
        "/v1/openguide/sessions/auth-run",
        headers={"X-OpenGuide-Admin-Token": "wrong"},
    ).status_code == 401
    ok = client.get(
        "/v1/openguide/sessions/auth-run",
        headers={"X-OpenGuide-Admin-Token": ADMIN},
    )
    assert ok.status_code == 200 and ok.json()["session_id"] == "auth-run"


def test_admin_token_accepts_bearer_auth_for_control_endpoints():
    client, h = _build()
    body = load_contract(CONTRACT)
    headers = {"Authorization": f"Bearer {ADMIN}"}

    registered = client.post("/v1/openguide/contracts", headers=headers, json=body)
    assert registered.status_code == 200
    assert registered.json()["contract_hash"] == h

    client.post(
        "/v1/chat/completions",
        headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "trace-auth"},
        json={"model": "openai:gpt-4o", "messages": [{"role": "user", "content": "x"}]},
    )
    assert client.get("/v1/openguide/spans").status_code == 401
    assert client.get("/v1/openguide/spans", headers=headers).status_code == 200
    assert client.get("/v1/openguide/runs").status_code == 401
    assert client.get("/v1/openguide/runs", headers=headers).status_code == 200
    assert client.get("/v1/openguide/runs/trace-auth/trace").status_code == 401
    trace = client.get("/v1/openguide/runs/trace-auth/trace", headers=headers)
    assert trace.status_code == 200 and trace.json()["verified"] is True
