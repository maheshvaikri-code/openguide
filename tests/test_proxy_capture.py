"""Opt-in content capture: a TURN event per governed turn, inside the hash chain, off by default."""
import os

from fastapi.testclient import TestClient

from guidancegrid.core.canonical import chash
from guidancegrid.obc import load_contract
from guidancegrid.sensors import JudgeMeasure, MeasureRegistry, StructuralMeasure
from guidancegrid.store import Store
from proxy.app import create_app
from proxy.config import ProxyConfig
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream

CONTRACT = os.path.join(
    os.path.dirname(__file__), "..", "spec", "obc", "examples", "coding-agent-default.toml")


def _setup(capture, replies, store=None):
    """A model that says what the test scripts. The sensor reads a 'good' reply as adherent and anything
    else as a moderate violation (drift 0.30: the contract's re-anchor rung, below escalate and halt)."""
    measures = MeasureRegistry()
    measures.register(JudgeMeasure("judge:instruction_adherence",
                                   lambda ctx: 0.95 if "good" in ctx["output"] else 0.55))
    measures.register(StructuralMeasure("structural:tests_pass_before_commit", lambda ctx: True))
    measures.register(StructuralMeasure("external:codemonk.cesr", lambda ctx: 0.9))
    reg = ContractRegistry(measures=measures)
    h = reg.register(load_contract(CONTRACT))
    it = iter(replies)
    up = MockUpstream(lambda body: next(it))
    app = create_app(registry=reg, upstream=up, store=store, capture_content=capture)
    return TestClient(app), h, up, app


def _say(client, h, text, sid="s1"):
    headers = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": sid}
    return client.post("/v1/chat/completions", headers=headers,
                       json={"model": "mock:m", "messages": [{"role": "user", "content": text}]})


def _trace(app, sid="s1"):
    return app.state.governor.sessions.get(sid).reconciler.trace


def test_content_is_not_captured_by_default():
    c, h, _, app = _setup(False, ["good one", "good two"])
    _say(c, h, "hello")
    _say(c, h, "again")
    evs = [r["ev"] for r in _trace(app).records]
    assert evs == ["STATE", "STATE"]                           # nothing but behavioral state
    assert "hello" not in str(_trace(app).records)


def test_capture_adds_one_turn_event_per_turn_with_the_user_message_and_the_reply():
    c, h, _, app = _setup(True, ["good one", "good two"])
    _say(c, h, "first question")
    _say(c, h, "second question")
    recs = _trace(app).records
    assert [r["ev"] for r in recs] == ["STATE", "TURN", "STATE", "TURN"]
    turns = [r for r in recs if r["ev"] == "TURN"]
    assert [t["turn"] for t in turns] == [0, 1]
    assert [t["user"] for t in turns] == ["first question", "second question"]
    assert [t["output"] for t in turns] == ["good one", "good two"]
    assert [r["turn"] for r in recs if r["ev"] == "STATE"] == [0, 1]       # same turn numbering as STATE


def test_the_restatement_sent_with_a_request_is_recorded_on_that_turn():
    c, h, up, app = _setup(True, ["bad reply", "good reply", "good reply"])
    _say(c, h, "q0")                                           # drifts: the sensor reads 0.55
    _say(c, h, "q1")                                           # carries the re-anchor prepared after turn 0
    _say(c, h, "q2")
    turns = [r for r in _trace(app).records if r["ev"] == "TURN"]
    assert turns[0]["restated"] is None
    assert turns[1]["restated"]                                # what was restated to the model
    sent_system = [m["content"] for m in up.calls[1]["messages"] if m["role"] == "system"]
    assert sent_system == [turns[1]["restated"]]               # byte-for-byte what the upstream received
    assert up.calls[0]["messages"][0]["role"] == "user"        # turn 0 carried nothing extra


def test_turn_events_are_inside_the_hash_chain():
    c, h, _, app = _setup(True, ["good", "good"])
    _say(c, h, "q0")
    _say(c, h, "q1")
    t = _trace(app)
    assert t.verify()
    t.records[1]["output"] = "tampered reply"                  # edit captured content
    assert not t.verify()


def test_very_long_content_is_clipped_and_flagged():
    c, h, _, app = _setup(True, ["good " + "x" * 50_000])
    _say(c, h, "u" * 50_000)
    turn = next(r for r in _trace(app).records if r["ev"] == "TURN")
    assert len(turn["output"]) < 9_000 and len(turn["user"]) < 9_000
    assert turn["truncated"] is True
    short = _setup(True, ["good"])
    _say(short[0], short[1], "hi")
    assert next(r for r in _trace(short[3]).records if r["ev"] == "TURN")["truncated"] is False


def test_only_the_latest_user_message_is_recorded_not_the_whole_history():
    c, h, _, app = _setup(True, ["good"])
    c.post("/v1/chat/completions", headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "s1"},
           json={"model": "mock:m", "messages": [
               {"role": "system", "content": "SYSTEM SECRET"}, {"role": "user", "content": "old"},
               {"role": "assistant", "content": "old reply"}, {"role": "user", "content": "the new one"}]})
    turn = next(r for r in _trace(app).records if r["ev"] == "TURN")
    assert turn["user"] == "the new one"
    assert "SYSTEM SECRET" not in str(turn)


def test_the_metadata_only_view_never_includes_captured_content():
    store = Store()
    c, h, _, _ = _setup(True, ["very private reply"], store=store)
    _say(c, h, "very private question")
    body = c.get("/v1/openguide/runs/s1/trace?metadata_only=true").json()
    assert "records" not in body and body["event_counts"] == {"STATE": 1, "TURN": 1}
    assert "private" not in str(body)
    full = c.get("/v1/openguide/runs/s1/trace").json()
    assert any(r["ev"] == "TURN" and r["output"] == "very private reply" for r in full["records"])
    assert full["verified"] is True and full["chain"]["ok"] is True


def test_a_stored_trace_with_content_reloads_and_still_verifies():
    store = Store()
    c, h, _, _ = _setup(True, ["good"], store=store)
    _say(c, h, "q")
    run = store.get_run("s1")
    reloaded = store.get_trace(run.trace_cas_key)
    assert reloaded.verify() and [r["ev"] for r in reloaded.records] == ["STATE", "TURN"]
    assert chash(reloaded.manifest) == reloaded.genesis


def test_capture_is_configured_from_the_environment(monkeypatch):
    assert ProxyConfig().capture_content is False
    monkeypatch.setenv("OPENGUIDE_CAPTURE_CONTENT", "1")
    assert ProxyConfig.from_env().capture_content is True
    monkeypatch.setenv("OPENGUIDE_CAPTURE_CONTENT", "false")
    assert ProxyConfig.from_env().capture_content is False
    monkeypatch.delenv("OPENGUIDE_CAPTURE_CONTENT")
    assert ProxyConfig.from_env().capture_content is False


def test_streaming_turns_are_captured_too():
    c, h, _, app = _setup(True, ["good streamed reply"])
    body = {"model": "mock:m", "stream": True, "messages": [{"role": "user", "content": "stream me"}]}
    with c.stream("POST", "/v1/chat/completions",
                  headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "s1"}, json=body) as r:
        b"".join(r.iter_bytes())
    turn = next(x for x in _trace(app).records if x["ev"] == "TURN")
    assert turn["user"] == "stream me" and turn["output"] == "good streamed reply"


def test_turn_event_has_one_shared_shape_and_clips_each_field():
    from guidancegrid.core.trace import MAX_CAPTURE_CHARS, turn_event

    ev = turn_event(3, "hi", "hello", "restate")
    assert ev == {"ev": "TURN", "turn": 3, "user": "hi", "output": "hello", "restated": "restate",
                  "truncated": False}
    assert turn_event(0, "u", "o")["restated"] is None
    big = turn_event(0, "u" * (MAX_CAPTURE_CHARS + 1), "o", None)
    assert len(big["user"]) == MAX_CAPTURE_CHARS and big["truncated"] is True
    assert turn_event(0, "u", "o", "r" * (MAX_CAPTURE_CHARS + 5))["truncated"] is True



# ── security review: capture must never break a governed call, and never run on an open proxy by accident ──
def test_a_non_string_text_part_does_not_crash_the_call_and_is_not_recorded():
    c, h, _, app = _setup(True, ["good"])
    r = c.post("/v1/chat/completions", headers={"X-OpenGuide-Contract": h, "X-OpenGuide-Session": "s1"},
               json={"model": "mock:m", "messages": [{"role": "user", "content": [
                   {"type": "text", "text": 123}, {"type": "text", "text": "kept"}, {"type": "image_url"}]}]})
    assert r.status_code == 200
    turn = next(x for x in _trace(app).records if x["ev"] == "TURN")
    assert turn["user"] == "kept"                                  # only real strings


def test_a_failure_while_recording_text_never_breaks_the_response_or_the_run(monkeypatch):
    import proxy.governance as gov

    def boom(*a, **k):
        raise RuntimeError("could not build the record")

    monkeypatch.setattr(gov, "turn_event", boom)
    store = Store()
    c, h, _, app = _setup(True, ["good reply"], store=store)
    r = _say(c, h, "hello")
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "good reply"
    # the turn is still recorded as behavior
    assert [x["ev"] for x in _trace(app).records] == ["STATE"]
    assert store.get_run("s1").turns == 1                              # ...and the run was persisted


def test_a_non_string_reply_is_coerced_not_crashed_on():
    c, h, _, app = _setup(True, [{"id": "x", "object": "chat.completion", "model": "m", "choices": [
        {"index": 0, "message": {"role": "assistant", "content": [{"type": "text", "text": "parts"}]},
         "finish_reason": "stop"}]}])
    assert _say(c, h, "q").status_code == 200
    turn = next(x for x in _trace(app).records if x["ev"] == "TURN")
    assert isinstance(turn["output"], str)
