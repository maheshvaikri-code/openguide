"""Exploratory diagnostics for why a steering recipe that worked on one model hurt another (REPORT 7.7).

Two questions, both cheap:

* Is it the *direction* or just the *size* of the push? A control pack with random directions but the same
  per-layer norms answers it (``random_direction_pack``).
* Is the push large relative to what a layer normally writes? ``layer_write_stats`` measures, per decoder
  layer, the median over tokens of ||output - input|| / ||input||, and ``push_to_write`` compares the
  steering push to it.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from guidancegrid.core.field import gaussian_envelope
from guidancegrid.core.grid import STEER_SIGNAL, SignalPack


def random_direction_pack(pack: SignalPack, band: tuple[int, int], seed: int) -> SignalPack:
    """Same layers and per-layer norms as ``pack``, but each vector points in a random direction (seeded)."""
    rng = np.random.default_rng(seed)
    out = SignalPack(pack.model_id, pack.d)
    for layer in range(*band):
        norm = float(np.linalg.norm(np.asarray(pack.get(STEER_SIGNAL, layer), dtype=np.float64)))
        v = rng.standard_normal(pack.d)
        out.set_vector(STEER_SIGNAL, layer, (v / np.linalg.norm(v) * norm).astype(np.float32))
    return out


def token_write_ratios(inp: Any, out: Any) -> np.ndarray:
    """Per token: the layer's change relative to its input, ||out - in|| / ||in||. Shapes (T, d)."""
    a = np.asarray(inp, dtype=np.float64)
    b = np.asarray(out, dtype=np.float64)
    return np.linalg.norm(b - a, axis=-1) / np.maximum(np.linalg.norm(a, axis=-1), 1e-12)


def layer_write_stats(model: Any, input_ids: Any, skip_first: bool = False) -> dict[int, dict[str, float]]:
    """Per decoder layer, on one fixed sequence: the median over tokens of the write ratio and input norm.

    Hooks are always removed. ``skip_first`` drops the first token (often an attention sink)."""
    import torch

    from guidancegrid.channels.t0_activation import decoder_layers

    layers = decoder_layers(model)
    seen_in: dict[int, Any] = {}
    seen_out: dict[int, Any] = {}
    handles = []
    for i, layer in enumerate(layers):
        def pre(mod, args, kwargs, i=i):
            seen_in[i] = (args[0] if args else kwargs["hidden_states"]).detach().float().cpu()

        def post(mod, args, kwargs, output, i=i):
            seen_out[i] = (output[0] if isinstance(output, tuple) else output).detach().float().cpu()

        handles.append(layer.register_forward_pre_hook(pre, with_kwargs=True))
        handles.append(layer.register_forward_hook(post, with_kwargs=True))
    try:
        with torch.no_grad():
            model(input_ids=input_ids.to(next(model.parameters()).device))
    finally:
        for h in handles:
            h.remove()
    stats = {}
    for i in range(len(layers)):
        a, b = seen_in[i][0].numpy(), seen_out[i][0].numpy()
        if skip_first:
            a, b = a[1:], b[1:]
        stats[i] = {"median_write_ratio": float(np.median(token_write_ratios(a, b))),
                    "median_input_norm": float(np.median(np.linalg.norm(a, axis=-1)))}
    return stats


def envelope(band: tuple[int, int], n_layers: int) -> np.ndarray:
    """The steering gain envelope across layers, exactly as ``steering_context`` builds it."""
    return np.asarray(gaussian_envelope(band[0], band[1] - 1, n_layers), dtype=np.float64)


def push_to_write(gain: float, band: tuple[int, int], n_layers: int, pack_norms: dict[int, float],
                  stats: dict[int, dict[str, float]]) -> dict[int, float]:
    """For each band layer: the steering push relative to the state, over what that layer normally writes.

    The push at a layer is ``gain * envelope * ||pack vector||`` and is measured against the layer's input
    norm, so ``push / ||input||`` is the fraction of the state it moves; dividing by the write ratio expresses
    it in units of "one typical layer's update". Above 1 means the steering moves the state more than the
    layer itself does."""
    env = envelope(band, n_layers)
    out = {}
    for layer in range(*band):
        push = gain * env[layer] * pack_norms[layer] / stats[layer]["median_input_norm"]
        out[layer] = float(push / stats[layer]["median_write_ratio"])
    return out
