"""Behavioral-state -> OpenTelemetry span emission.

Implements the gen_ai.behavior.* mapping from spec/state/otel-mapping.md. The
emitter is an interface: InMemorySpanEmitter records spans as dicts (tests +
console dogfooding); OTLPSpanEmitter forwards to any OTLP collector when
opentelemetry is configured. The data plane never blocks on emission.
"""
from __future__ import annotations

from typing import Any, Protocol


def behavior_attributes(state: dict[str, Any], compiled, session) -> dict[str, Any]:
    """Build the gen_ai.behavior.* attribute dict for one turn."""
    attrs: dict[str, Any] = {
        "gen_ai.behavior.turn": state["turn"],
        "gen_ai.behavior.tier": state["tier_active"],
        "gen_ai.behavior.drift": state["drift"],
        "gen_ai.behavior.contract_hash": compiled.contract_hash,
        "gen_ai.request.model": compiled.model_id,
    }
    for inv_id, reading in state.get("invariants", {}).items():
        if reading.get("reading") is not None:
            attrs[f"gen_ai.behavior.invariant.{inv_id}"] = reading["reading"]
        attrs[f"gen_ai.behavior.invariant.{inv_id}.violated"] = bool(reading.get("violated"))
    if state.get("recovery_fired"):
        attrs["gen_ai.behavior.recovery"] = state["recovery_fired"]
    if state.get("sensor_gaps"):
        attrs["gen_ai.behavior.sensor_gaps"] = list(state["sensor_gaps"])
    if "sigma_peak" in state:
        attrs["gen_ai.behavior.sigma_peak"] = state["sigma_peak"]
    attrs["gen_ai.behavior.record_hash"] = session.reconciler.trace.head
    return attrs


class SpanEmitter(Protocol):
    def emit_turn(self, state: dict[str, Any], compiled, session) -> None: ...


class InMemorySpanEmitter:
    """Collects spans in a list. Used by tests and the local console."""

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    def emit_turn(self, state: dict[str, Any], compiled, session) -> None:
        self.spans.append({
            "name": "gen_ai.behavior.turn",
            "attributes": behavior_attributes(state, compiled, session),
        })


class NullSpanEmitter:
    def emit_turn(self, state: dict[str, Any], compiled, session) -> None:
        return None


class OTLPSpanEmitter:
    """Emits real OTel spans via an injected tracer (opentelemetry).

    Kept dependency-light: the caller passes a configured tracer so the proxy
    doesn't hard-depend on a specific OTel SDK setup.
    """

    def __init__(self, tracer: Any):
        self.tracer = tracer

    def emit_turn(self, state: dict[str, Any], compiled, session) -> None:
        attrs = behavior_attributes(state, compiled, session)
        span = self.tracer.start_span("gen_ai.behavior.turn")
        try:
            for k, v in attrs.items():
                span.set_attribute(k, v)
        finally:
            span.end()
