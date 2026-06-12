"""OpenGuide proxy — the wedge.

An OpenAI-compatible proxy that activates behavioral governance on a per-request
header (``X-OpenGuide-Contract``) with zero changes to the calling app. Default
behavior is pass-through; governance is opt-in and side-channel — it observes
each turn, records hash-chained behavioral state, feeds a re-anchor forward into
the next turn, and exports gen_ai.behavior.* spans.
"""
from .app import create_app
from .upstream import MockUpstream, Upstream

__all__ = ["create_app", "Upstream", "MockUpstream"]
