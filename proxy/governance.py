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

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import uuid4

from guidancegrid.core.trace import turn_event

from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .session import SessionStore
from .streaming import (
    StreamAssembler,
    detect_trigger_tokens,
    message_from_completion,
)
from .tool_policy import ToolPolicy, ToolPolicyDecision
from .upstream import Upstream

log = logging.getLogger("openguide.proxy")

CONTRACT_HEADER = "x-openguide-contract"
SESSION_HEADER = "x-openguide-session"


class ContractNotFound(KeyError):
    pass


class ToolPolicyDenied(Exception):
    def __init__(self, decision: ToolPolicyDecision, headers: dict[str, str]):
        super().__init__(decision.reason)
        self.decision = decision
        self.headers = headers


@dataclass(frozen=True)
class ResolvedGovernance:
    session_id: str
    compiled: Any
    generated_session: bool = False


class Governor:
    def __init__(self, registry: ContractRegistry, upstream: Upstream,
                 sessions: SessionStore | None = None, emitter=None, store=None,
                 tool_policy: ToolPolicy | None = None, capture_content: bool = False):
        self.registry = registry
        self.upstream = upstream
        self.sessions = sessions or SessionStore()
        self.emitter = emitter or InMemorySpanEmitter()
        self.store = store                      # optional guidancegrid.store.Store
        self.tool_policy = tool_policy or ToolPolicy()
        # Opt-in, off by default: traces then hold behavioral state only, never message text.
        self.capture_content = capture_content

    # ── helpers ──────────────────────────────────────────────────────
    def _manifest(self, compiled, session_id: str) -> dict[str, Any]:
        return {"model": compiled.model_id, "contract_hash": compiled.contract_hash,
                "runtime": "openguide-proxy-0.1", "session": session_id}

    def _inject(self, body: dict[str, Any], text: str) -> dict[str, Any]:
        msg = {"role": "system", "content": text}
        return {**body, "messages": [msg, *body.get("messages", [])]}

    def _base_gov_headers(self, compiled, resolved: ResolvedGovernance) -> dict[str, str]:
        h = {
            "X-OpenGuide-Contract": compiled.contract_hash,
            "X-OpenGuide-Tier": compiled.tier_active,
            "X-OpenGuide-Session": resolved.session_id,
        }
        if resolved.generated_session:
            h["X-OpenGuide-Session-Generated"] = "true"
        return h

    def _gov_headers(self, compiled, out, resolved: ResolvedGovernance) -> dict[str, str]:
        h = {
            **self._base_gov_headers(compiled, resolved),
            "X-OpenGuide-Drift": f"{out.drift:.6f}",
        }
        if out.action:
            h["X-OpenGuide-Recovery"] = out.action
        return h

    def _tool_policy_headers(self, decision: ToolPolicyDecision) -> dict[str, str]:
        if not decision.tools:
            return {}
        h = {
            "X-OpenGuide-Tool-Decision": decision.decision,
            "X-OpenGuide-Tool-Reason": decision.reason,
            "X-OpenGuide-Tool-Names": ",".join(t["name"] for t in decision.tools),
        }
        if decision.denied:
            h["X-OpenGuide-Blocked"] = "tool_policy"
        return h

    @staticmethod
    def _latest_user_text(body: dict[str, Any]) -> str:
        """The text of the newest user message (not the whole history, never the system prompt)."""
        for m in reversed(body.get("messages", [])):
            if m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, list):                  # only real text parts; images etc. are not text
                    parts = (p.get("text") for p in c if isinstance(p, dict))
                    return "".join(t for t in parts if isinstance(t, str))
                return c if isinstance(c, str) else ""
        return ""

    def _record_turn(self, sess, body, content: str, restated: str | None) -> None:
        """Append a TURN event after the turn's STATE (see guidancegrid.core.trace.turn_event)."""
        user = self._latest_user_text(body)
        output = content if isinstance(content, str) else ""
        sess.reconciler.trace.append(turn_event(sess.turn - 1, user, output, restated))

    def _reconcile(self, session_id: str, compiled, body, assistant_msg,
                   restated: str | None = None) -> Any:
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
        if self.capture_content:
            try:
                self._record_turn(sess, body, content, restated)
            except Exception:                            # noqa: BLE001
                # Capture is a convenience: it must never break a governed call or leave the run unsaved.
                log.exception("could not record the TURN event; the turn is still recorded as behavior")
        self.emitter.emit_turn(out.state, compiled, sess)
        self._persist(sess, compiled)
        return sess, out

    def _record_tool_policy(self, sess, decision: ToolPolicyDecision) -> None:
        if not decision.tools:
            return
        sess.reconciler.trace.append({
            "turn": sess.turn - 1,
            "ev": "TOOL_POLICY",
            "decision": decision.decision,
            "reason": decision.reason,
            "tools": decision.tools,
        })
        self._persist(sess, sess.compiled)

    def _evaluate_tool_policy(self, sess, assistant_msg) -> ToolPolicyDecision:
        decision = self.tool_policy.evaluate(assistant_msg.get("tool_calls", []))
        self._record_tool_policy(sess, decision)
        return decision

    def _persist(self, sess, compiled) -> None:
        """Persist the trace snapshot and upsert the run row every turn."""
        if self.store is None:
            return
        from guidancegrid.store import RunRecord

        trace_cas_key = self.store.put_trace(sess.reconciler.trace)
        self.store.put_run(RunRecord(
            run_id=sess.session_id, contract_hash=compiled.contract_hash,
            model=compiled.model_id, tier=compiled.tier_active, turns=sess.turn,
            max_drift=round(sess.max_drift, 6), recoveries=sess.recoveries,
            halted=sess.halted, verified=sess.reconciler.trace.verify(),
            trace_hash=sess.reconciler.trace.head, trace_cas_key=trace_cas_key, created="",
        ))

    def _resolve(self, body, headers) -> ResolvedGovernance | None:
        """Return governance context if governed, else None for passthrough.

        Explicit ``X-OpenGuide-Session`` drives cross-call continuity. If the
        caller omits it, create a unique anonymous session for this request so
        unrelated governed calls never share behavioral state by accident.
        """
        ch = headers.get(CONTRACT_HEADER)
        if not ch:
            return None
        if not self.registry.has(ch):
            raise ContractNotFound(ch)
        model = body.get("model", "unknown")
        compiled = self.registry.compiled(ch, model)
        supplied = (headers.get(SESSION_HEADER) or "").strip()
        if supplied:
            return ResolvedGovernance(supplied, compiled, generated_session=False)
        return ResolvedGovernance(f"anon:{uuid4().hex}", compiled, generated_session=True)

    # ── non-streaming ────────────────────────────────────────────────
    async def chat(self, body: dict[str, Any], headers: dict[str, str]):
        resolved = self._resolve(body, headers)
        if resolved is None:
            return await self.upstream.chat(body, headers), {}
        session_id, compiled = resolved.session_id, resolved.compiled
        sess = self.sessions.get(session_id)
        send_body = body
        restated = sess.pending_reanchor if sess is not None and sess.pending_reanchor else None
        if restated:
            send_body = self._inject(body, restated)
        resp = await self.upstream.chat(send_body, headers)
        msg = message_from_completion(resp)
        sess, out = self._reconcile(session_id, compiled, body, msg, restated)
        gov_headers = self._gov_headers(compiled, out, resolved)
        decision = self._evaluate_tool_policy(sess, msg)
        gov_headers = {**gov_headers, **self._tool_policy_headers(decision)}
        if decision.denied:
            raise ToolPolicyDenied(decision, gov_headers)
        return resp, gov_headers

    # ── streaming ────────────────────────────────────────────────────
    def open_stream(
        self, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[AsyncIterator[bytes], dict[str, str]]:
        resolved = self._resolve(body, headers)
        if resolved is None:
            return self.upstream.stream(body, headers), {}
        return (
            self._stream_resolved(body, headers, resolved),
            self._base_gov_headers(resolved.compiled, resolved),
        )

    async def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        gen, _ = self.open_stream(body, headers)
        async for chunk in gen:
            yield chunk

    async def preflight_stream(
        self, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[list[bytes], dict[str, str]]:
        """Buffer a governed stream so tool policy can deny before bytes leave."""
        resolved = self._resolve(body, headers)
        if resolved is None:
            chunks = [chunk async for chunk in self.upstream.stream(body, headers)]
            return chunks, {}

        session_id, compiled = resolved.session_id, resolved.compiled
        sess = self.sessions.get(session_id)
        send_body = body
        restated = sess.pending_reanchor if sess is not None and sess.pending_reanchor else None
        if restated:
            send_body = self._inject(body, restated)

        assembler = StreamAssembler()
        chunks: list[bytes] = []
        async for chunk in self.upstream.stream(send_body, headers):
            assembler.feed_bytes(chunk)
            chunks.append(chunk)
        sess, out = self._reconcile(session_id, compiled, body, assembler.message(), restated)
        gov_headers = self._gov_headers(compiled, out, resolved)
        decision = self._evaluate_tool_policy(sess, assembler.message())
        gov_headers = {**gov_headers, **self._tool_policy_headers(decision)}
        if decision.denied:
            raise ToolPolicyDenied(decision, gov_headers)
        return chunks, gov_headers

    async def _stream_resolved(self, body: dict[str, Any], headers: dict[str, str],
                               resolved: ResolvedGovernance) -> AsyncIterator[bytes]:
        session_id, compiled = resolved.session_id, resolved.compiled
        sess = self.sessions.get(session_id)
        send_body = body
        restated = sess.pending_reanchor if sess is not None and sess.pending_reanchor else None
        if restated:
            send_body = self._inject(body, restated)

        assembler = StreamAssembler()
        async for chunk in self.upstream.stream(send_body, headers):
            assembler.feed_bytes(chunk)
            yield chunk                       # client stream is byte-identical
        # turn complete: reconcile + emit side-channel (no stream mutation)
        sess, _ = self._reconcile(session_id, compiled, body, assembler.message(), restated)
        self._evaluate_tool_policy(sess, assembler.message())
        # Streaming headers were sent before the final tool decision was known.
        # Enforcing policies should use preflight_stream, which buffers first.
