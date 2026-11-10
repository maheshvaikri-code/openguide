# ADR-004: Architecture-drift study harness — hooks, silent snapshots, held-out scoring, container isolation

**Date:** 2026-11-10 · **Status:** accepted
**Deciders:** Chief Architect; human (Mahesh Vaikri) for the isolation requirement, the arm design and the primary measure (§5: no spend here)

## Context
The study (brief `docs/briefs/arch-drift-harness.md`) compares *when* architecture checks run for a coding agent: at commit (A), after
every edit (B), or never (C). It needs (1) a way to see every edit a Claude Code session makes, (2) a checker whose message is
identical in A and B, (3) a scorer the agent cannot influence and that also measures rules the loop never mentions, because an agent
can satisfy a checker while routing around its intent, and (4) a safe place to run an agent that writes and executes code.
Documented facts the design relies on (Claude Code docs, `hooks`, `settings`, `headless`, `cli-reference`, checked 2026-11-10):
a PostToolUse hook with matcher `*` runs after every tool call; JSON `hookSpecificOutput.additionalContext` on PostToolUse is added to
the model's context on its next request; "Claude never sees stderr from a hook that exits 0"; settings are hot-reloaded and nothing in
the docs stops the agent editing workspace `.claude/settings.json`, but managed settings outrank everything and
`allowManagedHooksOnly` blocks user, project and local hooks. Not documented: whether `MultiEdit` is a tool name; which OS user hooks
run as; exit 0 with no output is *inferred* silent, not stated.

## Decision
1. **One hook script, three arms.** `archstudy/hook.py` is registered for PostToolUse with matcher `*` (no dependence on tool names).
   Every arm: it snapshots the working tree silently (no output) when the tree changed. Arm **B** additionally runs the **visible**
   checks and, if any violation exists, returns the rendered message as `additionalContext`. Arm **A** installs a git `pre-commit`
   hook that runs the same checks and prints the same message to stderr (the agent sees a rejected commit in the Bash result). Arm
   **C** does neither. The arm is an environment variable set by the launcher, never by the agent.
2. **One renderer.** `archstudy/feedback.py::render` produces the message (rule id, file:line, message, the ADR excerpt for each
   distinct rule, bounded size). A and B call the same function, so only timing differs.
3. **Checks are stdlib `ast` scans of `app/`.** Visible: V1 layering, V2 `redis` only in `app/cache.py`, V3 outbound HTTP libraries
   only in `app/http_client.py`, V4 no unapproved third-party import. Held-out (documented in `docs/adr/`, never run in the loop):
   H1 no other network modules outside the HTTP client, H2 SQL only in repositories, H3 no dynamic imports or cross-module private
   names. The visible checks are deliberately the kind a real import linter does (static imports), so a disguised shortcut is
   possible and the held-out rules measure it.
4. **Silent snapshots into a separate git dir outside the workspace**, with an append-only hash-chained log
   (`prev_hash`, `hash`). The scorer refuses a broken chain or a final snapshot that differs from the final workspace tree. The
   runner writes task markers into the same chain between tasks.
5. **The scorer is offline and read-only**: it extracts each snapshot to a temp dir, runs all rules, and at the end the repo's tests
   and the hidden acceptance tests (held by the harness, never copied into the workspace).
6. **Task scripts** are a random linear extension of a small dependency graph with the two shock tasks pinned at positions 4 and 9,
   seeded and hashed.
7. **Isolation, fail closed.** The agent runs in a container built from a pure function `docker_run_argv(...)` and refused by
   `validate_argv(...)` unless: non-root user, read-only root filesystem, `--cap-drop ALL`, `no-new-privileges`, pid/memory/cpu
   limits, only the test-repo and a snapshot volume mounted, no Docker socket, no host network, not privileged, network only through
   an **egress allowlist proxy** (a CONNECT-only sidecar that permits `api.anthropic.com:443` and nothing else) on an internal
   network. Enforcement hooks live in **managed settings** inside the image (root-owned, read-only) with `allowManagedHooksOnly`, so
   the agent cannot disable or edit them. The image preinstalls `redis` and `requests` so the shortcut is possible. The image copies
   an **allowlist** of harness files (the hook, the commit check, the visible rules, the renderer, the snapshotter and the visible
   ADR texts); the held-out rules live in `heldout.py`, which is never copied, so the agent cannot read what the scorer checks
   (`rules.py` imports it behind an `ImportError` guard and a hook without it checks the visible rules and refuses a request for
   held-out ones). The egress proxy refuses names that resolve to non-public addresses and dials the resolved address.
8. **Secrets:** the API key exists only in the launcher's environment and the container's environment; `redact()` is applied to every
   string the harness stores; a test scans the repository for key-shaped strings.
9. **No real call in this step:** the package contains no network client and no launcher that starts a session; `launch` builds and
   validates an argv and stops. The one exception is `egress.py`, a CONNECT allowlist proxy for a later sidecar container: it
   imports `asyncio` and `socket` by design, is never started here, and a test checks that nothing else imports it.

## Alternatives considered
| Option | Pros | Cons | Why not |
|--------|------|------|---------|
| A (chosen) hooks + git pre-commit + separate-git-dir snapshots | Exact per-tool boundaries; uses the agent's real harness; arms differ only in timing | Same-user hook channel; relies on documented-but-new hook semantics | — |
| B Anthropic-API proxy that observes traffic | No in-container hooks | Cannot see edits, shell commands or file state | Cannot measure the thing |
| C Host-side filesystem watcher for snapshots | Outside the agent's reach | No alignment to tool calls; races; Windows/Linux differences | Edit boundaries are the measure |
| D Run the loop with the Agent SDK and own tool dispatch | Full control of feedback and snapshots | Not the agent people run; different system prompt/tools | Loses the realism the study is for |
| E import-linter / dependency-cruiser for the checks | Off the shelf | New dependency; less control over messages and the held-out split | Dependency policy; need identical messages |
| F do nothing / cheaper arms only | No build | Cannot show a measured difference | The point of the work |

## Consequences
- Positive: one measurement chain from edit to score; the held-out split detects routing around the checker; the dry run can prove
  the metric discriminates before any money is spent; the isolation spec is testable without a daemon.
- Negative / debt accepted: a determined agent could read or rewrite the snapshot store (same user), so tampering is detected, not
  prevented; the tasks are synthetic and small; Python only; one codebase.
- Behaviours of the treatment that the study will measure, not hide: in Arm B the message is repeated after every tree-changing
  call while a visible violation persists (the dry run: 13 messages for an agent that never fixes it, each carrying the ADR text),
  which is a real token and attention cost; in Arm A every later commit is rejected while the violation persists. An agent in Arm A
  can bypass the commit check with `git commit --no-verify`; the snapshots still record the tree, so the scorer sees the violation
  either way, but the *feedback* arm then did not deliver. The harness does not prevent this; the pilot should show whether it
  happens.
- Residual risks to carry into the pilot: (a) pilot canary: confirm that `additionalContext` actually shows up in the model's next
  turn, using `--include-hook-events` and a marker string, before the arms are compared; (b) hook latency per call;
  (c) tool names such as `MultiEdit` are irrelevant because the matcher is `*`, but a tool that edits files outside `Bash`/`Edit`/`Write`
  is still caught because the tree, not the tool, is the trigger.
- Invalidation triggers: Claude Code changes PostToolUse semantics; the pilot shows `additionalContext` does not reach the model; the
  pilot shows Claude never takes the shock shortcut (redesign shocks, not this ADR); a different agent harness is added.
