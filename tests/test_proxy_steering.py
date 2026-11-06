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
from proxy.steering import MAX_SAFE_GAIN, SteeringConfig
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


def _config(gain=0.05, band=BAND):
    return SteeringConfig(_pack(band=band), band, gain)


class Rig:
    """A scripted local model whose steering is recorded instead of applied."""

    def __init__(self, replies, gain=0.05, steering=True, fail_on=None):
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
        self.config = _config(gain)
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
def test_the_gain_is_capped_at_the_measured_usable_ceiling():
    assert MAX_SAFE_GAIN == 0.1
    SteeringConfig(_pack(), BAND, MAX_SAFE_GAIN)                     # the ceiling itself is allowed
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
