# OpenGuide as an Enterprise Governance Layer for Agentic AI

This document describes the strategic enterprise role for OpenGuide: the layer
that lets autonomous AI agents take real action against corporate systems under
durable, reviewable, auditable runtime control.

## One-Line Positioning

OpenGuide is an enterprise governance layer for agentic AI: a behavioral
control plane that sits between autonomous agents and corporate action.

Shorter phrasing:

> The governance layer between autonomous agents and real corporate action.

Enterprise phrasing:

> OpenGuide lets autonomous AI agents act inside enterprise systems under
> contract-bound, auditable runtime control.

## Why This Layer Is Needed

Enterprise AI is moving from chat and copilots toward agents that can perform
multi-step work and call tools. Those agents may:

- Modify code.
- Query databases.
- Update CRM records.
- Send customer messages.
- Trigger business workflows.
- Access internal documents.
- Create tickets or incidents.
- Make recommendations that affect regulated processes.
- Operate across many turns with partial autonomy.

For this class of AI system, final-answer review and prompt logging are not
enough. Enterprises need a runtime layer that can answer:

- What was the agent allowed to do?
- Which behavioral contract was active?
- Did the agent stay inside task and tenant scope?
- Were required checks satisfied before tool use?
- Did the agent drift from policy before taking action?
- Was a risky action re-anchored, escalated, or halted?
- Can the full behavioral record be reviewed and verified later?

OpenGuide is designed to occupy that missing layer.

## Where It Sits in the AI System

OpenGuide sits between the agent or application layer and the systems the agent
can affect.

```text
User / business workflow
        |
        v
Agent or orchestration layer
        |
        | proposed reasoning, messages, tool calls, actions
        v
OpenGuide governance layer
        |
        | contract checks, drift state, recovery, audit trace
        v
Model provider / inference runtime / corporate tools
        |
        v
Corporate systems of record
```

In an enterprise deployment, OpenGuide may be placed in several adjacent
positions:

- In front of model providers as an OpenAI-compatible proxy.
- Inside an agent runtime as a behavioral reconciler.
- Alongside tool gateways as a policy and audit layer.
- Upstream of observability, SIEM, GRC, and compliance systems.
- Behind a console used by AI platform, security, risk, and compliance teams.

The core idea is that OpenGuide is not the model and not the agent. It is the
runtime governance layer around agent behavior.

## The Control Loop

OpenGuide creates a closed loop around agent behavior:

1. Declare the expected behavior in an Open Behavioral Contract.
2. Observe actual behavior through typed sensors and validators.
3. Compute drift from declared floors and hard rules.
4. Decide whether the run remains healthy.
5. Re-anchor, escalate, halt, or continue.
6. Record the state and decision in a hash-chained trace.

This moves enterprise agent control from hope to runtime evidence.

Without OpenGuide:

```text
Prompt -> agent acts -> logs reviewed later
```

With OpenGuide:

```text
Contract -> agent acts -> behavior measured -> drift reconciled
         -> action allowed/re-anchored/escalated/halted -> trace verified
```

## What "Durable, Reviewable, Auditable Control" Means

### Durable Control

Control is durable when it is not only embedded in a prompt or hidden in
application code. In OpenGuide, control is represented by versioned behavioral
contracts and content hashes.

Durable control means:

- The expected behavior is explicit.
- The policy can be reviewed before deployment.
- The policy can be referenced by hash during a run.
- Behavior can be compared across contract versions.
- The same contract can be applied across models and workflows.

### Reviewable Control

Control is reviewable when humans can inspect the policy, runtime state, and
decisions.

Reviewable control means teams can see:

- Which contract was active.
- Which invariants were measured.
- Which floors were violated.
- Which tool moments were risky.
- Which recovery actions fired.
- Whether a run halted or escalated.
- Whether sensors failed or produced gaps.

This matters because enterprise governance needs human review, not only hidden
automation.

### Auditable Control

Control is auditable when the record can be checked after the fact.

OpenGuide uses hash-chained traces so that behavioral records can be verified.
If a record is edited, removed, or reordered, trace verification fails.

Auditable control means the enterprise can reconstruct:

- What policy was active.
- What the agent did.
- What the runtime observed.
- When drift occurred.
- What decision was made.
- Whether the trace is intact.

## What It Can Govern

OpenGuide can govern both behavior and action-adjacent state.

### Behavioral Scope

Examples:

- Stay within the assigned task.
- Do not expand scope without approval.
- Preserve the system and user hierarchy.
- Do not obey untrusted retrieved instructions.
- Maintain tenant-specific tone and boundaries.
- Cite approved sources before making claims.

### Tool-Use Discipline

Examples:

- Do not call production-write tools before validation.
- Do not run destructive operations without escalation.
- Do not update CRM records if confidence is below a floor.
- Do not call external systems when sensor gaps are present.
- Require human approval for high-risk actions.

### Process Gates

Examples:

- Tests must pass before commit.
- Customer identity must be verified before account changes.
- Source approval must pass before financial or legal advice.
- Ticket classification must be complete before routing.
- Data sensitivity must be classified before summarization.

### Runtime Risk Signals

Examples:

- Instruction adherence is falling.
- Context obedience is rising above user adherence.
- The agent is repeatedly triggering recovery.
- Required sensors are unavailable.
- The run is approaching a halt threshold.

## Example: Agent Updating Salesforce

```text
Agent wants to update Salesforce.
        |
        v
OpenGuide reads the active contract.
        |
        v
OpenGuide checks:
- Is this tenant allowed to use this action?
- Is the action inside the declared task scope?
- Has instruction adherence stayed above the floor?
- Did required customer verification happen?
- Is this action high risk?
- Are any required sensors missing?
        |
        v
Decision:
- Continue
- Re-anchor and retry
- Escalate to human review
- Halt the run
        |
        v
Decision and state are recorded in a tamper-evident trace.
```

The enterprise value is that the agent's action is not just an opaque tool call.
It is part of a governed, reviewable trajectory.

## Example: Coding Agent Changing a Repository

A coding agent can be governed by a contract requiring:

- Edits only inside declared paths.
- No force push.
- Tests before commit.
- Escalation before destructive filesystem operations.
- Halt if instruction adherence falls below the threshold.

OpenGuide records:

- The active contract hash.
- Each turn's adherence and structural checks.
- The drift score.
- Re-anchor events.
- Escalation or halt decisions.
- Trace verification status.

This gives engineering leadership and security teams a post-run artifact that
is stronger than normal chat logs.

## Example: Browsing Agent Facing Prompt Injection

A browsing agent can be governed by a contract requiring user-instruction
adherence to stay above context obedience.

Risk pattern:

- User adherence decreases.
- Context obedience increases.
- The agent begins following page instructions rather than user instructions.

OpenGuide can treat that behavioral state shape as a prompt-injection signal,
then re-anchor, escalate, or halt before a risky action is taken.

## Enterprise Control Points

OpenGuide can support control at several points in the agent lifecycle.

### Before the Run

- Validate the contract.
- Check model capability against enforcement floor.
- Bind the run to a contract hash.
- Record identity, tenant, model, and runtime metadata.

### During the Run

- Measure invariant readings.
- Detect drift.
- Validate hard rules.
- Detect trigger tokens or risky state transitions.
- Inject re-anchor text when appropriate.
- Record recovery decisions.

### Before Tool Action

The current repo is strongest around model-call governance and behavioral
tracing. For full enterprise action governance, OpenGuide should be extended to
gate tool calls explicitly.

A production version should support:

- Tool risk classification.
- Tool allowlists and denylists.
- Pre-action invariant checks.
- Required approvals.
- Escalation workflow integration.
- Per-tool audit records.

### After the Run

- Verify the trace.
- Review drift timeline.
- Inspect recovery decisions.
- Export compliance evidence.
- Compare behavior across models, contracts, or tenants.

## Relationship to Corporate Systems

OpenGuide should not replace systems of record, IAM, SIEM, DLP, GRC, or
workflow engines. It should integrate with them.

| Enterprise system | Relationship |
|---|---|
| IAM / SSO | Identifies users, service accounts, and tenants |
| Agent runtime | Supplies messages, actions, and tool-call context |
| LLM gateway | Routes model calls through governed proxy paths |
| Tool gateway | Enforces action-level policy and approvals |
| Observability | Receives drift, recovery, and trace metrics |
| SIEM | Receives high-risk drift and halt/escalation events |
| GRC | Consumes contracts, reports, and audit evidence |
| Data stores | Provide durable trace and fleet index storage |

The strongest architecture is layered: IAM authenticates, tool gateways enforce
resource permissions, and OpenGuide governs behavioral state and action risk.

## Enterprise Architecture Pattern

```text
                         +----------------------+
                         | Compliance / GRC     |
                         | audit reports        |
                         +----------^-----------+
                                    |
                         +----------+-----------+
                         | Observability / SIEM |
                         | drift, recovery      |
                         +----------^-----------+
                                    |
+-----------+     +-----------------+-----------------+     +-------------+
| Users and | --> | Agent runtime / workflow engine    | --> | Tool APIs   |
| systems   |     +-----------------+-----------------+     | CRM, DB, CI |
+-----------+                       |                       +-------------+
                                    v
                         +----------+-----------+
                         | OpenGuide            |
                         | contracts, drift,    |
                         | recovery, trace      |
                         +----------+-----------+
                                    |
                                    v
                         +----------+-----------+
                         | LLM provider or      |
                         | inference runtime    |
                         +----------------------+
```

## Adoption Model

### Phase 1: Passive Runtime Evidence

Run OpenGuide in observe-only mode for selected agent workflows.

Purpose:

- Establish baseline drift.
- Validate sensors.
- Produce trace records.
- Build trust with platform and risk teams.

### Phase 2: Reactive Re-Anchoring

Enable T2 re-anchoring when drift crosses thresholds.

Purpose:

- Reduce avoidable drift.
- Compare against naive fixed-cadence prompting.
- Quantify token and cost overhead.

### Phase 3: Escalation and Halt

Enable escalation and halt policies for risky workflows.

Purpose:

- Prevent agents from continuing when behavioral risk is high.
- Route high-risk moments to human review.
- Build an incident review workflow.

### Phase 4: Tool-Action Governance

Integrate OpenGuide with the tool gateway or agent runtime so tool calls can be
checked before execution.

Purpose:

- Govern real corporate actions.
- Require approvals for high-risk tools.
- Record action-level audit decisions.

### Phase 5: Fleet Governance

Aggregate runs across teams, tenants, models, and contracts.

Purpose:

- Compare model reliability.
- Find risky workflows.
- Tune contracts.
- Provide executive and compliance reporting.

## Enterprise Readiness Requirements

The current repo is a credible foundation, but a production enterprise
governance layer needs additional hardening.

## But Not Yet Fully As-Is

The current project is a credible foundation, but it is not yet the complete
enterprise layer that can safely authorize autonomous agents to take real action
against corporate systems.

To become that layer, OpenGuide needs hardening around:

- Identity and session isolation.
- RBAC and admin authentication.
- Policy approval workflows.
- Persistent production storage.
- Tool-call authorization gates.
- Redaction and privacy modes.
- SIEM and GRC integrations.
- Human-in-the-loop escalation.
- Immutable trace storage.
- Real enterprise benchmarks.
- Deployment hardening.

The important distinction is that the current repo proves the architecture:
contracts, tier resolution, drift measurement, recovery, proxy activation,
telemetry, storage primitives, and hash-chained traces. The enterprise product
still needs the surrounding security, tenancy, approval, persistence, and
integration layers that large organizations require before allowing agents to
touch systems of record.

## Hardening Backlog

| Area | Needed capability | Why it matters |
|---|---|---|
| Identity and session isolation | Generated anonymous sessions now prevent accidental no-header session sharing; remaining work is tenant-aware sessions, user identity, service-account identity, and signed run metadata | Prevents cross-user or cross-tenant behavioral state bleed |
| RBAC and admin authentication | Optional admin-token protection now gates control-plane endpoints; remaining work is enterprise RBAC, SSO, scoped roles, and policy-management permissions | Prevents unauthorized policy changes or audit access |
| Policy approval workflows | Draft, review, approve, deploy, retire, and diff contracts | Makes behavioral policy governable by risk, security, and platform teams |
| Persistent production storage | The local compose stack now uses a persisted sqlite volume that matches the implemented backend; remaining work is Postgres or equivalent durable fleet index plus durable trace metadata | Makes run history survive restarts and support enterprise reporting |
| Tool-call authorization gates | Optional proxy-side allowlist, denylist, and approval-required name patterns are now available via `OPENGUIDE_TOOL_ALLOWLIST`, `OPENGUIDE_TOOL_DENYLIST`, and `OPENGUIDE_TOOL_REQUIRE_APPROVAL`; remaining work is richer risk classes, scoped arguments, external approval services, and tool gateway integrations | Lets OpenGuide govern real corporate actions, not only model messages |
| Redaction and privacy modes | Metadata-only trace responses are now available with `?metadata_only=true`; remaining work is prompt/output hashing, PII redaction, and retention controls | Allows use in sensitive regulated environments |
| SIEM and GRC integrations | Events, evidence bundles, compliance exports, policy status feeds | Makes OpenGuide consumable by existing enterprise control systems |
| Human-in-the-loop escalation | Escalation queues, approver identity, decision records, timeout handling | Creates a safe path for high-risk or uncertain agent actions |
| Immutable trace storage | Trace snapshots are now persisted into the content-addressed store every governed turn; remaining work is append-only object storage, object lock, signed trace bundles, and retention policy | Strengthens audit defensibility beyond in-process hash verification |
| Real enterprise benchmarks | Real-data SEC EDGAR and CISA KEV corporate reference demos now exercise proxy action governance over public company and cyber-risk facts; remaining work is closed-model and open-model evaluations on realistic tool-using partner workflows | Proves value beyond simulated harnesses |
| Deployment hardening | Streaming assembly now buffers split SSE lines and UTF-8 sequences; remaining work is Helm/Kubernetes, HA, secrets handling, observability, backup/restore, and upgrade paths | Makes the system operable by enterprise platform teams |

### Identity and Access Control

Required:

- Generated anonymous sessions for governed requests without explicit session
  headers. Implemented in the proxy to avoid accidental shared anonymous state.
- Optional admin-token protection for control-plane endpoints. Implemented for
  `/v1/openguide/*` when `OPENGUIDE_ADMIN_TOKEN` is configured.
- SSO integration.
- RBAC for contract management and trace review.
- Tenant-aware session isolation.
- Service-account identity for agents.
- Signed run metadata.

### Durable Storage

Required:

- Production database support.
- Persisted sqlite storage in the local compose stack. Implemented at
  `/data/openguide.db`.
- Current trace snapshots are persisted into CAS every governed turn and can be
  reloaded from the run index after the in-memory session is gone.
- Immutable or append-only trace storage.
- Retention policies.
- Backup and restore.
- Queryable fleet index.

### Tool Governance

Required:

- Tool-call interception. Implemented for OpenAI-style assistant `tool_calls`
  in non-streaming responses and, when a tool policy is configured, streaming
  responses are preflight-buffered so denied calls can be blocked before bytes
  are returned to the client.
- Allowlist and denylist checks. Implemented with comma-separated tool-name
  patterns through `OPENGUIDE_TOOL_ALLOWLIST` and `OPENGUIDE_TOOL_DENYLIST`.
- Approval-required checks. Implemented as a deny decision with an
  `approval_required:*` reason through `OPENGUIDE_TOOL_REQUIRE_APPROVAL`;
  a real human approval workflow is still needed.
- Action-level audit events. Implemented as `TOOL_POLICY` trace events that
  record tool id, tool name, decision, and reason without storing tool
  arguments.
- Risk classification.
- Scoped argument validation.
- External tool gateway integration.
- Approval workflows.
- Deny and halt paths tied into contract recovery state.

### Privacy and Data Protection

Required:

- Trace redaction.
- Metadata-only trace mode. Implemented on
  `/v1/openguide/runs/{run_id}/trace?metadata_only=true`, returning manifest,
  head hash, CAS key, verification status, record count, and event counts
  without the raw `records` array.
- Prompt and output hashing options.
- PII handling policy.
- Data residency support.
- Customer-controlled retention.

### Reliability

Required:

- Sensor timeouts.
- Circuit breakers.
- Degraded-mode behavior.
- Streaming robustness. Split SSE lines and split UTF-8 sequences are now
  buffered by the proxy stream assembler; production still needs broader
  upstream-format and backpressure testing.
- Backpressure handling.
- High availability deployment patterns.

### Compliance Integration

Required:

- Exportable audit reports.
- SIEM events.
- GRC integration points.
- Evidence bundles per run.
- Policy approval workflow.
- Contract version lifecycle.

## What OpenGuide Should Claim

Strong claims:

- OpenGuide makes agent behavior contract-bound and traceable.
- OpenGuide records drift, recovery, and policy state across a run.
- OpenGuide provides auditable runtime evidence for agentic workflows.
- OpenGuide can reduce behavioral drift when recovery policies are effective.
- OpenGuide lets teams compare models and contracts under the same behavioral
  policy.

Claims to avoid:

- OpenGuide guarantees safe AI behavior.
- OpenGuide prevents all policy violations.
- OpenGuide replaces IAM, DLP, SIEM, GRC, or approval workflows.
- OpenGuide has proven open-weight capability retention before real evals.
- OpenGuide is production-enterprise-ready without additional hardening.

## Why It Matters for Enterprise AI

Enterprises are hesitant to let agents take real action because normal AI
systems lack durable control. OpenGuide can help close that gap by making agent
behavior:

- Declared through contracts.
- Measured at runtime.
- Corrected when drift appears.
- Interrupted when risk is too high.
- Recorded in a verifiable trace.
- Reviewed across fleets of runs.

This is the difference between an agent that merely has instructions and an
agent that operates under runtime governance.

## Bottom Line

Yes, OpenGuide can be positioned as an enterprise governance layer for agentic
AI. That is one of its strongest strategic uses.

The current implementation demonstrates the foundation: contracts, tiers,
sensors, drift reconciliation, recovery, proxy activation, telemetry, and
hash-chained traces. To fully become the layer that lets autonomous agents take
real action against corporate systems, the next product step is action-level
governance: identity, tool-call gates, approvals, immutable storage, tenant
isolation, redaction, and compliance integrations.

The durable thesis is:

> Enterprises will not trust autonomous agents with corporate action unless
> those agents operate under runtime contracts, reviewable decisions, and
> auditable traces. OpenGuide is built to be that control layer.
