"""Behavioral-state -> OTel attribute mapping + emitter behaviors."""
import os

from guidancegrid.compiler import compile_contract
from guidancegrid.obc import load_contract
from proxy.otel import (
    InMemorySpanEmitter,
    NullSpanEmitter,
    OTLPSpanEmitter,
    behavior_attributes,
)


class _FakeSpan:
    def __init__(self):
        self.attrs = {}
        self.ended = False

    def set_attribute(self, k, v):
        self.attrs[k] = v

    def end(self):
        self.ended = True


class _FakeTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name):
        s = _FakeSpan()
        s.name = name
        self.spans.append(s)
        return s


class _Sess:
    class _RC:
        class _T:
            head = "sha256:" + "a" * 64
        trace = _T()
    reconciler = _RC()


def _compiled():
    c = load_contract(os.path.join(os.path.dirname(__file__), "..", "spec", "obc",
                                   "examples", "coding-agent-default.toml"))
    return compile_contract(c, "openai:gpt-4o")


STATE = {
    "turn": 3, "tier_active": "t2", "drift": 0.31,
    "invariants": {"adherence": {"reading": 0.54, "violated": True, "determinism": "stochastic"}},
    "recovery_fired": "re_anchor", "sensor_gaps": ["cesr"],
}


def test_behavior_attributes_mapping():
    attrs = behavior_attributes(STATE, _compiled(), _Sess())
    assert attrs["gen_ai.behavior.turn"] == 3
    assert attrs["gen_ai.behavior.tier"] == "t2"
    assert attrs["gen_ai.behavior.drift"] == 0.31
    assert attrs["gen_ai.behavior.invariant.adherence"] == 0.54
    assert attrs["gen_ai.behavior.invariant.adherence.violated"] is True
    assert attrs["gen_ai.behavior.recovery"] == "re_anchor"
    assert attrs["gen_ai.behavior.sensor_gaps"] == ["cesr"]
    assert attrs["gen_ai.behavior.contract_hash"].startswith("sha256:")
    assert attrs["gen_ai.behavior.record_hash"].startswith("sha256:")


def test_inmemory_emitter_collects():
    em = InMemorySpanEmitter()
    em.emit_turn(STATE, _compiled(), _Sess())
    assert len(em.spans) == 1 and em.spans[0]["name"] == "gen_ai.behavior.turn"


def test_null_emitter_noop():
    assert NullSpanEmitter().emit_turn(STATE, _compiled(), _Sess()) is None


def test_otlp_emitter_sets_attrs_and_ends_span():
    tracer = _FakeTracer()
    OTLPSpanEmitter(tracer).emit_turn(STATE, _compiled(), _Sess())
    assert len(tracer.spans) == 1
    span = tracer.spans[0]
    assert span.ended is True
    assert span.attrs["gen_ai.behavior.drift"] == 0.31
    assert span.attrs["gen_ai.behavior.tier"] == "t2"
