"""FastAPI app: an OpenAI-compatible proxy with header-activated governance.

Routes:
  POST /v1/chat/completions          - proxy (streaming + non-streaming)
  POST /v1/openguide/contracts       - register an OBC contract -> {contract_hash}
  GET  /v1/openguide/sessions/{id}   - behavioral-state summary for a session
  GET  /v1/openguide/spans           - emitted gen_ai.behavior.* spans (in-memory emitter)
  GET  /healthz                      - liveness

Governance is opt-in via the ``X-OpenGuide-Contract`` header; without it the
proxy is a transparent pass-through.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .governance import ContractNotFound, Governor
from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .session import SessionStore
from .upstream import MockUpstream, Upstream


def create_app(*, registry: ContractRegistry | None = None, upstream: Upstream | None = None,
               sessions: SessionStore | None = None, emitter=None) -> FastAPI:
    app = FastAPI(title="OpenGuide Proxy", version="0.1.0")

    registry = registry or ContractRegistry()
    upstream = upstream or MockUpstream()
    emitter = emitter or InMemorySpanEmitter()
    governor = Governor(registry, upstream, sessions or SessionStore(), emitter)

    app.state.registry = registry
    app.state.governor = governor
    app.state.emitter = emitter

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/openguide/contracts")
    async def register_contract(req: Request):
        body = await req.json()
        try:
            h = registry.register(body)
        except Exception as exc:  # validation error
            return JSONResponse({"error": str(exc)}, status_code=422)
        return {"contract_hash": h}

    @app.get("/v1/openguide/sessions/{session_id}")
    async def session_state(session_id: str):
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
    async def spans():
        if isinstance(emitter, InMemorySpanEmitter):
            return {"spans": emitter.spans}
        return {"spans": []}

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
                gen = governor.stream(body, headers)
                return StreamingResponse(gen, media_type="text/event-stream")
            resp, gov_headers = await governor.chat(body, headers)
            return JSONResponse(resp, headers=gov_headers)
        except ContractNotFound as exc:
            return JSONResponse(
                {"error": f"unknown contract: {exc.args[0]}"}, status_code=404
            )

    return app
