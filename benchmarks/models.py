"""Model profiles for the real-model experiments: where a model lives, how it is loaded, its steering band.

The first model (Qwen2.5-1.5B-Instruct) is the setup every earlier result used. A second model gets its
band by mapping Qwen's *relative* position (layers 10-18 of 28) onto its own depth, so the recipe, not a
hand-picked layer range, is what carries over. Gain is relative by construction: a steering pack's vector at
each layer has the norm of the typical residual there, and injection is renormalised to the hidden state's
norm, so a gain of 0.05 means about 5% of a typical residual norm on any model and needs no rescaling.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Qwen's band, as a fraction of its depth: layers 10 up to (not including) 19 of 28.
_REF_LO, _REF_HI, _REF_DEPTH = 10, 19, 28


def relative_band(n_layers: int) -> tuple[int, int]:
    """Qwen's relative layer band mapped onto a model with ``n_layers`` decoder layers: [lo, hi)."""
    return round(n_layers * _REF_LO / _REF_DEPTH), round(n_layers * _REF_HI / _REF_DEPTH)


@dataclass(frozen=True)
class ModelProfile:
    key: str                       # file-name friendly id, also the steering pack's model id
    hf_repo: str
    path: str                      # local weights
    served_name: str               # the label stored on runs
    dtype: str                     # "float16" | "bfloat16" | "float32"
    n_layers: int
    band: tuple[int, int]          # steered decoder layers: lo..hi-1
    revision: str | None = None    # exact Hugging Face commit the weights must be (None: not recorded)

    @property
    def pack_path(self) -> str:
        return os.path.join(ROOT, ".models", "steering", f"{self.key}.safetensors")


QWEN = ModelProfile(
    key="qwen2.5-1.5b-instruct", hf_repo="Qwen/Qwen2.5-1.5B-Instruct",
    path=os.path.join(ROOT, ".models", "Qwen2.5-1.5B-Instruct"), served_name="local:qwen2.5-1.5b-instruct",
    dtype="float16", n_layers=28, band=relative_band(28))

GRANITE = ModelProfile(
    key="granite-3.1-2b-instruct", hf_repo="ibm-granite/granite-3.1-2b-instruct",
    path=os.path.join(ROOT, ".models", "granite-3.1-2b-instruct"),
    served_name="local:granite-3.1-2b-instruct",
    dtype="bfloat16", n_layers=40, band=relative_band(40),
    revision="bbc2aed595bd38bd770263dc3ab831db9794441d")

PROFILES = {"qwen": QWEN, "granite": GRANITE}


def get(name: str) -> ModelProfile:
    if name not in PROFILES:
        raise ValueError(f"unknown model {name!r}; choose one of {sorted(PROFILES)}")
    return PROFILES[name]


def local_revision(path: str) -> str | None:
    """The Hugging Face commit a downloaded copy records, or None if it records none (or several)."""
    found = set()
    for meta in glob.glob(os.path.join(path, ".cache", "huggingface", "download", "*.metadata")):
        with open(meta, encoding="utf-8") as f:
            found.add(f.readline().strip())
    return found.pop() if len(found) == 1 else None


def revision_ok(profile: ModelProfile) -> tuple[bool, str]:
    """Whether the local weights are exactly the pinned revision. A profile with no pin always passes."""
    if profile.revision is None:
        return True, "no revision pinned"
    have = local_revision(profile.path)
    if have == profile.revision:
        return True, have
    return False, f"local weights are revision {have!r}, the profile pins {profile.revision!r}"
