# archstudy: harness for the architecture-drift study (step 1, no API spend)

Measures whether correcting a coding agent's architecture violations **at every edit** (Arm B) beats catching them **at commit**
(Arm A), against **no checks** (Arm C), on the same task script. Brief: `docs/briefs/arch-drift-harness.md`. Decisions:
`docs/adr/004-architecture-drift-study-harness.md`. Plan: `docs/plans/arch-drift-harness.md`.

**Nothing here calls a model or an API.** The package contains no network client. `egress.py` (a CONNECT allowlist proxy for a later
sidecar container) is the one network component and is never started.

## What is in it
| Module | Job |
|---|---|
| `codebase/` | The synthetic orders service the agent works in: 4 visible rules and 3 held-out rules, each written as an ADR |
| `rules.py` | The visible checks (V1 layering, V2 Redis only in the cache, V3 outbound HTTP via the client, V4 no unapproved library) |
| `heldout.py` | The held-out checks (H1 network primitives, H2 SQL outside repositories, H3 dynamic imports / private names). **Scorer-side only; never copied into the agent's image** |
| `feedback.py` | The one message the agent sees, identical in Arm A and Arm B; refuses held-out rules |
| `hook.py`, `precommit.py` | The Claude Code PostToolUse hook (snapshots in every arm; feedback in Arm B) and the git commit check (Arm A) |
| `snapshot.py` | Silent tree snapshots in a separate git dir, hash-chained log, tamper checks |
| `tasks.py`, `acceptance/` | 12 tasks with two shocks (positions 4 and 9), a seeded script generator, hidden acceptance tests |
| `score.py` | The silent scorer: violations left, edits in violation, episodes, task success |
| `standin.py`, `solutions.py`, `dryrun.py` | Scripted stand-in agents and the dry-run matrix with its registered expectations |
| `isolation.py`, `egress.py`, `redaction.py`, `container/` | Fail-closed container launch validation, the egress allowlist proxy, key redaction, the image definition |

## Run the dry run
```
python scripts/arch_dryrun.py --quick     # about a minute: first 9 tasks, in-process hook
python scripts/arch_dryrun.py             # full: the real hook as a subprocess, tests included
python -m pytest tests/test_archstudy_*.py
```
The dry run replays four scripted policies (compliant, shortcut, disguised, responsive) through every arm and checks that the scorer
tells them apart: a compliant agent is clean; a shortcut is caught by the visible rules; a disguised shortcut passes the visible rules
and is caught by the held-out ones; an agent that fixes a violation when told spends fewer edits in violation in Arm B than in Arm A.

## What this does not show
- It validates the **measuring chain**, not any model. Stand-in agents say nothing about what Claude does.
- **Verified here:** rules, message, hook, snapshots, scorer, task script, acceptance tests, launch-command validation, egress proxy
  logic (against loopback), image file allowlist (static).
- **Not verified here:** the Docker image has not been built and no container has been started (Docker was not running); that
  Claude Code honours `allowManagedHooksOnly` from `/etc/claude-code/managed-settings.json`; that `additionalContext` from a
  PostToolUse hook reaches the model in practice (documented, unobserved: the pilot starts with a canary); that Claude takes the
  shock shortcut at all (the pilot gate: at least 40% of no-check runs, or the shocks are redesigned).
- Known residual risks are in ADR-004: same-user snapshot store (tampering is detected, not prevented), `git commit --no-verify` in
  Arm A, synthetic and small tasks, Python only.

## Before any real Claude call (separate approval)
Pilot: the current Sonnet with its exact model string pinned; a spend cap set in the Anthropic console before a key exists; the key
in an environment variable or an external file, never in the repo, traces or logs. Pilot gate and measured cost per session come
first; the main study's budget is set from that, and its specification is frozen by commit before it runs.
