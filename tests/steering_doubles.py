"""Test doubles for steering.

Production gives an upstream a steering hook only through ``HFUpstream.enable_steering``, which asks
``validation.authorise`` first; the hook and the authorisation are private to that path. Tests that need an
upstream that "can steer" without loading a real model reach into that private state here, on purpose and in
one place, so no test can quietly stand in for the real route.
"""
from proxy.validation import Authorisation


def authorisation_for(config, ceiling=None, mode=None):
    """What ``authorise`` would have returned for ``config`` (ceiling defaults to the config's own)."""
    mode = mode or ("experimental" if config.experimental else "validated")
    own = config.gain_ceiling if config.gain_ceiling is not None else config.gain
    top = ceiling if ceiling is not None else own
    return Authorisation(mode=mode, ceiling=float(top), record=None, band=tuple(config.band),
                         pack_hash=config.pack_hash)


def attach_steering(upstream, factory, config, ceiling=None, mode=None):
    """Give ``upstream`` a steering hook and the authorisation ``enable_steering`` would have granted."""
    upstream._steer_factory = factory
    upstream.steering_authorisation = authorisation_for(config, ceiling, mode)
    upstream._gain_ceiling = upstream.steering_authorisation.ceiling
    return upstream
