"""LangGraph middleware: wrap a model node so every call is governed.

Adds the OpenGuide contract/session headers to the model invocation and records
the returned behavioral headers onto the graph state, so a parent graph and its
subagents share one conversation id (parent-child trace chaining).

    from integrations.langgraph_middleware import govern
    graph.add_node("model", govern(model_node, contract_hash, session_key="thread_id"))
"""
from __future__ import annotations

from typing import Any, Callable


def govern(node: Callable[[dict], dict], contract_hash: str,
           session_key: str = "thread_id") -> Callable[[dict], dict]:
    """Wrap a LangGraph node callable. Injects governance headers via the
    state's ``config.configurable.default_headers`` and folds behavioral
    metadata back into the returned state under ``openguide``."""

    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        session_id = str(state.get(session_key, "default"))
        headers = {
            "X-OpenGuide-Contract": contract_hash,
            "X-OpenGuide-Session": session_id,
        }
        cfg = state.setdefault("config", {}).setdefault("configurable", {})
        cfg.setdefault("default_headers", {}).update(headers)
        result = node(state)
        if isinstance(result, dict):
            result.setdefault("openguide", {})["session_id"] = session_id
        return result

    return wrapped
