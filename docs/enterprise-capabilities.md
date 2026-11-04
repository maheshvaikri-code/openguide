# OpenGuide Capabilities, Enterprise Usage, and Adoption Case

This document summarizes what OpenGuide can do, where it fits, how enterprises
could use it, and what must mature before production adoption.

For the sharper agentic-AI governance framing, see
[`enterprise-governance-layer.md`](enterprise-governance-layer.md).

## Executive Summary

OpenGuide is an open control plane for AI agent behavior. It lets teams declare
how an agent should behave, observe whether the agent is drifting from that
declared behavior, intervene when needed, and retain a tamper-evident trace of
the run.

The best current positioning is:

> OpenGuide provides behavioral contracts, drift monitoring, recovery, and
> tamper-evident traces for enterprise AI workflows.

A stronger enterprise agentic-AI positioning is:

> OpenGuide lets autonomous AI agents act inside enterprise systems under
> contract-bound, auditable runtime control.

It should not be positioned as a system that guarantees LLM behavior. A more
accurate and credible claim is that it detects, records, and statistically
steers behavior against declared contracts.

The project is worth pursuing if the target market is enterprise AI governance,
AI agent observability, auditability, compliance evidence, and reliability for
long-running agent workflows. It is currently strongest as a reference
implementation and enterprise prototype. It needs more production hardening
before it is ready as an enterprise-grade proxy.

## The Problem It Addresses

Most enterprise AI governance happens outside the agent trajectory:

- Prompts are reviewed before execution.
- Outputs are checked after execution.
- Access policies surround the model.
- Logs are inspected after something goes wrong.

That leaves a gap during the actual run. Long-running agents can drift across
turns, lose instruction adherence, over-obey retrieved context, ignore tenant
policy, skip process gates, or continue after they should have escalated.

OpenGuide addresses that gap by creating a closed loop:

1. Declare desired behavior.
2. Measure actual behavior during the run.
3. Reconcile drift against setpoints.
4. Apply recovery actions.
5. Record the behavioral state and interventions in a verifiable trace.

This changes the enterprise question from:

> Did the final answer violate policy?

to:

> When did the agent begin drifting, what did it drift from, what intervention
> fired, did it recover, and can we verify the record?

## Core Concepts

### Open Behavioral Contract

An Open Behavioral Contract, or OBC, defines the expected behavior of an agent.
It can include:

- Invariants: behavior that should hold across a run.
- Floors: minimum acceptable scores for soft behavioral measures.
- Hard checks: structural requirements that must pass.
- Phases: different behavior expectations across different parts of a run.
- Triggers: events that activate specific signals.
- Recovery actions: what to do when drift crosses thresholds.
- Signals: the steering or re-anchoring surfaces available to the runtime.

Example enterprise invariants:

- The agent must stay inside the approved task scope.
- The agent must not write files outside declared paths.
- The agent must not commit before tests pass.
- The support agent must preserve tenant tone and escalation policy.
- The browsing agent must obey user intent over untrusted page content.
- The finance assistant must cite approved sources before producing advice.

### GuidanceGrid Runtime

GuidanceGrid is the reference runtime. It compiles contracts into the strongest
available enforcement channel for the target model and records behavioral state
for each turn.

Its important responsibilities are:

- Resolve model capabilities.
- Compile OBC contracts into runtime artifacts.
- Read typed sensors.
- Compute drift.
- Trigger recovery.
- Emit re-anchor text when appropriate.
- Append state records into the hash-chained trace.

### Enforcement Tiers

OpenGuide uses a tiered model so one contract can run across open-weight and
closed API models.

| Tier | Capability | Typical target | Status |
|---|---|---|---|
| T0 | Activation steering | Open-weight models | Steering scaffold implemented; real-model evals pending |
| T1 | Constrained decoding | Local/open models | Dependency-light masking implemented; production backend optional |
| T2 | Text re-anchoring | Closed APIs and proxies | Most practical current enterprise tier |
| T3 | Validation | Any model | Practical for structural checks and audit |

For near-term enterprise use, T2 and T3 are the most relevant because they work
with OpenAI-compatible closed APIs and do not require model weights.

### Behavioral State

Each turn produces behavioral state:

- Active tier.
- Invariant readings.
- Drift score.
- Active signals.
- Recovery action, if any.
- Sensor gaps.
- Validation failures.
- Trace head.

This turns behavior into observable runtime state rather than informal prompt
intent.

### Hash-Chained Trace

Each behavioral state record is appended into a hash chain. Any mutation,
deletion, or reordering breaks verification.

For enterprises, this supports:

- Audit trails.
- Incident review.
- Run replay.
- Compliance evidence.
- Behavior provenance.
- Contract version accountability.

The trace is not just logging. It is a verifiable record of which behavioral
contract was active, what the runtime observed, and what actions were taken.

## Current Capabilities

### Contract Authoring and Validation

OpenGuide supports OBC contracts authored in TOML and validated against a JSON
Schema. Contracts can describe identity, boundaries, invariants, phases,
triggers, recovery actions, and signal bindings.

Value:

- Behavior becomes explicit and versioned.
- Different teams can review behavioral policy separately from application code.
- The same contract can be tested against different models or providers.

### Capability Resolution

The compiler selects the strongest enforcement tier supported by the target
model while respecting the contract's minimum enforcement floor.

Value:

- One contract can run across providers.
- The runtime refuses to silently degrade below the required floor.
- Enterprises can compare model providers against the same behavioral policy.

### Typed Sensors

The sensor layer supports:

- Structural measures.
- External measures.
- Judge measures.
- Linear probe measures for open-weight tiers.

Sensor failures become recorded sensor gaps rather than data-plane failures.

Value:

- Enterprises can integrate deterministic checks, business metrics, or LLM
  judges.
- Missing or failed sensors are visible.
- Production traffic is less likely to be blocked by control-plane issues.

### Drift Reconciliation

The reconciler computes drift from weighted invariant violations and dispatches
recovery actions when thresholds are crossed.

Value:

- Behavioral degradation becomes measurable.
- Recovery can be reactive instead of fixed cadence.
- Teams can identify contracts that are too weak or too strict.

### Recovery Actions

The current recovery model supports:

- Re-anchor.
- Escalate.
- Halt.

Value:

- Agents can be nudged back toward the declared contract.
- High-risk drift can trigger escalation or stop conditions.
- Recovery decisions are recorded in the trace.

### OpenAI-Compatible Proxy

The proxy supports OpenAI-compatible chat completions. Governance is activated
with a header:

```text
X-OpenGuide-Contract: <contract_hash>
```

Value:

- Existing applications can adopt governance without deep code changes.
- Pass-through remains the default.
- The proxy becomes a practical enterprise wedge.

### Streaming Support

The proxy handles streaming Server-Sent Events and reassembles assistant
messages and tool-call deltas for behavioral analysis.

Value:

- Governance can work with streaming applications.
- Tool-call behavior can be inspected after stream assembly.

### Observability and OTel

The proxy emits `gen_ai.behavior.*` telemetry.

Value:

- Behavioral state can flow into existing observability systems.
- AI runs can be monitored alongside infrastructure and application metrics.
- Enterprises can build dashboards over drift, recovery, and validation status.

### Store and Fleet Index

The runtime includes a SQLite-backed content-addressed store and fleet index.

Value:

- Runs can be queried by contract, model, tier, drift, recovery count, or halt
  status.
- This is the foundation for a future console and enterprise fleet view.

### Conformance Vectors

The spec includes conformance vectors for canonical encoding, trace chain
verification, and contract compilation.

Value:

- Other implementations can verify compatibility.
- The standard is not tied only to the Python runtime.
- Determinism is testable.

### Simulated Benchmarks

The repo includes simulated benchmark harnesses for:

- Re-anchoring versus naive re-prompting.
- Governed versus ungoverned drift.
- Fleet generation.
- Injection-detection scenarios.

Value:

- The methodology is wired end to end.
- The results are clearly labeled simulated.
- The harnesses can be replaced with real closed-model and open-model results.

### Real-Data Corporate Reference Demos

The repo now includes real-data reference demos that run scripted corporate
agents through the OpenAI-compatible proxy using public internet data.

`examples/corporate-edgar/` shows:

- Public corporate data ingestion from the SEC EDGAR API.
- Extraction of latest annual revenue and net income facts.
- Evidence-grounded behavioral checks.
- An allowed `crm.create_account_note` tool call.
- A blocked `erp.update_vendor_risk` tool call with an
  `approval_required:*` decision.
- A verified trace containing both behavioral `STATE` records and
  action-level `TOOL_POLICY` records.

`examples/cyber-kev/` shows:

- Public cyber-risk data ingestion from CISA's Known Exploited Vulnerabilities
  catalog.
- Extraction of recent CVE, vendor, product, date-added, due-date, and required
  action fields.
- Evidence-grounded behavioral checks.
- An allowed `siem.create_case` tool call.
- A blocked `edr.isolate_host` tool call with an `approval_required:*`
  decision.
- A verified trace containing both behavioral `STATE` records and
  action-level `TOOL_POLICY` records.

Run them with:

```bash
make corporate-demo
make cyber-demo
```

These are not real-model benchmarks. They are corporate reference
implementations that demonstrate how OpenGuide can sit between agents and
systems of record while using real public company and cyber-risk data.

## Enterprise Use Cases

### AI Agent Governance

Enterprises can define contracts for agents that perform multi-step work.

Example:

- A coding agent must stay inside a declared scope, run tests before commit, and
  halt if instruction adherence collapses.
- A support agent must preserve tone, follow escalation rules, and avoid
  disallowed commitments.
- A research agent must cite approved sources and avoid acting on untrusted
  instructions.

OpenGuide provides the contract, measurement, recovery, and trace layer around
those agents.

### Audit and Compliance

Regulated enterprises need evidence of what happened during AI-assisted
workflows. OpenGuide can record:

- Which contract was active.
- Which model and tier were used.
- Which invariants passed or failed.
- When drift crossed a threshold.
- Which recovery action fired.
- Whether the trace verifies.

This can support internal review, compliance reporting, customer assurance, and
post-incident analysis.

### Long-Running Agent Reliability

Long-running agents are prone to gradual behavioral drift. OpenGuide gives
teams a way to track adherence over the life of a run, not just at the final
answer.

Useful metrics include:

- Maximum drift.
- Turns in violation.
- Recovery count.
- Halt rate.
- Sensor gap rate.
- Drift by model, tenant, contract, or workflow.

### Multi-Tenant Behavior Control

The same model can serve different tenants with different contracts.

Example:

| Tenant | Contract emphasis |
|---|---|
| Healthcare | Conservative answers, uncertainty escalation, source discipline |
| Finance | Approved data sources, audit language, no unsupported advice |
| Retail support | Warm tone, quick resolution, handoff on refunds above threshold |
| Internal engineering | Scope control, test gates, no destructive commands |

This lets enterprises treat behavior as configuration instead of hard-coded
application logic.

### Prompt-Injection Detection

Browsing and retrieval agents can be monitored for divergence between user
adherence and context obedience.

If an agent begins obeying retrieved page instructions more than the user's
instructions, that behavioral state shape can be treated as a risk signal.

OpenGuide's value here is not only blocking known bad strings. It can detect a
shift in behavioral alignment during the run.

### Model and Provider Evaluation

The same OBC can be run against multiple models:

- OpenAI-compatible closed APIs.
- Anthropic-compatible systems through adapters.
- Local open-weight models.
- Mock models for repeatable tests.

This supports procurement and model governance:

- Which model drifts less under the same contract?
- Which provider requires fewer recovery actions?
- Which models produce more sensor gaps?
- Which model is cheapest at equal behavioral reliability?

### Change Management

Enterprises can compare runs across:

- Contract versions.
- Model versions.
- Prompt versions.
- SignalPack versions.
- Sensor versions.

This helps answer what changed when agent behavior regressed.

## How Enterprises Could Adopt It

### Stage 1: Observability-Only Pilot

Start with T3 validation and passive behavioral state recording.

Goals:

- Identify drift patterns.
- Measure sensor gaps.
- Build trust in traces.
- Avoid changing agent outputs at first.

Best for:

- Security teams.
- AI platform teams.
- Compliance teams.
- Teams skeptical of automatic intervention.

### Stage 2: T2 Re-Anchoring

Enable reactive re-anchoring for selected workflows.

Goals:

- Reduce drift.
- Compare reactive re-anchoring against naive periodic prompting.
- Measure token overhead.
- Track recovery effectiveness.

Best for:

- Coding agents.
- Support agents.
- Research agents.
- Operations agents.

### Stage 3: Fleet Monitoring

Aggregate runs across teams, tenants, models, and contracts.

Goals:

- Build dashboards.
- Detect high-risk workflows.
- Compare model/provider behavior.
- Identify contracts that need tuning.

Best for:

- Central AI platform organizations.
- Enterprise architecture teams.
- Risk and compliance teams.

### Stage 4: Enforcement and Escalation

Use halt and escalation policies for high-risk workflows.

Goals:

- Stop risky runs.
- Route incidents to humans.
- Produce audit reports.
- Enforce hard structural gates.

Best for:

- Regulated workflows.
- Customer-facing agents.
- Agents with tool access.
- Agents that can modify systems of record.

### Stage 5: Open-Weight Steering

For enterprises running their own models, evaluate T0 and T1.

Goals:

- Use activation steering and constrained decoding.
- Measure capability retention.
- Publish internal eval cards.
- Treat behavior packs as deployment artifacts.

Best for:

- AI labs.
- Model platform teams.
- Enterprises running vLLM, HF, or llama.cpp infrastructure.

## Enterprise Value

### Better Control Over Agent Drift

Instead of relying only on stronger prompts, teams can observe drift and respond
when it happens.

### More Credible AI Governance

Policies become executable contracts with traceable runtime behavior.

### Audit-Ready AI Runs

The trace gives enterprises a verifiable account of behavioral state and
recovery actions.

### Faster Incident Review

Teams can inspect when drift started, what sensor changed, and what recovery
action fired.

### Cross-Model Portability

The same contract can compile to different enforcement tiers depending on the
model.

### Better Procurement Data

Enterprises can compare model vendors based on behavioral reliability, not only
latency, cost, or benchmark scores.

### Safer Tool-Using Agents

Agents with tools can be governed by structural gates, trigger detection, and
halt/escalation rules.

### Tenant-Specific Behavior

Behavior can become a versioned deployment artifact per tenant, workflow, or
business unit.

## What Makes It Different

### Versus LLM Observability

Traditional observability watches and reports. OpenGuide watches, reconciles,
acts, and records.

Observability answers:

> What happened?

OpenGuide aims to answer:

> What was supposed to happen, how did the agent drift, what correction fired,
> and can we verify the record?

### Versus Guardrails

Guardrails often validate inputs or outputs at boundaries. OpenGuide tracks
behavior across the trajectory.

Guardrails are usually gate-oriented. OpenGuide is loop-oriented.

### Versus Prompt Engineering

Prompt engineering is open loop. OpenGuide makes re-anchoring conditional on
measured behavioral state.

Prompting says:

> Remind the model what to do.

OpenGuide says:

> Remind the model when drift shows the reminder is needed, and record that it
> happened.

### Versus Model Evals

Model evals are usually offline. OpenGuide brings behavioral measurement into
runtime.

Evals answer:

> How did this model perform on a benchmark?

OpenGuide answers:

> How is this specific agent run behaving right now under this specific
> contract?

### Versus AI Governance Platforms

Many governance tools manage policy, approval, inventories, and reporting.
OpenGuide focuses on runtime behavior.

The strongest enterprise version is not a replacement for governance platforms.
It is a runtime evidence and control layer they can consume.

## Is It Worth Pursuing?

Yes, if the project focuses on the right wedge.

The strongest wedge is not "we guarantee LLM behavior." That claim is too broad
and technically fragile.

The strongest wedge is:

> Enterprises need runtime behavioral observability and auditability for
> long-running AI agents, and OpenGuide gives them contracts, drift state,
> recovery, and tamper-evident traces.

Reasons it is worth pursuing:

- Agent workflows are becoming longer and more autonomous.
- Enterprises need governance that works during execution, not only before and
  after.
- Existing observability tools do not usually model declared behavior versus
  actual behavior.
- Audit and compliance requirements are increasing.
- The proxy adoption model is practical.
- The spec-first approach can create ecosystem leverage.
- The honest simulated benchmark framing preserves credibility.

Reasons to be cautious:

- Real-model evidence is still needed.
- Enterprise security and tenancy hardening are not complete.
- T0/T1 steering must prove capability retention on real models.
- T2 re-anchoring may be matched by simpler baselines in some workloads.
- The category is still emerging and requires careful messaging.

The project is promising if it treats falsifiability as a strength. If naive
re-prompting matches contract-driven re-anchoring at equal cost on real tasks,
OpenGuide should still be valuable as observability, traceability, and runtime
governance infrastructure.

## Enterprise Adoption Readiness

### Ready Today

The current repo is ready for:

- Technical demos.
- Internal prototypes.
- Research pilots.
- Mock-agent simulations.
- Spec and architecture review.
- Offline governance experiments.
- Early closed-model proxy pilots in controlled environments.

### Not Yet Ready Without More Work

The current repo needs additional work before broad enterprise production use:

- Strong authentication and authorization for proxy and admin endpoints.
  Optional admin-token protection now gates `/v1/openguide/*` endpoints when
  configured; enterprise SSO/RBAC is still needed.
- Identity and session isolation. Anonymous governed calls are now isolated by
  generated session ids; tenant-aware persistent session identity is still
  needed.
- RBAC and admin authentication. Basic admin-token protection exists; scoped
  enterprise RBAC is still needed.
- Policy approval workflows.
- Persistent production-grade session storage.
- Persistent production-grade fleet and trace storage. The local compose stack
  now uses a persisted sqlite volume instead of claiming unsupported Postgres,
  and governed turns persist current trace snapshots into CAS.
- Real Postgres support.
- Tool-call authorization gates. Optional proxy-side allowlist, denylist, and
  approval-required name patterns now exist through
  `OPENGUIDE_TOOL_ALLOWLIST`, `OPENGUIDE_TOOL_DENYLIST`, and
  `OPENGUIDE_TOOL_REQUIRE_APPROVAL`; richer risk classes, scoped argument
  validation, and external approval services are still needed.
- Broader streaming hardening. Fragmented SSE lines and split UTF-8 sequences
  are now buffered; upstream-format coverage and backpressure behavior still
  need production hardening.
- Sensor timeouts, retries, and circuit breakers.
- Content redaction and metadata-only trace modes. Metadata-only trace responses
  now exist via `/v1/openguide/runs/{run_id}/trace?metadata_only=true`; broader
  redaction and hashing remain needed.
- SIEM and GRC integrations.
- Human-in-the-loop escalation.
- Immutable trace storage.
- Secrets handling and deployment hardening.
- Kubernetes and cloud deployment guidance.
- Real closed-model benchmark results.
- Real enterprise benchmarks against tool-using workflows. Real-data SEC EDGAR
  and CISA KEV corporate reference demos now exist; broader enterprise
  benchmarks still need real models, real tools, and partner workloads.
- Real open-weight capability-retention evals.
- Clear API versioning and compatibility guarantees.

## Recommended Product Positioning

Use different language for different audiences while keeping the same technical
truth.

### For AI Platform Teams

> A behavioral control plane for AI agents.

### For Observability Buyers

> Behavioral observability for long-running AI agents, with drift, recovery,
> and trace verification.

### For Governance and Risk Teams

> Executable AI behavior contracts with audit-ready runtime evidence.

### For Engineering Teams

> An OpenAI-compatible proxy that adds contract-based monitoring and recovery
> without rewriting the app.

### Avoid

Avoid claims such as:

- Guaranteed safe AI behavior.
- Complete prevention of hallucination.
- Universal enforcement across all models.
- Proven capability retention before real evals exist.
- Replacement for all governance, security, or compliance tooling.

## Recommended First Enterprise Pilot

A strong first pilot would be a long-running internal coding or support agent.

### Pilot Scope

- One team.
- One workflow.
- One or two contracts.
- T2/T3 only.
- Passive mode for the first phase.
- Reactive re-anchor in the second phase.
- Human review of all halt/escalation events.

### Pilot Metrics

- Drift rate.
- Turns in violation.
- Recovery count.
- Recovery success rate.
- Halt rate.
- Sensor gap rate.
- Token overhead.
- Cost overhead.
- Incident review time.
- Difference versus naive fixed-cadence re-prompting.

### Pilot Success Criteria

The pilot is successful if it shows at least one of:

- Earlier detection of risky agent behavior.
- Better audit trail than existing logs.
- Lower drift at comparable token cost.
- Useful model/provider comparison data.
- Clear evidence for when an agent should escalate or halt.
- Reduced incident investigation time.

## Roadmap Toward Enterprise Grade

### Near Term

- Extend session identity from generated anonymous isolation to tenant-aware,
  persistent session identity.
- Add production Postgres support beyond the current persisted sqlite compose
  stack.
- Harden streaming assembly.
- Add auth to governance endpoints.
- Extend the new tool-call authorization gate into argument-aware tool gateway
  enforcement and real approval workflows.
- Add sensor timeout and retry policy.
- Extend metadata-only trace mode into configurable redaction, prompt/output
  hashing, and retention controls.
- Load and apply declared T2 templates.
- Improve README wording around simulated and pending real-model results.

### Medium Term

- Build the Console fleet and run views.
- Add Postgres-backed fleet index and trace metadata.
- Add policy packs for common workflows.
- Add real closed-model benchmark results.
- Add security documentation.
- Add SIEM and observability integrations.
- Add exportable audit reports.

### Long Term

- Real T0/T1 eval cards for supported open-weight models.
- SignalPack registry with compatibility metadata.
- vLLM or inference-server integrations.
- Kubernetes operator or Helm chart.
- Enterprise SSO and RBAC.
- Compliance-oriented retention policies.
- Formal OBC versioning and governance process.

## Bottom Line

OpenGuide is a strong idea with a coherent architecture and a credible early
implementation. Its enterprise value is highest where AI agents are long
running, tool-using, customer-facing, regulated, or expensive to investigate
after failure.

It can bring a meaningful shift to enterprise AI:

- From prompts to behavioral contracts.
- From final-output checks to trajectory monitoring.
- From ordinary logs to verifiable traces.
- From static governance to runtime reconciliation.
- From model-only evaluation to model-plus-contract evaluation.

The project is worth pursuing if it continues to be honest about what is
simulated, what is proven, and what remains to be validated on real workloads.
