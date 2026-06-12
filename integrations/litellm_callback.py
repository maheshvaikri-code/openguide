"""LiteLLM callback: surface OpenGuide behavioral headers as structured events.

LiteLLM can route through the OpenGuide proxy (set api_base to the proxy). This
success callback reads the ``X-OpenGuide-*`` response headers LiteLLM exposes on
the raw response and emits a structured behavioral event — distribution through
the ecosystem, not against it.

Register:
    import litellm
    from integrations.litellm_callback import openguide_callback
    litellm.success_callback = [openguide_callback]
"""
from __future__ import annotations

from typing import Any


def extract_behavior(headers: dict[str, str]) -> dict[str, Any]:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if "x-openguide-contract" not in h:
        return {}
    out: dict[str, Any] = {
        "contract_hash": h.get("x-openguide-contract"),
        "tier": h.get("x-openguide-tier"),
    }
    if "x-openguide-drift" in h:
        out["drift"] = float(h["x-openguide-drift"])
    if "x-openguide-recovery" in h:
        out["recovery"] = h["x-openguide-recovery"]
    return out


def openguide_callback(kwargs, completion_response, start_time, end_time):  # litellm signature
    headers = {}
    try:
        headers = completion_response._hidden_params.get("additional_headers", {})  # litellm
    except Exception:
        headers = getattr(completion_response, "response_headers", {}) or {}
    behavior = extract_behavior(headers)
    if behavior:
        # hand off to your telemetry sink; here we just print
        print(f"[openguide] {behavior}")
    return behavior
