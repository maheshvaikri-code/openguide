"""Steering fails closed: a model with no validation record of its own is refused.

What worked on one model did not carry to another. The Qwen2.5-1.5B recipe, at the same *relative* gains, cost
Granite-3.1-2B 6 to 42 points of GSM8K (benchmarks/REPORT.md 7.7). So steering is only allowed on weights that
have a record here, citing the evidence, and only inside what that evidence covered (band, pack, gain
ceiling).
Anything else is an experiment, which must be asked for explicitly in code
(``SteeringConfig(experimental=True, gain_ceiling=...)``). It is never a server or environment setting, and
every steered turn under it is marked in the trace.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping


class NotValidated(ValueError):
    """Steering was asked for on a model, or a setup, that has no evidence behind it."""


@dataclass(frozen=True)
class ValidationRecord:
    key: str                                    # human name of the model
    weights_sha256: str                         # identity of the weights (see weights_identity)
    band: tuple[int, int]                       # the layers the evidence covers
    gain_ceiling: float                         # the highest gain the evidence supports
    pack_hash: str                              # the steering pack the evidence used
    evidence: tuple[tuple[str, str], ...]       # (results file, the commit that holds it)


@dataclass(frozen=True)
class Authorisation:
    mode: str                                   # "validated" | "experimental"
    ceiling: float
    record: ValidationRecord | None


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_cache: dict[tuple[str, int, int], str] = {}


def weights_identity(path: str) -> str:
    """SHA-256 over the sorted ``name:sha256`` of every ``*.safetensors`` file in a directory.

    It identifies the weights themselves, wherever they live; a revision label or a folder name would not (the
    Qwen copy has no recorded revision, so its hash is its only pin)."""
    names = sorted(n for n in os.listdir(path) if n.endswith(".safetensors"))
    if not names:
        raise ValueError(f"no .safetensors weight files in {path!r}, so the model cannot be identified")
    parts = []
    for n in names:
        full = os.path.join(path, n)
        st = os.stat(full)
        key = (os.path.abspath(full), st.st_size, int(st.st_mtime))
        if key not in _cache:
            _cache[key] = _file_sha256(full)
        parts.append(f"{n}:{_cache[key]}\n")
    return hashlib.sha256("".join(parts).encode()).hexdigest()


# The only model with evidence: three pre-registered studies (REPORT 7.4-7.6), each with a committed
# results file.
RECORDS: dict[str, ValidationRecord] = {
    "52509745a0868b55d0c13a2f0cf1bc8dac823df7cee3fdd6e114c91fa511b18e": ValidationRecord(
        key="qwen2.5-1.5b-instruct",
        weights_sha256="52509745a0868b55d0c13a2f0cf1bc8dac823df7cee3fdd6e114c91fa511b18e",
        band=(10, 19),
        gain_ceiling=0.05,
        pack_hash="sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f",
        evidence=(
            ("benchmarks/results/qwen2.5-1.5b/replication_t0.json", "289ee73"),
            ("benchmarks/results/qwen2.5-1.5b/replication_cap.json", "ad1183c"),
            ("benchmarks/results/qwen2.5-1.5b/replication_pool2.json", "827f6d2"),
        )),
}


def authorise(weights_path: str | None, config: Any,
              records: Mapping[str, ValidationRecord] | None = None) -> Authorisation:
    """Decide whether ``config`` may steer the model whose weights are at ``weights_path``.

    Raises NotValidated if there is no evidence for this model or this setup."""
    recs = RECORDS if records is None else records
    if config.experimental:
        if config.gain_ceiling is None:
            raise ValueError("experimental steering needs an explicit gain_ceiling "
                             "(there is no validated one to use)")
        return Authorisation("experimental", float(config.gain_ceiling), None)

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
    if tuple(config.band) != tuple(rec.band):
        raise NotValidated(f"the validated band for {rec.key} is {rec.band}, not {tuple(config.band)}")
    if config.pack_hash != rec.pack_hash:
        raise NotValidated(f"the validated steering pack for {rec.key} is {rec.pack_hash}, "
                           f"not {config.pack_hash}")
    if config.gain_ceiling is not None and config.gain_ceiling > rec.gain_ceiling:
        raise NotValidated(f"gain_ceiling {config.gain_ceiling} is above the validated ceiling "
                           f"{rec.gain_ceiling} for {rec.key}")
    ceiling = rec.gain_ceiling if config.gain_ceiling is None else float(config.gain_ceiling)
    if config.gain > ceiling:
        raise NotValidated(f"gain {config.gain} is above the validated ceiling {ceiling} for {rec.key}")
    return Authorisation("validated", ceiling, rec)
