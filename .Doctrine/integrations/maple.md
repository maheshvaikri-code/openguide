---
integration: maple
upstream: https://github.com/maheshvaikri-code/maple-oss
license: AGPL-3.0 (see the license verdict below — opt-in, never linked)
pinned_version: 1.1.2
discipline: multi-agent-runtime
verified: 2026-07-14
---

# MAPLE — Integration (opt-in workforce runtime)

MAPLE (Multi Agent Protocol Language Engine, `pip install maple-oss`) is a
multi-agent runtime and protocol: typed messages with `Result<T,E>` error
handling, a broker (in-memory to NATS), pairwise link-identified secure
channels, resource negotiation, task scheduling, and an autonomy layer
with LLM providers (Anthropic included) — three layers: L1 protocol,
L2 runtime, L3 autonomy SDK. As of **1.1.2** it ships a first-class
**doctrine profile** (`maple.adapters.doctrine_adapter`) and a
**broker-enforced fresh-context verifier preset**
(`maple.security.separation`) built to this integration's spec.
Verified here (2026-07-14, Windows, Python 3.12) against the 1.1.2 source
tree, all real output: the case-trap fix (a lowercase-registered handler
now fires), `require_routable=True` returning `Err UNROUTABLE` for a
missing agent, `build_work_package`/`build_gate_result` producing and
validating typed messages (bogus verdict rejected), the preset **blocking
a verifier→builder route**, and `tokens` as a `ResourceRequest` field.

Doctrine remains runtime-agnostic: this integration is OPT-IN. Without
it, the workforce runs on the host agent's native subagents (or serial
role-switching per `04-agent-adapters.md`). With it, roles become
persistent, addressable agents.

## The fit — Doctrine concept → MAPLE primitive

| Doctrine                                | MAPLE                                    |
|-----------------------------------------|------------------------------------------|
| Role / subagent                         | `Agent` (L2) or `AutonomousAgent` (L3, Anthropic provider) |
| Orchestrator (main session)             | `AgentOrchestrator.execute_supervised`   |
| Verifier panel (G4/G5 fan-out)          | `AgentOrchestrator.execute_consensus`    |
| Work package (declared file scope)      | `build_work_package(package_id, role, file_scope, brief_ref)` → typed `WORK.PACKAGE`; `validate_work_package` checks an incoming one |
| Gate verdict                            | `build_gate_result(gate, verdict, artifact_ref)` → typed `GATE.RESULT`; verdict validated against `GATE_VERDICTS` (`PASS`/`FAIL`/`BLOCKED`/`WAIVED`) |
| Honest reporting ("blocked" is valid)   | `Result<T,E>` — errors are values, never fabricated success; `send(..., require_routable=True)` → `Err UNROUTABLE` instead of a misleading `Ok` |
| Separation of duties                    | `fresh_context_verifier_preset(orchestrator, builders, verifiers)` → a broker-enforced `SeparationOfDutiesPolicy`: per-agent sender allowlist (fail-closed) + artifact-ref-only payloads. A verifier **cannot** route to a builder. Not a convention — a runtime guarantee |
| Permission matrix (enterprise profile)  | `security/` authentication + authorization + audit; the separation policy above |
| Loop caps / budgets                     | `ResourceRequest.tokens` (LLM budget, first-class beside compute/memory) + `ResourceNegotiator` |
| doctrineos MCP server                   | `maple.adapters.mcp_adapter` — MAPLE agents read the law over MCP |

Two hard boundaries, non-negotiable:

1. **MAPLE routes; gates decide.** A message reaching a verifier is not a
   review. Verdicts count only as artifacts under `docs/` (content-pinned,
   per `standards/merge-and-promotion.md`). The runtime is transport.
2. **The state plane stays the durable truth.** MAPLE's state store is
   ephemeral runtime state. Checkpoints, distillates, and decisions live
   in `.doctrine-state/` (hash-chained, git-committed) — never in the
   broker.

## Wiring pattern (verified shape, 1.1.2)

```python
from maple import Agent, Config
from maple.adapters.doctrine_adapter import build_work_package
from maple.security.separation import ArtifactRef, fresh_context_verifier_preset

worker = Agent(Config(agent_id="backend-engineer",
                      broker_url="memory://localhost", capabilities=["build"]))
worker.register_handler("work.package", on_work_package)  # 1.1.2 normalizes case

# separation of duties as a runtime guarantee, not a convention:
policy = fresh_context_verifier_preset(
    "orchestrator", builders=["backend-engineer"], verifiers=["code-reviewer"])

wp = build_work_package("wp-1", "backend-engineer", ["src/service/"],
                        ArtifactRef("docs/brief.md", brief_sha256),
                        sender="orchestrator", receiver="backend-engineer")
orchestrator.send(wp.unwrap(), require_routable=True)   # Err UNROUTABLE, not a false Ok
```

Payload discipline: work packages and verdicts carry **artifact
hashedrefs** (`ArtifactRef(path, sha256)`), not prose — enforced by the
preset's artifact-ref-only payload policy for guarded types. A builder's
reasoning cannot travel to a verifier; the verifier reads the artifact
fresh. Message types are Doctrine's protocol vocabulary: `WORK.PACKAGE`,
`GATE.RESULT`, plus §5 escalations, which always terminate at the human,
never at another agent.

## Resolved in 1.1.2 (the 1.1.1 sharp edges, now fixed)

- **Handler-key case trap → fixed.** `register_handler` now normalizes keys
  to upper-case, matching `Message` (the `@agent.handler` decorator path
  too). A handler registered `"work.package"` fires for `WORK.PACKAGE`.
  Verified here.
- **`send()` Ok = enqueue → opt-in delivery check.** `send(...,
  require_routable=True)` returns `Err UNROUTABLE` when the receiver has no
  live subscription (via `MessageBroker.is_routable`). The default `send()`
  is unchanged (Ok = enqueued), so still treat a default dispatch as
  reply-or-timeout; use `require_routable=True` when a false Ok would
  mislead. Reachability is checked at *send* time — a post-delivery
  acknowledgement receipt remains future work. Verified here.
- Also fixed in 1.1.2 (pre-existing bugs): broker **double-delivery** (each
  direct message was enqueued into two queues and delivered twice) and a
  `TaskQueue` **shutdown hang** (`stop()` blocked ~5s on a sleeping cleanup
  thread).

## Enhancement asks — SHIPPED in maple-oss 1.1.2

All five landed (the 1.1.2 CHANGELOG maps each to its ask number; verified
here against the source tree):

1. ✅ `register_handler` key normalization (kills the case trap). 5 tests.
2. ✅ Routability check: `MessageBroker.is_routable`, `send(...,
   require_routable=True)` → `Err UNROUTABLE`. 7 tests. (Post-delivery ack
   receipt still open.)
3. ✅ Fresh-context verifier preset: `maple.security.separation` —
   `SeparationOfDutiesPolicy` (fail-closed sender allowlist +
   artifact-ref-only payloads), `fresh_context_verifier_preset(...)`,
   `ArtifactRef(path, sha256)`. Separation of duties is now a
   **broker-enforced runtime guarantee**.
4. ✅ Doctrine profile: `maple.adapters.doctrine_adapter` —
   `build_work_package` / `build_gate_result` (→ `Result[Message]`),
   `validate_work_package` / `validate_gate_result`, `DoctrineAdapter`,
   `GATE_VERDICTS`. 34 tests. Imported explicitly, so `import maple` stays
   free of the security layer.
5. ✅ `tokens` as a `ResourceRequest` resource type (round-trips through
   negotiation; `ResourceManager` allocates it). 9 tests.

This closes the v0.6.11 caveat: transport-level duty separation was a
documented convention; with ask #3 shipped it is a broker-enforced
guarantee. Remaining open upstream: a true post-delivery acknowledgement
receipt (beyond send-time reachability).

## License verdict (dependency-policy §4: AGPL = explicit human decision)

MAPLE is AGPL-3.0 and first-party (same author as this doctrine).
Disposition, recorded 2026-07-13 (unchanged at 1.1.2): **never vendored,
never imported by doctrineos** — the wheel, MCP server, and tools stay
stdlib-only; this integration is a document and a protocol contract. The
doctrine profile ships inside `maple-oss`, not here, so no AGPL code
enters this repo. Consumer repos that
opt into the MAPLE runtime take the AGPL obligation knowingly (flag it
in their brief: `Workforce runtime: maple`). For the owner's own repos
the copyleft cost is nil.

## Boundaries

The runtime never replaces briefs, gates, artifacts, or the human's §5
authority. If the broker is down, the doctrine still runs — degraded to
native subagents or serial role-switching. Adoption order: prove the
task needs persistent cross-agent messaging first (most Class M work
does not); the runtime earns its keep at fleet scale, not on a bugfix.
