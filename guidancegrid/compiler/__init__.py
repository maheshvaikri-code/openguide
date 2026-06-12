"""OBC compiler: contract -> tier artifacts.

capability  - which enforcement tiers a target model supports
compile     - OBC -> CompiledContract (resolved tier + channel artifacts)
"""
from .capability import (
    CAPABILITIES,
    CapabilityDescriptor,
    CapabilityError,
    CapabilityResolver,
)
from .compile import CompiledContract, compile_contract

__all__ = [
    "CapabilityDescriptor",
    "CapabilityResolver",
    "CapabilityError",
    "CAPABILITIES",
    "CompiledContract",
    "compile_contract",
]
