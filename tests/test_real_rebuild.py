"""Rebuilding saved real-model runs with message text, by replaying the model's recorded replies."""
import asyncio
import copy

import pytest

from benchmarks import real_model as rm
from benchmarks import real_rebuild as rb
from guidancegrid.store import Store
from proxy.upstream import MockUpstream


def run(coro):
    return asyncio.run(coro)


def drifting():
    def respond(body):
        msgs = body["messages"]
        n = sum(1 for m in msgs if m["role"] == "user")
        anchored = any("[contract:anchor]" in m["content"] for m in msgs if m["role"] == "system")
        return "Sure. [END]" if n <= 3 or anchored else "**long** answer, no sign-off"
    return MockUpstream(respond)


def _saved(turns=8, seeds=2, shocks=(3,)):
    """What the experiment scripts save: every turn of every arm, from a model that drifts."""
    conv: dict[str, list] = {}
    for s in range(seeds):
        arms = {
            "none": run(rm.run_none(drifting(), s, turns, Store(), arm="shock-none", shocks=shocks)),
            "proxy": run(rm.run_contract(drifting(), s, turns, Store(), shocks=shocks)),
            "front1": run(rm.run_naive(drifting(), s, turns, 1, Store(), placement="front",
                                       arm="shock-front1", shocks=shocks)),
            "end3": run(rm.run_naive(drifting(), s, turns, 3, Store(), placement="end",
                                     arm="shock-end3", shocks=shocks)),
        }
        for name, r in arms.items():
            conv.setdefault(name, []).append({"seed": s, "turns": r.turns})
    return {"design": "shock", "seeds": seeds, "turns": turns, "shocks": list(shocks), "conversations": conv}


def test_replay_upstream_returns_the_recorded_replies_in_order_and_then_fails_loudly():
    up = rb.ReplayUpstream(["a", "b"])
    assert run(up.chat({}, {}))["choices"][0]["message"]["content"] == "a"
    assert run(up.chat({}, {}))["choices"][0]["message"]["content"] == "b"
    with pytest.raises(rb.FidelityError, match="more replies"):
        run(up.chat({}, {}))                                   # asking for more than was recorded is a bug


def test_a_rebuild_reproduces_every_recorded_turn_and_adds_the_text():
    saved = _saved()
    store = Store()
    n = rb.rebuild(saved, store, tag="shock")
    assert n == 2 * 4                                           # 2 seeds x 4 arms
    for rid in ("real-shock-none-s0", "real-contract-s1", "real-shock-front1-s0", "real-shock-end3-s1"):
        row = store.get_run(rid)
        assert row and row.trace_cas_key and row.verified
        trace = store.get_trace(row.trace_cas_key)
        turns = [r for r in trace.records if r["ev"] == "TURN"]
        assert len(turns) == 8 and all(t["output"] for t in turns)


def test_the_replayed_state_records_equal_the_originals():
    saved = _saved()
    store = Store()
    rb.rebuild(saved, store, tag="shock")
    original = {c["seed"]: c["turns"] for c in saved["conversations"]["none"]}
    trace = store.get_trace(store.get_run("real-shock-none-s0").trace_cas_key)
    states = [r for r in trace.records if r["ev"] == "STATE"]
    assert [s["drift"] for s in states] == [t["drift"] for t in original[0]]
    assert [s["recovery_fired"] for s in states] == [t["recovery"] for t in original[0]]


def test_a_rebuild_that_does_not_reproduce_the_recording_refuses_to_write():
    saved = _saved()
    bad = copy.deepcopy(saved)
    bad["conversations"]["front1"][0]["turns"][5]["drift"] = 0.123      # a number the replay cannot reproduce
    store = Store()
    with pytest.raises(rb.FidelityError, match="front1.*seed 0.*turn 5"):
        rb.rebuild(bad, store, tag="shock")
    assert store.query_runs(limit=100) == []                            # nothing was written


def test_changed_prompts_are_caught_too():
    saved = _saved()
    bad = copy.deepcopy(saved)
    bad["conversations"]["none"][1]["turns"][2]["user"] = "a different question"
    with pytest.raises(rb.FidelityError, match="user"):
        rb.rebuild(bad, Store(), tag="shock")


def test_plain_only_ablation_files_rebuild_too():
    turns, seeds = 6, 2
    conv: dict[str, list] = {}
    for s in range(seeds):
        r = run(rm.run_naive(drifting(), s, turns, 3, Store(), placement="end", arm="abl-end3",
                             plain_only=True))
        conv.setdefault("end3", []).append({"seed": s, "turns": r.turns})
    saved = {"seeds": seeds, "turns": turns, "plain_only": True, "conversations": conv}
    store = Store()
    assert rb.rebuild(saved, store, tag="abl") == 2
    assert store.get_run("real-abl-end3-s0") and store.get_run("real-abl-end3-s1")


def test_an_unknown_arm_is_reported_not_skipped():
    saved = _saved()
    saved["conversations"]["mystery"] = saved["conversations"]["none"]
    with pytest.raises(rb.FidelityError, match="mystery"):
        rb.rebuild(saved, Store(), tag="shock")
