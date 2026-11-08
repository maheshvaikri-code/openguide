"""Drift-gated T0 steering in the proxy (ADR-003): when it turns on, that it is recorded, and that
clients cannot force it."""
import asyncio
from contextlib import contextmanager

import httpx
import numpy as np
import pytest

from benchmarks import real_model as rm
from guidancegrid.core.grid import STEER_SIGNAL, SignalPack
from guidancegrid.core.trace import steer_event
from proxy.app import create_app
from proxy.hf_upstream import HFUpstream
from proxy.registry import ContractRegistry
from proxy.steering import HARD_GAIN_LIMIT, SteeringConfig, SteerState, advance
from proxy.upstream import MockUpstream

GOOD = "Open Settings and tap Sync. [END]"
BAD = ("Here is **a long answer**:\n\n"
       "- first, open the settings menu and look for the sync option in the list\n"
       "- second, make sure you are signed in with the same account on every device you use\n"
       "- third, wait a minute for everything to update and then check again to be sure it worked well [END]")
BAND = (1, 4)


def _pack(dim=8, band=BAND):
    pack = SignalPack("m", dim)
    for layer in range(*band):
        pack.set_vector(STEER_SIGNAL, layer, np.ones(dim, dtype=np.float32))
    return pack


def _config(gain=0.05, band=BAND, **cap):
    return SteeringConfig(_pack(band=band), band, gain, **cap)


class Rig:
    """A scripted local model whose steering is recorded instead of applied."""

    def __init__(self, replies, gain=0.05, steering=True, fail_on=None, **cap):
        self.entered: list[float] = []          # gain of every steered generation, in order
        self.exited = 0
        self.calls = 0                          # every generation, steered or not
        it = iter(replies)
        outer = self

        def generate(messages, max_new):
            outer.calls += 1
            if fail_on is not None and outer.calls == fail_on + 1:
                raise RuntimeError("generation failed")
            return next(it), 5, 5

        self.up = HFUpstream(generate_fn=generate)

        @contextmanager
        def factory(g):
            outer.entered.append(g)
            try:
                yield
            finally:
                outer.exited += 1

        self.up.steer_factory = factory
        self.config = _config(gain, **cap)
        reg = ContractRegistry(measures=rm.make_measures())
        self.h = reg.register(rm.contract_dict())
        self.app = create_app(registry=reg, upstream=self.up, steering=self.config if steering else None)
        self.sid = "s"

    async def say(self, client, text="hi", headers=None, body=None, sid=None):
        h = {"X-OpenGuide-Contract": self.h, "X-OpenGuide-Session": sid or self.sid, **(headers or {})}
        payload = {"model": "m", "messages": [{"role": "user", "content": text}], **(body or {})}
        return await client.post("/v1/chat/completions", headers=h, json=payload)

    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://p")

    def trace(self, sid="s"):
        return self.app.state.governor.sessions.get(sid).reconciler.trace


def run(coro):
    return asyncio.run(coro)


# ── the configuration ─────────────────────────────────────────────────
def test_no_gain_may_pass_the_outer_limit_and_the_limit_itself_is_allowed():
    assert HARD_GAIN_LIMIT == 0.1                              # where Qwen's GSM8K collapsed (66% -> 24%)
    SteeringConfig(_pack(), BAND, HARD_GAIN_LIMIT)
    for bad in (0.1000001, 0.2, 0.4):
        with pytest.raises(ValueError, match="gain"):
            SteeringConfig(_pack(), BAND, bad)


@pytest.mark.parametrize("gain", [0, -0.05, float("nan"), float("inf")])
def test_a_gain_must_be_positive_and_finite(gain):
    with pytest.raises(ValueError, match="gain"):
        SteeringConfig(_pack(), BAND, gain)


@pytest.mark.parametrize("band", [(3, 3), (4, 1), (-1, 3)])
def test_the_band_must_be_a_real_range_of_layers(band):
    with pytest.raises(ValueError, match="band"):
        SteeringConfig(_pack(), band, 0.05)


def test_the_pack_must_have_a_direction_for_every_layer_in_the_band():
    with pytest.raises(ValueError, match="layer"):
        SteeringConfig(_pack(band=(1, 3)), (1, 4), 0.05)           # layer 3 has no vector


def test_the_pack_hash_is_the_packs_own():
    cfg = _config()
    assert cfg.pack_hash == cfg.pack.hash()


def test_a_steer_record_carries_what_was_done_to_which_turn():
    assert steer_event(3, 0.05, (10, 19), "sha256:p") == {
        "ev": "STEER", "turn": 3, "gain": 0.05, "band": [10, 19], "pack_hash": "sha256:p"}


# ── the closed loop ───────────────────────────────────────────────────
def test_steering_turns_on_after_a_correction_and_off_after_a_clean_turn():
    rig = Rig([GOOD, BAD, GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            return [(await rig.say(c)).headers.get("x-openguide-recovery") for _ in range(4)]

    actions = run(go())
    assert actions == [None, "re_anchor", None, None]
    # turn 0 clean; turn 1 not steered (drift not yet known) and corrected; turn 2 steered; turn 3 clean again
    assert rig.entered == [0.05]
    trace = rig.trace()
    steers = [r for r in trace.records if r["ev"] == "STEER"]
    assert [(r["turn"], r["gain"]) for r in steers] == [(2, 0.05)]
    assert steers[0]["band"] == list(BAND) and steers[0]["pack_hash"] == rig.config.pack_hash
    assert trace.verify()


def test_steering_stays_on_while_drift_persists():
    rig = Rig([BAD, BAD, BAD, GOOD])

    async def go():
        async with rig.client() as c:
            for _ in range(4):
                await rig.say(c)

    run(go())
    assert rig.entered == [0.05, 0.05, 0.05]                         # turns 1, 2 and 3 follow a correction
    assert [r["turn"] for r in rig.trace().records if r["ev"] == "STEER"] == [1, 2, 3]


def test_a_clean_session_is_never_steered_and_has_no_steer_records():
    rig = Rig([GOOD, GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            for _ in range(3):
                await rig.say(c)

    run(go())
    assert rig.entered == []
    assert not [r for r in rig.trace().records if r["ev"] == "STEER"]


def test_each_session_has_its_own_steering_state():
    rig = Rig([BAD, GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c, sid="a")                                # a is corrected
            await rig.say(c, sid="b")                                # another conversation: not steered
            await rig.say(c, sid="a")                                # a is steered

    run(go())
    assert rig.entered == [0.05]
    assert not [r for r in rig.trace("b").records if r["ev"] == "STEER"]


def test_without_steering_configured_nothing_is_steered_or_recorded():
    rig = Rig([BAD, BAD], steering=False)

    async def go():
        async with rig.client() as c:
            await rig.say(c)
            await rig.say(c)

    run(go())
    assert rig.entered == []
    assert not [r for r in rig.trace().records if r["ev"] == "STEER"]


def test_a_request_with_no_contract_is_passed_through_unsteered():
    rig = Rig([BAD, BAD])

    async def go():
        async with rig.client() as c:
            for _ in range(2):
                await c.post("/v1/chat/completions",
                             json={"model": "m", "messages": [{"role": "user", "content": "x"}]})

    run(go())
    assert rig.entered == []


def test_streaming_requests_are_steered_too():
    rig = Rig([BAD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c)
            r = await rig.say(c, body={"stream": True})
            assert r.status_code == 200

    run(go())
    assert rig.entered == [0.05]
    assert [r["turn"] for r in rig.trace().records if r["ev"] == "STEER"] == [1]


# ── clients cannot steer ──────────────────────────────────────────────
def test_a_client_cannot_turn_steering_on_or_raise_it():
    rig = Rig([GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c, headers={"X-OpenGuide-Steer": "1.0", "X-OpenGuide-Gain": "0.4"},
                          body={"steer": 1.0, "gain": 0.4, "openguide_steer": 1.0})
            await rig.say(c, body={"steer": 1.0})

    run(go())
    assert rig.entered == []  # the loop never fired and nothing else can


# ── refusing what can't be honoured ──────────────────────────────────
def test_steering_is_refused_for_an_upstream_that_cannot_steer():
    reg = ContractRegistry(measures=rm.make_measures())
    with pytest.raises(ValueError, match="steer"):
        create_app(registry=reg, upstream=MockUpstream(), steering=_config())
    with pytest.raises(ValueError, match="steer"):
        create_app(registry=reg, upstream=HFUpstream(generate_fn=lambda m, n: ("x", 1, 1)),
                   steering=_config())


def test_a_failed_steered_generation_still_leaves_the_hooks_off():
    rig = Rig([BAD, GOOD], fail_on=1)

    async def go():
        async with rig.client() as c:
            await rig.say(c)                                         # corrected
            with pytest.raises(RuntimeError):
                await rig.say(c)                                     # steered, and the generation fails

    run(go())
    assert rig.entered == [0.05] and rig.exited == 1                 # entered once, exited though it raised


# ── a pack must be what it claims (security review) ───────────────────
def _pack_with(vec_for_layer, dim=8, band=BAND):
    pack = SignalPack("m", dim)
    for layer in range(*band):
        pack.set_vector(STEER_SIGNAL, layer, vec_for_layer(layer))
    return pack


@pytest.mark.parametrize("bad", [
    np.array([1.0, np.nan] + [1.0] * 6, dtype=np.float32),             # not finite
    np.array([1.0, np.inf] + [1.0] * 6, dtype=np.float32),
    np.ones(5, dtype=np.float32),                                        # not the pack's hidden size
    np.ones((8, 1), dtype=np.float32),                                   # not a flat vector
    np.ones((2, 8), dtype=np.float32),
])
def test_a_band_vector_must_be_a_finite_flat_vector_of_the_packs_size(bad):
    pack = _pack_with(lambda layer: bad if layer == 2 else np.ones(8, dtype=np.float32))
    with pytest.raises(ValueError, match="layer 2"):
        SteeringConfig(pack, BAND, 0.05)


def test_a_pack_can_be_pinned_to_the_hash_the_operator_reviewed():
    pack = _pack()
    SteeringConfig(pack, BAND, 0.05, expected_pack_hash=pack.hash())
    with pytest.raises(ValueError, match="hash"):
        SteeringConfig(pack, BAND, 0.05, expected_pack_hash="sha256:" + "0" * 64)


def test_only_the_bands_layers_are_ever_steered():
    # vectors beyond the band too
    pack = _pack_with(lambda layer: np.ones(8, dtype=np.float32), band=(0, 6))
    cfg = SteeringConfig(pack, (2, 4), 0.05)
    inside = cfg.pack_in_band()
    assert [layer for layer in range(6) if inside.get(STEER_SIGNAL, layer) is not None] == [2, 3]
    assert inside.d == pack.d and inside.model_id == pack.model_id


def _stream_body():
    return {"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}


def _hdrs(rig):
    return {"x-openguide-contract": rig.h, "x-openguide-session": rig.sid}


def test_a_steered_stream_the_client_abandons_is_recorded_and_marked_unscored():
    rig = Rig([BAD, GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c)                                         # corrected: next is steered
        gen, _ = rig.app.state.governor.open_stream(_stream_body(), _hdrs(rig))
        await gen.__anext__()                                        # read one chunk ...
        await gen.aclose()                                           # ... and walk away

    run(go())
    assert rig.entered == [0.05]                                     # the model was steered and answered
    steers = [r for r in rig.trace().records if r["ev"] == "STEER"]
    assert [(r["turn"], r.get("scored")) for r in steers] == [(1, False)]   # says the turn was never scored
    assert rig.trace().verify()


def test_a_steered_reply_is_recorded_even_if_scoring_it_fails():
    rig = Rig([BAD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c)

            def boom(*a, **k):
                raise RuntimeError("scoring failed")

            rig.app.state.governor.sessions.get(rig.sid).reconciler.step = boom
            with pytest.raises(RuntimeError):
                await rig.say(c)

    run(go())
    assert [(r["turn"], r.get("scored")) for r in rig.trace().records if r["ev"] == "STEER"] == [(1, False)]


def test_a_stream_that_fails_before_producing_a_reply_records_no_steering():
    rig = Rig([BAD], fail_on=1)

    async def go():
        async with rig.client() as c:
            await rig.say(c)
        gen, _ = rig.app.state.governor.open_stream(_stream_body(), _hdrs(rig))
        with pytest.raises(RuntimeError):
            await gen.__anext__()

    run(go())
    assert not [r for r in rig.trace().records if r["ev"] == "STEER"]


def test_a_client_that_cancels_while_the_model_is_still_generating_leaves_no_claim():
    """The reply is discarded, never delivered, so there is nothing to attribute steering to."""
    import threading

    gate, started = threading.Event(), threading.Event()
    rig = Rig([BAD, GOOD])
    real = rig.up._generate

    def slow(messages, n):
        if rig.calls >= 1:                                           # the steered second generation
            started.set()
            gate.wait(5)
        return real(messages, n)

    rig.up._generate = slow

    async def go():
        async with rig.client() as c:
            await rig.say(c)
        gen, _ = rig.app.state.governor.open_stream(_stream_body(), _hdrs(rig))
        task = asyncio.ensure_future(gen.__anext__())
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.set()
        await asyncio.sleep(0.2)                                     # let the worker thread finish

    run(go())
    assert not [r for r in rig.trace().records if r["ev"] == "STEER"]
    assert rig.trace().verify()


def test_the_blocking_tool_policy_stream_path_steers_and_records_too():
    rig = Rig([BAD, GOOD])

    async def go():
        async with rig.client() as c:
            await rig.say(c)
        chunks, _ = await rig.app.state.governor.preflight_stream(_stream_body(), _hdrs(rig))
        assert chunks and chunks[-1].endswith(b"[DONE]\n\n")

    run(go())
    assert rig.entered == [0.05]
    assert [r["turn"] for r in rig.trace().records if r["ev"] == "STEER"] == [1]


# ── the opt-in cap on consecutive steered turns (docs/preregistration/t0-cap-study.md) ──
def _simulate(cfg, wants_by_turn):
    """Which turns are steered, given what the gate wants after each scored turn. Turn 0 is never steered."""
    state, steered_now, out = SteerState(), False, []
    for turn, wants in enumerate(wants_by_turn):
        gain, state = advance(cfg, state, steered_now, wants)      # decided after turn `turn`, for turn + 1
        steered_now = gain > 0
        if steered_now:
            out.append(turn + 1)
    return out


def test_with_no_cap_every_turn_after_a_correction_is_steered_as_before():
    assert _simulate(_config(), [True] * 6) == [1, 2, 3, 4, 5, 6]
    assert _simulate(_config(), [True, False, True, True, False]) == [1, 3, 4]


def test_the_cap_allows_two_in_a_row_then_pauses_three_turns():
    cfg = _config(max_consecutive=2, pause_turns=3)
    assert _simulate(cfg, [True] * 13) == [1, 2, 6, 7, 11, 12]


def test_a_clean_turn_resets_the_run_so_the_cap_only_counts_consecutive_steering():
    cfg = _config(max_consecutive=2, pause_turns=3)
    # steered, steered would hit the cap; a clean turn in between breaks the run
    assert _simulate(cfg, [True, True, False, True, True, False, True]) == [1, 2, 4, 5, 7]


def test_during_the_pause_nothing_is_steered_whatever_the_gate_wants_and_it_counts_down_per_turn():
    cfg = _config(max_consecutive=1, pause_turns=2)
    assert _simulate(cfg, [True] * 8) == [1, 4, 7]                  # one, pause 2, one, pause 2, ...


def test_a_pause_is_only_started_when_steering_was_wanted():
    cfg = _config(max_consecutive=2, pause_turns=3)
    # two steered turns, then the gate goes quiet: no pause is needed, so steering is available right away
    assert _simulate(cfg, [True, True, False, True]) == [1, 2, 4]


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "2"])
def test_the_cap_must_be_a_positive_whole_number(bad):
    with pytest.raises(ValueError, match="max_consecutive"):
        _config(max_consecutive=bad)


@pytest.mark.parametrize("bad", [0, -2, 2.5, False])
def test_the_pause_must_be_a_positive_whole_number(bad):
    with pytest.raises(ValueError, match="pause_turns"):
        _config(max_consecutive=2, pause_turns=bad)


def test_through_the_proxy_a_gate_that_never_calms_down_is_steered_in_bursts():
    rig = Rig([BAD] * 13, max_consecutive=2, pause_turns=3)

    async def go():
        async with rig.client() as c:
            for _ in range(13):
                await rig.say(c)

    run(go())
    assert [r["turn"] for r in rig.trace().records if r["ev"] == "STEER"] == [1, 2, 6, 7, 11, 12]
    assert len(rig.entered) == 6 and rig.trace().verify()


def test_without_the_cap_the_same_conversation_is_steered_on_every_turn_after_the_first():
    rig = Rig([BAD] * 6)

    async def go():
        async with rig.client() as c:
            for _ in range(6):
                await rig.say(c)

    run(go())
    assert [r["turn"] for r in rig.trace().records if r["ev"] == "STEER"] == [1, 2, 3, 4, 5]


# -- a per-model gain ceiling (a model other than Qwen needs its own evidence) --
def test_there_is_no_default_ceiling_it_comes_from_the_models_record_or_an_explicit_experiment():
    cfg = SteeringConfig(_pack(), BAND, 0.075)
    assert cfg.gain_ceiling is None                                  # nothing is assumed
    assert SteeringConfig(_pack(), BAND, 0.075, gain_ceiling=0.075).gain_ceiling == 0.075


def test_a_ceiling_can_never_exceed_the_hard_limit_or_be_non_positive():
    for bad in (0.1000001, 0.2, 0, -0.05, float("nan"), True):
        with pytest.raises(ValueError, match="gain_ceiling"):
            SteeringConfig(_pack(), BAND, 0.05, gain_ceiling=bad)


def test_the_gain_may_not_exceed_its_own_ceiling():
    with pytest.raises(ValueError, match="gain"):
        SteeringConfig(_pack(), BAND, 0.06, gain_ceiling=0.05)
    SteeringConfig(_pack(), BAND, 0.025, gain_ceiling=0.075)           # a gain below the ceiling is fine


# -- experiments are marked in the trace --------------------------------------------------------
def test_steering_under_the_experimental_override_is_marked_in_every_steer_record():
    rig = Rig([BAD, GOOD, GOOD], experimental=True, gain_ceiling=0.05)

    async def go():
        async with rig.client() as c:
            for _ in range(3):
                await rig.say(c)

    run(go())
    steers = [r for r in rig.trace().records if r["ev"] == "STEER"]
    assert steers and all(r.get("experimental") is True for r in steers)
    assert rig.trace().verify()


def test_steering_on_a_validated_setup_has_no_experimental_mark():
    rig = Rig([BAD, GOOD, GOOD])

    async def go():
        async with rig.client() as c:
            for _ in range(3):
                await rig.say(c)

    run(go())
    steers = [r for r in rig.trace().records if r["ev"] == "STEER"]
    assert steers and all("experimental" not in r for r in steers)
