#!/usr/bin/env python3
"""doctrine_engage: the per-turn awakening reminder (Layer 1).

Wired as a Claude Code ``UserPromptSubmit`` hook, this re-arms the Engagement
Protocol on EVERY user message: it prints a compact reminder that Claude Code
injects into the agent's context, so the doctrine is triggered per-task rather
than merely loaded once at session start and forgotten mid-session.

Repo-safe and consumer-safe: if no ``.Doctrine.md`` is found at (or above) the
working directory, it prints nothing and exits 0 -- a no-op outside a doctrine
repo. Output is ASCII-only (Windows cp1252 pipes crash on stray Unicode
punctuation) per the v0.6.10->v0.6.18 self-evolution retrospective.
"""
from __future__ import annotations

import sys
from pathlib import Path

REMINDER = (
    "[Doctrine active] This repo runs on the Engineering Doctrine (.Doctrine.md). "
    "Before acting on the request above:\n"
    "  1. Open your reply with the [DOCTRINE ENGAGED] block.\n"
    "  2. Classify the task (S / M / L / HOTFIX) and name the role hat.\n"
    "  3. Read the routed skills/roles from the .Doctrine.md Section 6 routing "
    "table for whatever the task touches -- do not work from memory of them.\n"
    "  4. Execute the gate path for that class; stop only at a Section 5 escalation.\n"
    "Right-size the ceremony: a Class S task earns the one-line block."
)


def find_root(start: Path) -> Path | None:
    """Nearest ancestor (including ``start``) that contains ``.Doctrine.md``."""
    for d in (start, *start.parents):
        if (d / ".Doctrine.md").is_file():
            return d
    return None


def main(argv: list[str] | None = None) -> int:
    # No arguments are needed; tolerate any (hook robustness).
    if find_root(Path.cwd()) is None:
        return 0  # not a doctrine repo -> silent no-op
    sys.stdout.write(REMINDER + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
