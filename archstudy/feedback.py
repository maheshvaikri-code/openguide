"""The message an agent is shown about its visible-rule violations.

One function, used for both arms (Arm A at commit, Arm B after an edit), so the only
difference between the arms is *when* the message arrives, not what it says. It refuses
held-out rules: those must never reach the agent.
"""
from __future__ import annotations

from collections.abc import Iterable

from archstudy import rules

MAX_LISTED = 12
MAX_ADR_CHARS = 700
MAX_CHARS = 6000


def render(violations: Iterable[rules.Violation]) -> str:
    vs = sorted(violations)
    if not vs:
        return ""
    bad = sorted({x.rule for x in vs} - set(rules.VISIBLE))
    if bad:
        raise ValueError(f"only visible rules may be shown to the agent; got {bad}")
    lines = [f"Architecture check: {len(vs)} violation(s) of the written rules.", ""]
    for x in vs[:MAX_LISTED]:
        lines.append(f"{x.rule}  {x.path}:{x.line}  {x.message}")
    if len(vs) > MAX_LISTED:
        lines.append(f"... and {len(vs) - MAX_LISTED} more")
    lines += ["", "The rules behind these:"]
    for rule in sorted({x.rule for x in vs}):
        text = rules.adr_text(rule)
        lines += ["", text if len(text) <= MAX_ADR_CHARS else text[:MAX_ADR_CHARS].rstrip() + " ..."]
    msg = "\n".join(lines)
    return msg if len(msg) <= MAX_CHARS else msg[:MAX_CHARS - 4].rstrip() + " ..."
