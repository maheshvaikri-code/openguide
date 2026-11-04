"""FastAPI app: an OpenAI-compatible proxy with header-activated governance.

Routes:
  POST /v1/chat/completions          - proxy (streaming + non-streaming)
  POST /v1/openguide/contracts       - register an OBC contract -> {contract_hash}
  GET  /v1/openguide/sessions/{id}   - behavioral-state summary for a session
  GET  /v1/openguide/spans           - emitted gen_ai.behavior.* spans (in-memory emitter)
  GET  /healthz                      - liveness

Governance is opt-in via the ``X-OpenGuide-Contract`` header; without it the
proxy is a transparent pass-through. Control-plane endpoints under
``/v1/openguide/*`` require ``OPENGUIDE_ADMIN_TOKEN`` when configured.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .governance import ContractNotFound, Governor, ToolPolicyDenied
from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .session import SessionStore
from .tool_policy import ToolPolicy
from .upstream import MockUpstream, Upstream


def create_app(*, registry: ContractRegistry | None = None, upstream: Upstream | None = None,
               sessions: SessionStore | None = None, emitter=None, store=None,
               admin_token: str | None = None, tool_policy: ToolPolicy | None = None) -> FastAPI:
    app = FastAPI(title="OpenGuide Proxy", version="0.1.0")

    registry = registry or ContractRegistry()
    upstream = upstream or MockUpstream()
    emitter = emitter or InMemorySpanEmitter()
    tool_policy = tool_policy or ToolPolicy()
    governor = Governor(
        registry,
        upstream,
        sessions or SessionStore(),
        emitter,
        store=store,
        tool_policy=tool_policy,
    )

    app.state.registry = registry
    app.state.governor = governor
    app.state.emitter = emitter
    app.state.store = store
    app.state.admin_token = admin_token
    app.state.tool_policy = tool_policy

    def require_admin(req: Request) -> JSONResponse | None:
        """Protect control-plane endpoints when an admin token is configured."""
        if not admin_token:
            return None
        supplied = req.headers.get("x-openguide-admin-token", "")
        auth = req.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth.split(" ", 1)[1].strip()
        if secrets.compare_digest(supplied, admin_token):
            return None
        return JSONResponse({"error": "admin token required"}, status_code=401)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/openguide/contracts")
    async def register_contract(req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        body = await req.json()
        try:
            h = registry.register(body)
        except Exception as exc:  # validation error
            return JSONResponse({"error": str(exc)}, status_code=422)
        return {"contract_hash": h}

    @app.get("/v1/openguide/sessions/{session_id}")
    async def session_state(session_id: str, req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        sess = governor.sessions.get(session_id)
        if sess is None:
            return JSONResponse({"error": "no such session"}, status_code=404)
        return {
            "session_id": session_id,
            "turns": sess.turn,
            "max_drift": round(sess.max_drift, 6),
            "recoveries": sess.recoveries,
            "halted": sess.halted,
            "contract_hash": sess.compiled.contract_hash,
            "tier": sess.compiled.tier_active,
            "trace_head": sess.reconciler.trace.head,
            "trace_verified": sess.reconciler.trace.verify(),
        }

    @app.get("/v1/openguide/spans")
    async def spans(req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        if isinstance(emitter, InMemorySpanEmitter):
            return {"spans": emitter.spans}
        return {"spans": []}

    @app.get("/v1/openguide/runs")
    async def runs(req: Request, contract: str | None = None, min_drift: float | None = None,
                   halted: bool | None = None, limit: int = 100):
        denied = require_admin(req)
        if denied is not None:
            return denied
        if store is None:
            return JSONResponse({"error": "no store configured"}, status_code=501)
        rows = store.query_runs(contract_hash=contract, min_drift=min_drift,
                                halted=halted, limit=limit)
        return {"runs": [r.__dict__ for r in rows]}

    def trace_payload(t, cas_key: str | None, metadata_only: bool = False) -> dict[str, Any]:
        payload = {
            "manifest": t.manifest,
            "head": t.head,
            "verified": t.verify(),
            "cas_key": cas_key,
        }
        if metadata_only:
            event_counts: dict[str, int] = {}
            for rec in t.records:
                ev = str(rec.get("ev", "UNKNOWN"))
                event_counts[ev] = event_counts.get(ev, 0) + 1
            return {
                **payload,
                "metadata_only": True,
                "record_count": len(t.records),
                "event_counts": event_counts,
            }
        return {**payload, "records": t.records}

    @app.get("/v1/openguide/runs/{run_id}/trace")
    async def run_trace(run_id: str, req: Request, metadata_only: bool = False):
        denied = require_admin(req)
        if denied is not None:
            return denied
        sess = governor.sessions.get(run_id)
        if sess is None and store is not None:
            run = store.get_run(run_id)
            if run is not None and run.trace_cas_key:
                t = store.get_trace(run.trace_cas_key)
                if t is not None:
                    return trace_payload(t, run.trace_cas_key, metadata_only)
        if sess is None:
            return JSONResponse({"error": "no such run/trace"}, status_code=404)
        t = sess.reconciler.trace
        cas_key = store.put_trace(t) if store is not None else None   # durable copy
        return trace_payload(t, cas_key, metadata_only)

    @app.post("/v1/chat/completions")
    async def chat_completions(req: Request):
        body: dict[str, Any] = await req.json()
        headers = {k.lower(): v for k, v in req.headers.items()}
        # validate the contract up front so streaming can't fail mid-response
        ch = headers.get("x-openguide-contract")
        if ch and not registry.has(ch):
            return JSONResponse({"error": f"unknown contract: {ch}"}, status_code=404)
        try:
            if body.get("stream"):
                if governor.tool_policy.enabled:
                    chunks, gov_headers = await governor.preflight_stream(body, headers)
                    return StreamingResponse(
                        iter(chunks), media_type="text/event-stream", headers=gov_headers
                    )
                gen, gov_headers = governor.open_stream(body, headers)
                return StreamingResponse(gen, media_type="text/event-stream", headers=gov_headers)
            resp, gov_headers = await governor.chat(body, headers)
            return JSONResponse(resp, headers=gov_headers)
        except ContractNotFound as exc:
            return JSONResponse(
                {"error": f"unknown contract: {exc.args[0]}"}, status_code=404
            )
        except ToolPolicyDenied as exc:
            return JSONResponse(
                {
                    "error": "tool call denied by OpenGuide policy",
                    "reason": exc.decision.reason,
                    "tools": exc.decision.tools,
                },
                status_code=403,
                headers=exc.headers,
            )

    return app
