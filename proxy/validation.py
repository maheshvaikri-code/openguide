"""Steering fails closed: a model with no validation record of its own is refused.

What worked on one model did not carry to another. The Qwen2.5-1.5B recipe, at the same *relative* gains, cost
Granite-3.1-2B 6 to 42 points of GSM8K (benchmarks/REPORT.md 7.7). So steering is only allowed on weights that
have a record here, citing the evidence, and only inside what that evidence covered (band, pack, dtype, gain
ceiling). Anything else is an experiment, which must be asked for explicitly in code
(``SteeringConfig(experimental=True, gain_ceiling=...)``). It is never a server or environment setting, and
every steered turn under it is marked in the trace.

How it is enforced: ``HFUpstream.enable_steering`` calls ``authorise`` and keeps the resulting
``Authorisation`` on the upstream. The upstream refuses to steer without one, the Governor refuses a config
the authorisation does not cover, and the trace's ``experimental`` mark comes from the authorisation. This is
a guard against operator error, not a defence against code that can already edit the process.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping

from .steering import SteeringConfig


class NotValidated(ValueError):
    """Steering was asked for on a model, or a setup, that has no evidence behind it."""


@dataclass(frozen=True)
class ValidationRecord:
    key: str                                    # human name of the model
    weights_sha256: str                         # identity of the model files (see weights_identity)
    band: tuple[int, int]                       # the layers the evidence covers
    gain_ceiling: float                         # the highest gain the evidence supports
    pack_hash: str                              # the steering pack the evidence used
    evidence: tuple[tuple[str, str], ...]       # (results file, the commit that holds it)
    dtype: str | None = None                    # the numeric type the evidence was run in (None: not pinned)


@dataclass(frozen=True)
class Authorisation:
    """What ``authorise`` allowed. Kept on the upstream; the Governor checks its config against it."""
    mode: str                                   # "validated" | "experimental"
    ceiling: float
    record: ValidationRecord | None
    band: tuple[int, int]
    pack_hash: str

    def not_covered_reason(self, config: SteeringConfig) -> str | None:
        """Why ``config`` is not what was authorised, or None if it is covered."""
        if tuple(config.band) != tuple(self.band):
            return f"its band {tuple(config.band)} differs from the authorised {tuple(self.band)}"
        if config.pack_hash != self.pack_hash:
            return "its steering pack is not the one that was authorised"
        if config.experimental != (self.mode == "experimental"):
            return (f"its experimental flag ({config.experimental}) differs from the authorisation "
                    f"({self.mode})")
        if config.gain > self.ceiling:
            return f"its gain {config.gain} is above the authorised ceiling {self.ceiling}"
        return None


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def weights_identity(path: str) -> str:
    """SHA-256 over the sorted ``name:sha256`` of each ``*.safetensors`` file, then ``config.json``.

    It identifies the model files themselves, wherever they live; a revision label or a folder name would not
    (the Qwen copy has no recorded revision, so its hash is its only pin). The architecture config is included
    because a changed config (rope scaling and the like) changes what the same weights compute. Nothing is
    cached: the files are hashed each time, which takes seconds."""
    try:
        names = sorted(n for n in os.listdir(path) if n.endswith(".safetensors"))
    except OSError as e:
        raise NotValidated(
            f"cannot read model weights at {path!r} ({type(e).__name__}): steering needs a local directory "
            f"of .safetensors files so the model can be identified (a hub id or a single file cannot be). "
            f"Download the model to a directory, or pass experimental=True to experiment.") from e
    if not names:
        raise NotValidated(f"no .safetensors weight files in {path!r}, so the model cannot be identified")
    parts = [f"{n}:{_file_sha256(os.path.join(path, n))}\n" for n in names]
    cfg = os.path.join(path, "config.json")
    if os.path.isfile(cfg):
        parts.append(f"config.json:{_file_sha256(cfg)}\n")
    return hashlib.sha256("".join(parts).encode()).hexdigest()


# The only model with evidence: three pre-registered studies (REPORT 7.4-7.6), each with a committed
# results file.
RECORDS: dict[str, ValidationRecord] = {
    "5e5459042d56fb2c9c53ee4d813fe124cbb1dcbdc0241d3fbe4b4e8a701d67aa": ValidationRecord(
        key="qwen2.5-1.5b-instruct",
        weights_sha256="5e5459042d56fb2c9c53ee4d813fe124cbb1dcbdc0241d3fbe4b4e8a701d67aa",
        band=(10, 19),
        gain_ceiling=0.05,
        pack_hash="sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f",
        dtype="float16",
        evidence=(
            ("benchmarks/results/qwen2.5-1.5b/replication_t0.json", "289ee73"),
            ("benchmarks/results/qwen2.5-1.5b/replication_cap.json", "ad1183c"),
            ("benchmarks/results/qwen2.5-1.5b/replication_pool2.json", "827f6d2"),
        )),
}


def authorise(weights_path: str | None, config: Any,
              records: Mapping[str, ValidationRecord] | None = None, *, dtype: str | None = None,
              loaded_from: str | None = None, check_loaded: bool = False) -> Authorisation:
    """Decide whether ``config`` may steer the model whose weights are at ``weights_path``.

    ``dtype`` is the numeric type the model is loaded in. With ``check_loaded`` the model must also report
    that it was loaded from ``weights_path`` (``loaded_from``), so the files hashed are the files in memory.
    Raises NotValidated if there is no evidence for this model or this setup."""
    if not isinstance(config, SteeringConfig):
        raise TypeError(f"config must be a SteeringConfig, got {type(config).__name__}")
    recs = RECORDS if records is None else records
    band, pack_hash = tuple(config.band), config.pack_hash
    if config.experimental:
        if config.gain_ceiling is None:
            raise ValueError("experimental steering needs an explicit gain_ceiling "
                             "(there is no validated one to use)")
        return Authorisation("experimental", float(config.gain_ceiling), None, band, pack_hash)

    if weights_path is None:
        raise NotValidated("cannot identify the model's weights (no weights path), so no validation "
                           "record can apply; load it with HFUpstream.from_pretrained, or pass "
                           "experimental=True to experiment")
    identity = weights_identity(weights_path)
    rec = recs.get(identity)
    if rec is None:
        raise NotValidated(
            f"no validation record for these weights (sha256 {identity[:16]}...), so steering is refused. "
            f"Steering has been validated on one model only, and the same recipe degraded another "
            f"(benchmarks/REPORT.md 7.7). This model needs its own evidence: a pre-registered pilot and "
            f"replication. To experiment, build the SteeringConfig with experimental=True and an explicit "
            f"gain_ceiling; those turns are marked experimental in the trace.")
    if check_loaded:
        if not loaded_from or os.path.abspath(loaded_from) != os.path.abspath(weights_path):
            raise NotValidated(f"cannot confirm the loaded model came from {weights_path!r} (it reports "
                               f"{loaded_from!r}), so the hashed files may not be the ones in use")
    if rec.dtype is not None and dtype != rec.dtype:
        raise NotValidated(f"{rec.key} was validated in {rec.dtype}, but this model is loaded as {dtype}")
    if band != tuple(rec.band):
        raise NotValidated(f"the validated band for {rec.key} is {rec.band}, not {band}")
    if pack_hash != rec.pack_hash:
        raise NotValidated(f"the validated steering pack for {rec.key} is {rec.pack_hash}, not {pack_hash}")
    if config.gain_ceiling is not None and config.gain_ceiling > rec.gain_ceiling:
        raise NotValidated(f"gain_ceiling {config.gain_ceiling} is above the validated ceiling "
                           f"{rec.gain_ceiling} for {rec.key}")
    ceiling = rec.gain_ceiling if config.gain_ceiling is None else float(config.gain_ceiling)
    if config.gain > ceiling:
        raise NotValidated(f"gain {config.gain} is above the validated ceiling {ceiling} for {rec.key}")
    return Authorisation("validated", ceiling, rec, band, pack_hash)
