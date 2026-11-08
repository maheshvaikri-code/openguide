"""Where steering is applied and recorded, not only where it is enabled (review of the fail-closed guard)."""
import inspect
from contextlib import contextmanager, nullcontext

import numpy as np
import pytest
from steering_doubles import attach_steering

from guidancegrid.core.grid import STEER_SIGNAL, SignalPack
from proxy.app import create_app
from proxy.hf_upstream import HFUpstream
from proxy.steering import SteeringConfig

BAND = (1, 4)


def _pack(dim=8):
    p = SignalPack("m", dim)
    for layer in range(*BAND):
        p.set_vector(STEER_SIGNAL, layer, np.ones(dim, dtype=np.float32))
    return p


@contextmanager
def _factory(gain):
    yield


def _up():
    return HFUpstream(generate_fn=lambda m, n: ("x", 1, 1))


def test_the_steering_hook_has_no_public_name_and_enable_steering_takes_no_records():
    up = _up()
    assert not hasattr(up, "steer_factory")
    assert list(inspect.signature(HFUpstream.enable_steering).parameters) == ["self", "config"]


def test_a_hook_that_never_went_through_authorisation_is_not_steering_support():
    up = _up()
    up._steer_factory = lambda g: nullcontext()                 # poked in privately, no authorisation
    assert up.supports_steering is False
    with pytest.raises(ValueError, match="authoris"):
        create_app(upstream=up, steering=SteeringConfig(_pack(), BAND, 0.05))


def test_an_unauthorised_upstream_refuses_to_steer_even_when_asked_directly():
    import asyncio

    up = _up()
    up._steer_factory = lambda g: nullcontext()
    up._gain_ceiling = 0.1                                       # even with a permissive ceiling poked in
    with pytest.raises(ValueError, match="authoris"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05))


def test_a_fresh_upstream_has_a_closed_ceiling():
    assert _up()._gain_ceiling == 0.0


@pytest.mark.parametrize("what,make", [
    ("pack", lambda: SteeringConfig(_pack(dim=9), BAND, 0.03)),
    ("band", lambda: SteeringConfig(_pack(), (1, 3), 0.03)),
    ("gain", lambda: SteeringConfig(_pack(), BAND, 0.06)),
    ("experimental", lambda: SteeringConfig(_pack(), BAND, 0.03, experimental=True, gain_ceiling=0.05)),
])
def test_the_governor_refuses_a_config_the_authorisation_does_not_cover(what, make):
    up = attach_steering(_up(), _factory, SteeringConfig(_pack(), BAND, 0.05))
    with pytest.raises(ValueError, match=what):
        create_app(upstream=up, steering=make())


def test_the_governor_accepts_a_config_inside_what_was_authorised():
    up = attach_steering(_up(), _factory, SteeringConfig(_pack(), BAND, 0.05))
    create_app(upstream=up, steering=SteeringConfig(_pack(), BAND, 0.02))      # lower gain, same band, pack


def test_only_a_steering_config_object_is_accepted_by_the_governor():
    up = attach_steering(_up(), _factory, SteeringConfig(_pack(), BAND, 0.05))
    with pytest.raises(TypeError, match="SteeringConfig"):
        create_app(upstream=up, steering=object())
