# Implementation Plan — architecture-drift study harness (step 1)

**Brief:** `docs/briefs/arch-drift-harness.md` · **ADR:** `docs/adr/004-architecture-drift-study-harness.md` · **Date:** 2026-11-10

Package `archstudy/` (stdlib only), tests `tests/test_archstudy_*.py`, dry-run script `scripts/arch_dryrun.py`.

## Work packages and interfaces
| WP | Owner | Files | Interface (fixed here) |
|----|-------|-------|------------------------|
| 1 Rules + codebase | Backend | `archstudy/rules.py`, `archstudy/codebase/**` (template: `app/`, `tests/`, `docs/adr/001-007`, `CLAUDE.md`) | `Violation(rule, path, line, message)`; `VISIBLE`, `HELD_OUT` tuples of rule ids; `check_tree(root, rules) -> list[Violation]`; `adr_text(rule) -> str` from the harness's own copy |
| 2 Message | Backend | `archstudy/feedback.py` | `render(violations) -> str` (bounded, deterministic); same function used by A and B |
| 3 Snapshots + hook | Backend | `archstudy/snapshot.py`, `archstudy/hook.py`, `archstudy/precommit.py`, `archstudy/workspace.py` | `Snapshotter(workspace, store).snapshot(tool) -> Entry or None`; `.mark(kind, value)`; `verify_chain(store)`; `hook.main(stdin_text, env) -> (stdout, exit)`; `workspace.create(dest, arm)` |
| 4 Tasks + acceptance | Backend | `archstudy/tasks.py`, `archstudy/acceptance/test_T*.py` (hidden) | `build_script(seed) -> Script(order, shocks, hash)`; acceptance run by the scorer with `PYTHONPATH=<snapshot>` |
| 5 Scorer | Backend | `archstudy/score.py` | `score_run(store, workspace_final) -> RunScore` (visible/held-out final, edits in violation, episodes, task success, tool calls) |
| 6 Stand-ins + dry run | Backend | `archstudy/standin.py`, `archstudy/solutions.py`, `scripts/arch_dryrun.py` | `run_standin(policy, arm, script, dest) -> RunScore` driving the real hook with real PostToolUse JSON |
| 7 Isolation | DevOps (worker, parallel) | `archstudy/isolation.py`, `archstudy/egress.py`, `archstudy/redaction.py`, `archstudy/container/{Dockerfile,managed-settings.json}` | `docker_run_argv(...)`, `validate_argv(argv)` raises `IsolationError`; `egress.allowed(host, port)`, `EgressProxy`; `redact(text)`; Dockerfile static properties |

## Order
WP7 starts now in parallel (no dependency on 1-6). WP1 -> 2 -> 3 -> 4 -> 5 -> 6 in sequence by me (each depends on the previous). Verifiers
(code-reviewer, security-reviewer, qa-engineer) run on the finished package in fresh context.

## Tests -> acceptance criteria (trace)
| AC | Tests |
|----|-------|
| 1 | `test_archstudy_rules.py::test_the_template_has_no_violations`, template tests pass (run by the scorer test) |
| 2 | `test_archstudy_rules.py` one violating and one compliant fixture per rule; purity (no subprocess/network imports in `rules.py`) |
| 3 | `test_archstudy_tasks.py` (properties over many seeds) |
| 4, 5 | `test_archstudy_hook.py`, `test_archstudy_feedback.py` |
| 6 | `test_archstudy_snapshot.py` (chain, tamper, final-tree mismatch) |
| 7 | `test_archstudy_score.py` |
| 8 | `test_archstudy_isolation.py`, `test_archstudy_redaction.py` (and daemon tests that skip without Docker) |
| 9 | `test_archstudy_dryrun.py`, `scripts/arch_dryrun.py` |
| 10 | `test_archstudy_no_network.py` (static) |

## Risks
Synthetic tasks may not tempt a real model (the pilot gate measures it); hook latency on a slow disk; Windows git quirks (CRLF, path
separators) -- the dry run runs on the host, the study runs on Linux; `additionalContext` delivery is documented but unobserved (pilot
canary, ADR-004).
