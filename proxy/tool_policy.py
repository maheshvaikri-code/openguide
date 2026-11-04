"""Tool-call authorization policy for governed assistant actions.

This is deliberately small and deployment-facing: enterprises can configure
allow, deny, and approval-required tool-name patterns without changing OBC
schemas. Arguments are never stored in policy audit events.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any


@dataclass(frozen=True)
class ToolPolicyDecision:
    decision: str
    reason: str
    tools: list[dict[str, str]]

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


class ToolPolicy:
    def __init__(
        self,
        *,
        allow: list[str] | None = None,
        deny: list[str] | None = None,
        require_approval: list[str] | None = None,
    ):
        self.allow = [p for p in allow or [] if p]
        self.deny = [p for p in deny or [] if p]
        self.require_approval = [p for p in require_approval or [] if p]

    @property
    def enabled(self) -> bool:
        return bool(self.allow or self.deny or self.require_approval)

    def evaluate(self, tool_calls: list[dict[str, Any]] | None) -> ToolPolicyDecision:
        tools = [_tool_summary(tc) for tc in tool_calls or []]
        if not tools:
            return ToolPolicyDecision("allow", "no_tool_calls", [])

        names = [t["name"] for t in tools]
        if matched := _matching(names, self.deny):
            return ToolPolicyDecision("deny", f"denylist:{','.join(matched)}", tools)
        if matched := _matching(names, self.require_approval):
            return ToolPolicyDecision("deny", f"approval_required:{','.join(matched)}", tools)
        if self.allow:
            unlisted = [name for name in names if not _matches_any(name, self.allow)]
            if unlisted:
                return ToolPolicyDecision("deny", f"not_allowed:{','.join(unlisted)}", tools)
        return ToolPolicyDecision("allow", "allowed", tools)

    @classmethod
    def from_csv(
        cls,
        *,
        allow: str | None = None,
        deny: str | None = None,
        require_approval: str | None = None,
    ) -> "ToolPolicy":
        return cls(
            allow=_csv(allow),
            deny=_csv(deny),
            require_approval=_csv(require_approval),
        )


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(name, pat) for pat in patterns)


def _matching(names: list[str], patterns: list[str]) -> list[str]:
    return [name for name in names if _matches_any(name, patterns)]


def _tool_summary(tool_call: dict[str, Any]) -> dict[str, str]:
    fn = tool_call.get("function") or {}
    name = str(fn.get("name") or tool_call.get("name") or "")
    return {"id": str(tool_call.get("id") or ""), "name": name}
