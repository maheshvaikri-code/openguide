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



# ── drift-gated T0 in the contract arm (ADR-003) ──────────────────────
class _Steerable:
    """The scripted model, plus the ability to be steered: it only records the gain it was asked for."""
    supports_steering = True

    def __init__(self, inner, config):
        from steering_doubles import authorisation_for

        self.inner, self.gains = inner, []
        self.steering_authorisation = authorisation_for(config)

    async def chat(self, body, headers, steer=0.0, receipt=None):
        self.gains.append(steer)
        out = await self.inner.chat(body, headers)
        if steer > 0 and receipt is not None:
            receipt.produced = True                              # a real upstream reports what it did
        return out


def _steering_config():
    import numpy as np

    from guidancegrid.core.grid import STEER_SIGNAL, SignalPack
    from proxy.steering import SteeringConfig

    pack = SignalPack("m", 8)
    for layer in (1, 2, 3):
        pack.set_vector(STEER_SIGNAL, layer, np.ones(8, dtype=np.float32))
    return SteeringConfig(pack, (1, 4), 0.05)


def test_the_contract_arm_can_steer_in_a_closed_loop_and_keeps_its_runs_apart():
    cfg = _steering_config()
    up = _Steerable(drifting_model(), cfg)
    store = Store()
    res = run(rm.run_contract(up, seed=1, turns=8, store=store, steering=cfg, arm="closedloop"))
    assert res.arm == "closedloop"
    assert store.get_run("real-closedloop-s1") is not None and store.get_run("real-contract-s1") is None
    states = [r for r in res.trace.records if r["ev"] == "STATE"]
    steered = [r["turn"] for r in res.trace.records if r["ev"] == "STEER"]
    # a turn is steered exactly when the turn before it fired a correction
    assert steered == [t for t in range(1, 8) if states[t - 1]["recovery_fired"] is not None]
    assert steered, "the scripted model drifts, so something must have been steered"
    assert [t for t, g in enumerate(up.gains) if g > 0] == steered
    assert res.trace.verify()


def test_the_contract_arm_without_steering_is_unchanged_and_never_steers():
    res = run(rm.run_contract(drifting_model(), seed=1, turns=8, store=Store()))
    assert res.arm == "contract" and res.run_id == "real-contract-s1"
    assert not [r for r in res.trace.records if r["ev"] == "STEER"]


# ── the second prompt pool (docs/preregistration/t0-generalization.md) ──
def _derivation_prompts():
    from scripts import real_t0_gate
    return list(real_t0_gate.DERIVATION_PROMPTS)


def test_the_second_pool_has_the_same_shape_and_shares_no_prompt_with_the_first_or_the_pack():
    from benchmarks import prompts_v2 as v2

    assert len(v2.PLAIN_V2) == 24 and len(v2.TEMPTING_V2) == 16
    allv2 = v2.PLAIN_V2 + v2.TEMPTING_V2
    assert len(set(allv2)) == 40                                       # no duplicates
    assert not set(allv2) & set(rm.POOL)                               # nothing from the first pool
    assert not set(allv2) & set(_derivation_prompts())                 # nor anything the pack was derived on
    lower = [p.lower() for p in allv2]
    assert len(set(lower)) == 40


def test_every_prompt_of_the_second_pool_is_classified_by_what_it_asks_for():
    from benchmarks import prompts_v2 as v2

    assert all(rm.kind_of(p) == "plain" for p in v2.PLAIN_V2)
    assert all(rm.kind_of(p) == "tempting" for p in v2.TEMPTING_V2)
    assert all(rm.kind_of(p) == "tempting" for p in rm._TEMPTING)      # the first pool is unchanged
    assert all(rm.kind_of(p) == "plain" for p in rm._PLAIN)


def test_conversations_from_the_second_pool_use_only_it_and_keep_the_shock_turns():
    from benchmarks import prompts_v2 as v2

    turns = rm.user_turns(300, 16, shocks=(4, 10), pool="v2")
    assert set(turns) <= set(v2.PLAIN_V2 + v2.TEMPTING_V2)
    assert [rm.kind_of(t) for t in turns].count("tempting") == 2
    assert rm.kind_of(turns[4]) == "tempting" and rm.kind_of(turns[10]) == "tempting"
    assert turns == rm.user_turns(300, 16, shocks=(4, 10), pool="v2")      # deterministic
    assert turns != rm.user_turns(301, 16, shocks=(4, 10), pool="v2")


def test_the_default_pool_is_bit_identical_to_before_the_option_existed():
    import hashlib
    import json

    def h(seed):
        return hashlib.sha256(json.dumps(rm.user_turns(seed, 16, False, (4, 10))).encode()).hexdigest()[:16]

    assert (h(0), h(7), h(100)) == ("04948443bcbb5c61", "a9c0fd5c57c1da4b", "87bfa7a74912aa80")
    assert rm.user_turns(0, 16, False, (4, 10)) == rm.user_turns(0, 16, False, (4, 10), pool="v1")


def test_an_unknown_pool_is_an_error():
    with pytest.raises(ValueError, match="pool"):
        rm.user_turns(1, 16, shocks=(4, 10), pool="v3")


def test_the_contract_arm_can_run_on_the_second_pool():
    from benchmarks import prompts_v2 as v2

    res = run(rm.run_contract(drifting_model(), seed=300, turns=8, store=Store(), shocks=(3,), pool="v2"))
    assert all(t["user"] in set(v2.PLAIN_V2 + v2.TEMPTING_V2) for t in res.turns)
    assert res.turns[3]["kind"] == "tempting"


def test_a_run_carries_the_label_of_the_model_it_used_and_defaults_to_qwen():
    other = run(rm.run_contract(drifting_model(), seed=1, turns=4, store=Store(),
                                model_id="local:other-model"))
    assert other.trace.manifest["model"] == "local:other-model"
    default = run(rm.run_contract(drifting_model(), seed=1, turns=4, store=Store()))
    assert default.trace.manifest["model"] == rm.MODEL_ID
