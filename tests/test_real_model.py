"""Real-model experiment harness, tested offline with a scripted model that drifts the way a real
one does: it follows the rules until the conversation has gone on a while, and a re-anchor in the
request restores it."""
import asyncio

import pytest

from benchmarks import real_model as rm
from guidancegrid.store import Store
from proxy.upstream import MockUpstream


# ── the sensors ───────────────────────────────────────────────────────
def words(n, tail=" [END]"):
    return " ".join(["word"] * n) + tail


@pytest.mark.parametrize("text,expected", [
    (words(40), True), (words(41), False), (words(5), True),
    ("short [END]  \n", True),                          # trailing whitespace is fine
    ("", True),
])
def test_brevity(text, expected):
    assert rm.check(text)["brevity"] is expected


@pytest.mark.parametrize("text,expected", [
    ("Click Settings then Reset. [END]", True),
    ("**Bold** answer [END]", False),
    ("Steps:\n- one\n- two [END]", False),
    ("Steps:\n1. one\n2. two [END]", False),
    ("* item [END]", False),
    ("# Heading\ntext [END]", False),
    ("```code``` [END]", False),
    ("It costs 5 - 10 dollars. [END]", True),          # a hyphen mid-sentence is not a list
    ("Version 2.0 is out. [END]", True),               # a number with a dot is not a list
])
def test_plain_text(text, expected):
    assert rm.check(text)["plain_text"] is expected


@pytest.mark.parametrize("text,expected", [
    ("done [END]", True), ("done [END]\n", True), ("done", False),
    ("[END] done", False), ("done [end]", False), ("done [END] extra", False),
])
def test_sign_off(text, expected):
    assert rm.check(text)["sign_off"] is expected


def test_measures_are_registered_under_the_contract_refs():
    reg = rm.make_measures()
    ctx = {"output": "ok [END]"}
    for ref in ("structural:brevity", "structural:plain_text", "structural:sign_off"):
        assert reg.read(ref, ctx).value == 1.0
    assert reg.read("structural:sign_off", {"output": "nope"}).value == 0.0


def test_the_contract_loads_and_its_rules_are_what_is_restated_to_the_model():
    cc = rm.compiled_contract()
    frag = cc.t2_fragments["anchor"]
    for rule in ("at most 40 words", "no markdown", "[END]"):
        assert rule in frag


# ── the conversation ──────────────────────────────────────────────────
def test_user_turns_are_deterministic_per_seed_and_differ_across_seeds():
    assert rm.user_turns(3, 30) == rm.user_turns(3, 30)
    assert rm.user_turns(3, 30) != rm.user_turns(4, 30)
    assert len(rm.user_turns(0, 30)) == 30
    assert len(set(rm.user_turns(0, 30))) == 30                  # no repeats within a conversation


# ── the arms, against a scripted drifting model ───────────────────────
def _carries_anchor(call):
    return any("[contract:anchor]" in m["content"] for m in call["messages"] if m["role"] == "system")


def drifting_model(drift_from=3):
    """Compliant for the first turns; then ignores the rules unless a re-anchor is in the request."""
    def respond(body):
        msgs = body["messages"]
        user_turns = sum(1 for m in msgs if m["role"] == "user")
        anchored = any("[contract:anchor]" in m["content"] for m in msgs if m["role"] == "system")
        if user_turns <= drift_from or anchored:
            return "Sure, here is the answer. [END]"
        return "**Here** is a long answer without the sign-off"
    return MockUpstream(respond)


def run(coro):
    return asyncio.run(coro)


def test_unmanaged_arm_drifts_and_is_observed_but_never_corrected():
    store = Store()
    res = run(rm.run_none(drifting_model(), seed=1, turns=8, store=store))
    assert [t["ok"] for t in res.turns] == [True, True, True] + [False] * 5
    assert res.reanchor_turns == []                          # observe only
    # the trace must not claim corrections nobody applied, yet must record that drift crossed the threshold
    assert all(t["recovery"] is None for t in res.turns)
    assert max(t["drift"] for t in res.turns) > 0.1
    assert res.trace.verify()
    assert store.get_run("real-none-s1").verified is True
    assert store.get_run("real-none-s1").trace_cas_key        # a full trace is stored for replay


def test_naive_arm_restates_on_a_fixed_cadence_whatever_the_state():
    store = Store()
    up = drifting_model()
    res = run(rm.run_naive(up, seed=1, turns=10, every=4, store=store))
    assert res.reanchor_turns == [4, 8]                      # prepared at these turns...
    sent = [i for i, c in enumerate(up.calls) if _carries_anchor(c)]
    assert sent == [5, 9]    # ...and sent with the NEXT request, as the proxy does
    assert all(t["recovery"] is None for t in res.turns)     # nothing is "corrected" on a fixed cadence
    assert res.trace.verify() and store.get_run("real-naive-s1")


def test_contract_arm_goes_through_the_proxy_and_corrects_after_the_first_violation():
    store = Store()
    res = run(rm.run_contract(drifting_model(), seed=1, turns=10, store=store))
    oks = [t["ok"] for t in res.turns]
    assert oks[:3] == [True, True, True]
    assert oks[3] is False                                   # first violation, seen by the sensor
    assert oks[4] is True                                    # the re-anchor fed forward and restored it
    assert 3 in res.corrections and res.reanchor_turns       # recorded by the real reconciler
    assert res.trace.verify()
    run_row = store.get_run("real-contract-s1")              # persisted by the proxy itself
    assert run_row.recoveries >= 1 and run_row.trace_cas_key and run_row.verified


def test_contract_arm_beats_the_unmanaged_arm_on_this_scripted_model():
    store = Store()
    none = run(rm.run_none(drifting_model(), seed=2, turns=12, store=Store()))
    gov = run(rm.run_contract(drifting_model(), seed=2, turns=12, store=store))
    assert gov.compliance() > none.compliance()


def test_matched_cadence_follows_the_contract_arms_reanchor_count():
    assert rm.matched_every(turns=30, n_reanchors=6) == 5
    assert rm.matched_every(turns=30, n_reanchors=0) == 30   # no re-anchors: effectively never
    assert rm.matched_every(turns=30, n_reanchors=100) == 1


def test_summary_reports_rates_and_never_divides_by_zero():
    store = Store()
    results = [run(rm.run_none(drifting_model(), seed=s, turns=6, store=store)) for s in (1, 2)]
    summary = rm.summarize({"none": results, "naive": []})
    assert summary["none"]["conversations"] == 2 and summary["none"]["turns"] == 12
    assert 0.0 <= summary["none"]["compliance"] <= 1.0
    assert set(summary["none"]["by_rule"]) == {"brevity", "plain_text", "sign_off"}
    assert summary["naive"]["conversations"] == 0 and summary["naive"]["compliance"] is None


def test_turns_are_labelled_plain_or_tempting_and_summarised_by_kind():
    assert rm.kind_of(rm._PLAIN[0]) == "plain"
    assert rm.kind_of(rm._TEMPTING[0]) == "tempting"
    res = run(rm.run_none(drifting_model(), seed=1, turns=10, store=Store()))
    assert {t["kind"] for t in res.turns} <= {"plain", "tempting"}
    by_kind = rm.summarize({"none": [res]})["none"]["by_kind"]
    assert set(by_kind) == {"plain", "tempting"}
    for v in by_kind.values():
        assert v is None or 0.0 <= v <= 1.0


def test_an_arm_label_names_the_run_so_variants_never_overwrite_each_other():
    store = Store()
    a = run(rm.run_none(drifting_model(), seed=1, turns=4, store=store, arm="t0-g0.4"))
    b = run(rm.run_none(drifting_model(), seed=1, turns=4, store=store))
    assert a.run_id == "real-t0-g0.4-s1" and b.run_id == "real-none-s1"
    assert store.get_run("real-t0-g0.4-s1") and store.get_run("real-none-s1")
    assert a.trace.manifest["arm"] == "t0-g0.4"


def test_plain_only_conversations_contain_no_tempting_prompts():
    turns = rm.user_turns(3, 12, plain_only=True)
    assert len(turns) == 12 and len(set(turns)) == 12
    assert all(rm.kind_of(u) == "plain" for u in turns)
    assert rm.user_turns(3, 12, plain_only=True) == rm.user_turns(3, 12, plain_only=True)


def _system_positions(call):
    msgs = call["messages"]
    return [i for i, m in enumerate(msgs) if m["role"] == "system" and "[contract:anchor]" in m["content"]]


def test_front_placement_puts_the_restatement_first_and_end_placement_just_before_the_user_turn():
    front, end = drifting_model(), drifting_model()
    run(rm.run_naive(front, seed=1, turns=7, every=3, store=Store(), placement="front"))
    run(rm.run_naive(end, seed=1, turns=7, every=3, store=Store(), placement="end", arm="naive-end"))
    carried = [i for i, c in enumerate(front.calls) if _system_positions(c)]
    # prepared at turn 3 and sent with turn 4; the one prepared at turn 6 has no next turn to ride on
    assert carried == [4]
    for i in carried:
        assert _system_positions(front.calls[i]) == [0]
    for i, c in enumerate(end.calls):
        for pos in _system_positions(c):
            assert pos == len(c["messages"]) - 2             # right before the latest user message
            assert c["messages"][-1]["role"] == "user"
    assert any(_system_positions(c) for c in end.calls)


def test_an_unknown_placement_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="placement"):
        run(rm.run_naive(drifting_model(), seed=1, turns=3, every=2, store=Store(), placement="middle"))


def test_shocks_place_tempting_prompts_at_the_given_turns_and_plain_ones_everywhere_else():
    turns = rm.user_turns(2, 16, shocks=(4, 10))
    assert len(turns) == 16 and len(set(turns)) == 16
    assert [i for i, u in enumerate(turns) if rm.kind_of(u) == "tempting"] == [4, 10]
    assert turns == rm.user_turns(2, 16, shocks=(4, 10))                 # deterministic
    assert turns != rm.user_turns(3, 16, shocks=(4, 10))


def test_shocks_outside_the_conversation_are_rejected():
    import pytest

    with pytest.raises(ValueError, match="shock"):
        rm.user_turns(1, 10, shocks=(10,))
    with pytest.raises(ValueError, match="shock"):
        rm.user_turns(1, 10, shocks=(-1,))


def test_recovery_is_compliance_on_plain_turns_after_the_first_tempting_one():
    def res(kinds_oks):
        turns = [{"turn": i, "kind": k, "ok": ok, "checks": dict.fromkeys(rm.RULES, ok), "drift": 0.0,
                  "recovery": None, "reanchored": False} for i, (k, ok) in enumerate(kinds_oks)]
        return rm.ArmResult("x", 0, "x", None, "t2", turns)

    r = res([("plain", True), ("tempting", False), ("plain", False), ("plain", True), ("tempting", False),
             ("plain", True)])
    # plain turns after the first tempting one (turn 1): turns 2, 3, 5 -> False, True, True
    assert rm.summarize({"x": [r]})["x"]["recovery"] == pytest.approx(2 / 3)
    assert rm.summarize({"x": [res([("plain", True), ("plain", True)])]})["x"]["recovery"] is None
    assert rm.summarize({"x": []})["x"]["recovery"] is None


def test_the_contract_arm_accepts_the_same_shocks():
    res = run(rm.run_contract(drifting_model(), seed=1, turns=8, store=Store(), shocks=(3,)))
    assert [t["kind"] for t in res.turns].count("tempting") == 1 and res.turns[3]["kind"] == "tempting"


def _turn_events(trace):
    return [r for r in trace.records if r["ev"] == "TURN"]


def test_every_arm_records_what_was_said_in_the_trace():
    for arm_run in (
        lambda: rm.run_none(drifting_model(), seed=1, turns=6, store=Store()),
        lambda: rm.run_naive(drifting_model(), seed=1, turns=6, every=2, store=Store()),
        lambda: rm.run_contract(drifting_model(), seed=1, turns=6, store=Store()),
    ):
        res = run(arm_run())
        turns = _turn_events(res.trace)
        assert [t["turn"] for t in turns] == list(range(6))
        assert [t["user"] for t in turns] == [t["user"] for t in res.turns]
        assert [t["output"] for t in turns] == [t["reply"] for t in res.turns]
        assert res.trace.verify()                              # the captured text is inside the chain


def test_the_restatement_actually_sent_is_what_the_trace_says_was_sent():
    up = drifting_model()
    res = run(rm.run_naive(up, seed=1, turns=7, every=3, store=Store(), placement="end", arm="naive-end"))
    sent = {t["turn"]: t["restated"] for t in _turn_events(res.trace)}
    assert sent[0] is None and sent[3] is None                 # prepared at 3, sent with 4
    assert sent[4] and "[contract:anchor]" in sent[4]
    assert [i for i, c in enumerate(up.calls) if _carries_anchor(c)] == [4]


def test_the_unmanaged_arm_never_records_a_restatement():
    res = run(rm.run_none(drifting_model(), seed=1, turns=6, store=Store()))
    assert all(t["restated"] is None for t in _turn_events(res.trace))

