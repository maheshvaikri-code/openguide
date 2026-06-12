"""The governance core: govern one chat call (streaming or not).

Pass-through is the default. When ``X-OpenGuide-Contract`` names a registered
contract, the Governor:
  1. injects any pending re-anchor (from the previous turn) into the request,
  2. forwards to the upstream,
  3. assembles the assistant message,
  4. runs the reconciler (records hash-chained behavioral state),
  5. stashes the next re-anchor on the session (feeds forward),
  6. emits a gen_ai.behavior.* span.

The client's response bytes are never rewritten — governance is side-channel.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .session import SessionStore
from .streaming import (
    StreamAssembler,
    detect_trigger_tokens,
    message_from_completion,
)
from .upstream import Upstream

CONTRACT_HEADER = "x-openguide-contract"
SESSION_HEADER = "x-openguide-session"


class ContractNotFound(KeyError):
    pass


class Governor:
    def __init__(self, registry: ContractRegistry, upstream: Upstream,
                 sessions: SessionStore | None = None, emitter=None):
        self.registry = registry
        self.upstream = upstream
        self.sessions = sessions or SessionStore()
        self.emitter = emitter or InMemorySpanEmitter()

    # ── helpers ──────────────────────────────────────────────────────
    def _manifest(self, compiled, session_id: str) -> dict[str, Any]:
        return {"model": compiled.model_id, "contract_hash": compiled.contract_hash,
                "runtime": "openguide-proxy-0.1", "session": session_id}

    def _inject(self, body: dict[str, Any], text: str) -> dict[str, Any]:
        msg = {"role": "system", "content": text}
        return {**body, "messages": [msg, *body.get("messages", [])]}

    def _gov_headers(self, compiled, out) -> dict[str, str]:
        h = {
            "X-OpenGuide-Contract": compiled.contract_hash,
            "X-OpenGuide-Tier": compiled.tier_active,
            "X-OpenGuide-Drift": f"{out.drift:.6f}",
        }
        if out.action:
            h["X-OpenGuide-Recovery"] = out.action
        return h

    def _reconcile(self, session_id: str, compiled, body, assistant_msg) -> Any:
        sess = self.sessions.get_or_create(
            session_id, compiled, self.registry.measures, self._manifest(compiled, session_id)
        )
        content = assistant_msg.get("content") or ""
        token_refs = detect_trigger_tokens(content, compiled.trigger_table)
        ctx = {
            "turn": sess.turn,
            "output": content,
            "tool_calls": assistant_msg.get("tool_calls", []),
            "messages": body.get("messages", []),
            "token_trigger_refs": token_refs,
        }
        out = sess.reconciler.step(sess.turn, ctx)
        sess.pending_reanchor = out.reanchor_text
        sess.turn += 1
        sess.max_drift = max(sess.max_drift, out.drift)
        if out.action in ("re_anchor", "escalate"):
            sess.recoveries += 1
        sess.halted = out.halted
        sess.history.append(out.state)
        self.emitter.emit_turn(out.state, compiled, sess)
        return sess, out

    def _resolve(self, body, headers) -> tuple[str, Any] | None:
        """Return (session_id, compiled) if governed, else None for passthrough."""
        ch = headers.get(CONTRACT_HEADER)
        if not ch:
            return None
        if not self.registry.has(ch):
            raise ContractNotFound(ch)
        model = body.get("model", "unknown")
        compiled = self.registry.compiled(ch, model)
        session_id = headers.get(SESSION_HEADER) or f"anon:{ch[:16]}"
        return session_id, compiled

    # ── non-streaming ────────────────────────────────────────────────
    async def chat(self, body: dict[str, Any], headers: dict[str, str]):
        resolved = self._resolve(body, headers)
        if resolved is None:
            return await self.upstream.chat(body, headers), {}
        session_id, compiled = resolved
        sess = self.sessions.get(session_id)
        send_body = body
        if sess is not None and sess.pending_reanchor:
            send_body = self._inject(body, sess.pending_reanchor)
        resp = await self.upstream.chat(send_body, headers)
        msg = message_from_completion(resp)
        _, out = self._reconcile(session_id, compiled, body, msg)
        return resp, self._gov_headers(compiled, out)

    # ── streaming ────────────────────────────────────────────────────
    async def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        resolved = self._resolve(body, headers)
        if resolved is None:
            async for chunk in self.upstream.stream(body, headers):
                yield chunk
            return
        session_id, compiled = resolved
        sess = self.sessions.get(session_id)
        send_body = body
        if sess is not None and sess.pending_reanchor:
            send_body = self._inject(body, sess.pending_reanchor)

        assembler = StreamAssembler()
        async for chunk in self.upstream.stream(send_body, headers):
            assembler.feed_bytes(chunk)
            yield chunk                       # client stream is byte-identical
        # turn complete: reconcile + emit side-channel (no stream mutation)
        self._reconcile(session_id, compiled, body, assembler.message())
