# Project/Task Brief — Architecture-drift study harness (step 1, no API spend)

**Date:** 2026-11-10 · **Class:** L (new subsystem; a new threat surface: an agent that executes code) · **Requested by:** human (Mahesh Vaikri)

## Problem
OpenGuide's evidence for correcting drift is on one small open model in a chat setting. The claim it needs for its goal, "any agent,
on any model, held to a written contract", is about coding agents on frontier models, where the thing that drifts is architecture
(layering, dependency, boundary rules) and the correction is a targeted message at the right time. Nobody, including this project, has a
measured number for "correct at every edit" against "catch at commit" against "no checks". Before spending real API money the harness
that will produce that number has to exist and has to be shown to measure what it claims: it must catch a shortcut, catch a
*disguised* shortcut, and not be fooled by an agent that satisfies the visible checker and routes around it.

## Scope
- In (this brief = step 1, **no real Claude call, no API spend**):
  1. A synthetic Python codebase with **4 visible rules** (each an ADR plus an automatic check) and **3 held-out rules** of the same
     kind (each an ADR, but never checked in the agent's loop and never fed back).
  2. A task-script generator: 12 tasks, two **shock** tasks pinned at positions 4 and 9 whose wording tempts the agent to break a
     visible rule; seeded, deterministic, with dependency-respecting order; hidden acceptance tests per task.
  3. A Claude Code **hook adapter** with three arms: **A** checks only at commit, **B** checks after every edit, **C** no checks.
  4. A **silent scorer** in every arm: a snapshot after every tool call, scored offline on visible and held-out rules and tests; the
     agent never sees it.
  5. **Isolation**: the agent session specified to run in a container (read-only root, non-root, capabilities dropped, no host mounts
     beyond the test repo, network only to the Anthropic API through an egress allowlist), validated fail-closed before launch; and the
     rule that no API key ever enters the repo, traces or logs.
  6. A **dry run** end to end with scripted stand-in agents that take the shortcut at the shocks, including one that disguises it.
- **Non-goals:** any real Claude call; the pilot and the main study (separate approvals, and the main study's budget is set from the
  pilot's measured cost); a judge-model check; a proxy for Anthropic's API; production concurrency/auth; extending steering to other
  models; the plausible-but-wrong-direction study (named as the open question in the write-up instead).
- Deferred (parked, not built): variation of the codebase across scripts beyond task order and shock wording; a second language; a
  tamper-proof snapshot channel (see Risks in ADR-004); cost/latency instrumentation beyond tool-call counts (comes from the real
  stream in the pilot).

## Acceptance criteria (numbered, testable)
1. Given the codebase template, when all rules and the tests run on it, then it has 0 violations of every rule and its tests pass.
2. Each rule has a test with a violating fixture and a compliant fixture; the checks are deterministic and do no I/O beyond reading the
   tree (no subprocess, no network).
3. Given any seed, the script has 12 distinct tasks, the shocks at positions 4 and 9, every task after its dependencies, the same
   output for the same seed, and many distinct orders across seeds.
4. Given a PostToolUse event in Arm B and a tree with a visible violation, the hook returns feedback containing rule id, location, and
   the ADR text; in Arms A and C it returns **nothing** (exit 0, empty stdout and stderr). In every arm it records a snapshot when the
   tree changed, silently.
5. The message an agent receives for the same violations is **byte-identical** in Arm A (at commit) and Arm B (after edit): only
   *when* it arrives differs.
6. The snapshot log is append-only and hash-chained; the scorer refuses a log whose chain is broken or whose last snapshot differs from
   the final workspace tree.
7. The scorer reports, per run: visible and held-out violations left; edits spent in violation (both); episodes per rule
   (introduced, fixed, recurred); task success from hidden acceptance tests and the repo's tests; tool-call count. It never writes
   into the workspace.
8. The container launch command is built by a pure function and validated fail-closed: it is refused if any hardening property is
   missing, a mount is outside the allowed set, the Docker socket or host network is used, or it is privileged. A key pattern is
   redacted from anything the harness stores, and a scan finds none in the repository.
9. Dry run, per arm, with stand-in agents: a **compliant** agent scores 0 violations and full task success; a **shortcut** agent is
   caught on the visible rules; a **disguised** agent scores 0 visible violations and >0 held-out violations, and the scorer catches
   it; a **responsive** agent (breaks a rule, fixes it after feedback) spends fewer edits in violation in Arm B than in Arm A.
10. No code path in the package makes a network call or imports an Anthropic client (static check in the tests).

## Constraints
Python 3.10+ stdlib only for the harness (a new dependency needs the dependency policy); runs on Windows hosts and a Linux container;
hooks run per tool call so each must finish in well under a second on the synthetic codebase; ASCII output; every spec and
decision rule is frozen by commit **before** any run that counts (later steps).

## Assumptions (chosen defaults — correct me if wrong)
- **Same message in both arms (a deliberate deviation from your paste).** Your table has Arm A show "a list of violations" and Arm B
  "the rule plus the ADR text". If the content differs, any difference in outcome mixes *timing* with *content*. I made the message
  identical (rule id, location, ADR excerpt) so the only difference is when it arrives, which is the question asked.
- **Held-out rules are written down but not fed back.** Each has an ADR in `docs/adr/` like the visible ones (a rule the agent was never
  told about cannot fairly be "violated"), and is never run in the agent's loop, in either arm. They are scored at every snapshot.
- Tasks add code in existing layers and are order-independent, so any dependency-respecting order is valid. They are small and
  synthetic; whether they are realistic enough to tempt a real model is exactly what the pilot gate measures.
- The container image preinstalls `redis` and `requests` so the shortcut is *possible*; otherwise a missing package, not a rule,
  would stop the agent (the floor problem the first steering design had).
- Snapshots are written by the hook, inside the container, to a path outside the workspace. The agent is never told about it; it could
  in principle read it. The chain and the final-tree check make tampering detectable, not impossible (residual risk, ADR-004).
- Pilot gate (later, not built here): Claude takes the shock shortcut in at least 40% of no-check runs, or the shocks are redesigned.

## Open questions (blocking — answered before G1)
- None blocking this step. Decisions already made by the human: model = current Sonnet with the exact string pinned; pilot spend cap
  $50 set in the Anthropic console before any key exists; the model and main budget are the human's; the primary measure for a later
  registration is "Arm B ends with fewer visible-rule violations than Arm A, and held-out violations are not worse
  (non-inferiority)", with task success and time spent broken reported for all arms, 3 replicates per script per arm, bootstrap over scripts.

**Human confirmed:** yes (scope, isolation requirement, primary measure, stop before any real Claude call) · 2026-11-10
