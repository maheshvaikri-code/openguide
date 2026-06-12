"""Capability resolution: tier selection and floor enforcement."""
import pytest

from guidancegrid.compiler.capability import (
    CapabilityError,
    CapabilityResolver,
    tier_rank,
)


def test_tier_rank_order():
    assert tier_rank("t0") < tier_rank("t1") < tier_rank("t2") < tier_rank("t3")


def test_resolve_picks_strongest_supported():
    r = CapabilityResolver()
    assert r.resolve("vllm:qwen2.5-7b", "t3") == "t0"      # full stack -> strongest
    assert r.resolve("openai:gpt-4o", "t3") == "t2"        # closed API caps at t2
    assert r.resolve("llamacpp:local", "t3") == "t1"


def test_resolve_respects_floor():
    r = CapabilityResolver()
    # floor t2 on a closed model: t2 is strongest that meets floor
    assert r.resolve("anthropic:claude", "t2") == "t2"


def test_resolve_refuses_when_floor_unmet():
    r = CapabilityResolver()
    with pytest.raises(CapabilityError):
        r.resolve("openai:gpt-4o", "t0")     # needs activation; closed API can't
    with pytest.raises(CapabilityError):
        r.resolve("llamacpp:local", "t0")    # no activation tier


def test_unknown_provider_defaults_to_closed_tiers():
    r = CapabilityResolver()
    assert r.resolve("mystery:model", "t3") == "t2"
    with pytest.raises(CapabilityError):
        r.resolve("mystery:model", "t0")


def test_wildcard_and_exact_lookup():
    r = CapabilityResolver()
    d = r.descriptor_for("openai:gpt-4o-mini")
    assert "t2" in d.tiers and "t0" not in d.tiers
