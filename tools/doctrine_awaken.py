#!/usr/bin/env python3
"""doctrine_awaken: the activation doctor (Layer 0).

Installing the doctrine copies files; it does NOT prove the repo will actually
trigger the Engagement Protocol. This audits a repo's activation wiring and
reports every gap with a remediation, so a repo that "has Doctrine but never
uses it" is diagnosable in one command.

Checks, by layer:
  presence     -- .Doctrine.md, .Doctrine/, the activation tools
  load wiring  -- CLAUDE.md @-imports (Claude Code), AGENTS.md (other agents)
  awakening    -- SessionStart (state hydrate) + UserPromptSubmit (per-turn
                  re-arm) hooks in .claude/settings.json
  state plane  -- .doctrine-state/ initialized

Output is ASCII-only (Windows cp1252-safe). Exit 0 only when every CRITICAL
check passes; recommended-but-missing items warn without failing. Consumer-safe
by construction: it inspects wiring only -- no version carriers, no host tests.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OK, MISS, WARN = "[OK]  ", "[MISS]", "[WARN]"


def audit(root: Path) -> tuple[list[tuple[str, str, str]], bool]:
    """Return ``(rows, awake)``. Each row is ``(marker, message, remediation)``;
    ``awake`` is True only when all CRITICAL checks pass."""
    rows: list[tuple[str, str, str]] = []
    critical_ok = True

    def crit(cond: bool, msg: str, fix: str) -> None:
        nonlocal critical_ok
        rows.append((OK if cond else MISS, msg, "" if cond else fix))
        if not cond:
            critical_ok = False

    def rec(cond: bool, msg: str, fix: str) -> None:
        rows.append((OK if cond else WARN, msg, "" if cond else fix))

    # --- presence (critical) ---
    crit((root / ".Doctrine.md").is_file(), ".Doctrine.md present (the law)",
         "not a doctrine repo -- run: python tools/doctrine_install.py --target .")
    crit((root / ".Doctrine").is_dir(), ".Doctrine/ playbooks present",
         "run doctrine_install to copy the .Doctrine/ folder")

    # --- load wiring ---
    claude = root / "CLAUDE.md"
    claude_txt = claude.read_text("utf-8", "replace") if claude.is_file() else ""
    crit("@.Doctrine.md" in claude_txt,
         "CLAUDE.md imports @.Doctrine.md (Claude Code load)",
         "add '@.Doctrine.md' to CLAUDE.md, or run doctrine_install")
    rec("@.doctrine-state/local/hydration.bundle.md" in claude_txt,
        "CLAUDE.md imports the state hydration bundle",
        "add '@.doctrine-state/local/hydration.bundle.md' to CLAUDE.md")
    rec((root / "AGENTS.md").is_file(),
        "AGENTS.md present (boot for non-Claude agents)",
        "copy .Doctrine/adapters/AGENTS.md to the repo root (Cursor/Copilot/Codex/...)")

    # --- awakening hooks ---
    settings: dict = {}
    sp = root / ".claude" / "settings.json"
    if sp.is_file():
        try:
            settings = json.loads(sp.read_text("utf-8", "replace"))
        except (ValueError, OSError):
            settings = {}
    hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    rec(bool(hooks.get("SessionStart")),
        ".claude/settings.json SessionStart hook (state hydration at start)",
        "wire SessionStart -> 'python tools/doctrine_state.py hydrate --if-present'")
    crit(bool(hooks.get("UserPromptSubmit")),
         ".claude/settings.json UserPromptSubmit hook (per-turn engagement)",
         "wire UserPromptSubmit -> 'python tools/doctrine_engage.py'; without it the "
         "Engagement Protocol never re-arms per turn (the core awakening gap)")

    # --- activation tools + state plane ---
    rec((root / "tools" / "doctrine_engage.py").is_file(),
        "tools/doctrine_engage.py present (the per-turn reminder)",
        "run doctrine_install to copy the activation tools")
    rec((root / ".doctrine-state").is_dir(),
        ".doctrine-state/ initialized (state plane)",
        "run: python tools/doctrine_state.py init")

    return rows, critical_ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="doctrine_awaken",
        description="Audit whether a repo will actually wake Doctrine up.")
    ap.add_argument("--target", default=".", help="repo root to audit (default: cwd)")
    ap.add_argument("--quiet", action="store_true", help="print only the verdict line")
    args = ap.parse_args(argv)

    root = Path(args.target).resolve()
    rows, awake = audit(root)

    if not args.quiet:
        print(f"doctrine_awaken: activation audit for {root}")
        for marker, msg, fix in rows:
            print(f"  {marker} {msg}")
            if fix:
                print(f"         -> {fix}")
    n_ok = sum(1 for marker, _, _ in rows if marker == OK)
    verdict = "AWAKE" if awake else "NOT FULLY AWAKE"
    tail = "" if awake else " (critical gaps above)"
    print(f"{verdict}: {n_ok}/{len(rows)} checks pass{tail}")
    return 0 if awake else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
