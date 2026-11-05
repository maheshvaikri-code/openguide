# OpenGuide

**A behavioral control plane for AI agents.**

OpenGuide explores how teams can define expected agent behavior, monitor it over
time, and record the resulting decisions. Its reference runtime, **GuidanceGrid**,
compiles behavioral contracts for different model capabilities. An
OpenAI-compatible proxy brings these controls to chat-based workflows.

[Get started](#get-started) | [How it works](#how-it-works) | [Corporate demos](#corporate-demos) | [Evidence and roadmap](#evidence-and-roadmap) | [Documentation](#documentation)

> **Project status:** Research and reference implementation, not a complete
> enterprise security gateway. Benchmarks are simulated, and the corporate
> demos use real public data with scripted agents and simulated tool calls.

## Why OpenGuide?

AI agents increasingly make decisions across long workflows and propose actions
in business systems. Teams need to understand whether an agent is staying within
its intended boundaries, what happened when it drifted, and which actions were
allowed or blocked.

OpenGuide combines three ideas in one project:

- **Behavior as a contract:** Declare invariants, phases, triggers, and recovery
  actions in an Open Behavioral Contract (OBC).
- **A feedback loop:** Measure behavioral signals, detect drift, and generate
  a re-anchor or other recovery decision as the workflow progresses.
- **Reviewable evidence:** Record runtime state and supported tool-policy
  decisions in a hash-chained trace that can be verified and inspected.

For AI platform, security, and risk teams, the opportunity is to connect
behavioral observability with runtime control. For developers, the repository
provides an executable runtime, a proxy, contracts, examples, and test fixtures
to explore that approach.

## How it works

```text
  Agent / application
          |
          v
  OpenGuide proxy <---- OBC contract + sensors + tool-name policy
          |
          +-----------> Behavioral state, telemetry, and trace
          |
          v
  Model provider -----> Proposed response / tool call
          |
          v
  Application or tool gateway -----> Corporate systems
```

1. Register or load an OBC contract describing expected behavior.
2. Send a request to the proxy with `X-OpenGuide-Contract` and, for continuity,
   `X-OpenGuide-Session`.
3. The runtime measures the response, records behavioral state, and can prepare
   re-anchoring text for a later turn.
4. For governed requests, an optional proxy policy can allow or deny supported
   model-proposed tool calls by name. Decisions are recorded in the trace.

The application or a separate tool gateway remains responsible for executing
and authorizing actions against corporate systems. Governance is opt-in: requests
without a contract header pass through the proxy without these controls. The
proxy does not enforce actions that bypass it. See [enterprise governance](docs/enterprise-governance-layer.md)
for the trust boundary and outstanding work.

## Get started

**Prerequisites:** Python 3.10 or later. The proxy quickstart uses FastAPI and
HTTPX; the development extra also installs the test and lint tools.

From the repository root:

```bash
python -m pip install -e ".[dev,obc]"
python examples/quickstart-proxy/run.py
```

The offline quickstart uses a mock upstream and scripted sensor readings. It
prints per-turn drift and recovery decisions, followed by a trace verification
result. It requires no API key or GPU.

Run the tests and conformance checks:

```bash
python -m pytest
python -m ruff check .
python spec/conformance/run_conformance.py
```

For a locally hosted proxy and Jaeger, see the
[Docker Compose guide](deploy/compose/README.md). Its SQLite volume persists
the fleet index and content-addressed trace snapshots; PostgreSQL is not yet a
supported proxy backend.

### Use a contract

Contracts are TOML files with a reproducible content hash:

```python
from guidancegrid.obc import contract_hash, load_contract, validate_contract

contract = load_contract("spec/obc/examples/coding-agent-default.toml")
validate_contract(contract)
print(contract_hash(contract))
```

Explore the [contract specification](spec/obc/) and its
[examples](spec/obc/examples/) for the available fields.

## Corporate demos

These reference scenarios use public internet data and a scripted agent. They
do not connect to a real CRM, ERP, SIEM, or EDR system.

| Scenario | Live data source | Scripted action decisions | Run |
| --- | --- | --- | --- |
| Finance and risk | SEC EDGAR company facts | Allow a CRM note; deny an ERP risk update as approval-required | `python examples/corporate-edgar/run.py --refresh` |
| Security operations | CISA Known Exploited Vulnerabilities catalog | Allow a SIEM case; deny host isolation as approval-required | `python examples/cyber-kev/run.py --refresh` |

Both demos require the development dependencies above and internet access for a
fresh data fetch. Set `SEC_USER_AGENT` to an identifying organization and
contact when using the SEC demo. They can also be run through `make
corporate-demo` and `make cyber-demo` where Make is available.

The `approval_required` outcome is currently a **deny reason**, not an
implemented human approval queue or a mechanism to resume an approved action.
The demos show policy and trace mechanics, not model quality or production
security outcomes.

## Capabilities and boundaries

| Area | Available in this repository | Important boundary |
| --- | --- | --- |
| Contracts and runtime | OBC validation, capability resolution, sensors, drift reconciliation, and recovery decisions | Sensor coverage and recovery effectiveness depend on the deployment and measures supplied. |
| Proxy | OpenAI-compatible chat-completions proxy with opt-in governance and streaming support | Not every provider or response shape is covered; validate integrations before use. |
| Tool policy | Name-pattern allowlist, denylist, and approval-required denial for supported governed responses | No identity-aware or argument-aware authorization, real approval flow, or enforcement at the corporate tool itself. Policy-enabled streaming is buffered. |
| Trace and telemetry | Hash-chained records, verification, SQLite-backed snapshots, and OpenTelemetry integration | A valid hash chain does not prove source data is correct or provide immutable, signed, independently anchored storage. |
| Access and privacy | Optional admin token and metadata-only trace response | Enterprise identity, RBAC, tenant isolation, redaction, retention, and production secrets management remain open work. |
| Model control | Reference T2/T3 paths and T0/T1 steering components | Tier fidelity varies by model and integration; real-model capability-retention evaluations remain outstanding. |

OpenGuide does not guarantee model behavior or compliance. Deployment requires
security review, independently enforced tool permissions, and testing against
the intended models and workflows.

## Evidence and roadmap

The project has a working contract/runtime/proxy foundation, conformance
vectors, offline tests, and two public-data corporate reference scenarios.
The [benchmark report](benchmarks/REPORT.md) describes simulated comparisons
and their limitations. Results from real enterprise workloads and real-model
capability-retention tests are still needed.

The next milestones for enterprise evaluation include authenticated identities
and tenant isolation, policy approval workflows, production storage, a tool
gateway, privacy and retention controls, immutable or externally anchored
evidence, and realistic model and workflow evaluations. These are goals, not
claims of completed product functionality. See the
[enterprise capabilities assessment](docs/enterprise-capabilities.md) and
[governance roadmap](docs/enterprise-governance-layer.md).

## Documentation

| Path | Contents |
| --- | --- |
| [spec/](spec/) | Behavioral contract, state and trace specifications, examples, and conformance vectors. |
| [guidancegrid/](guidancegrid/) | Reference runtime, compiler, sensors, control channels, and SQLite store. |
| [proxy/](proxy/) | OpenAI-compatible proxy and tool-name policy. |
| [integrations/](integrations/) | OpenAI SDK, LiteLLM, and LangGraph integration examples. |
| [examples/](examples/) | Offline quickstart, simulated scenarios, and corporate reference demos. |
| [benchmarks/REPORT.md](benchmarks/REPORT.md) | Simulated results, methodology, and threats to validity. |
| [docs/blueprint.md](docs/blueprint.md) | Architecture, rationale, and phased project plan. |
| [packs/README.md](packs/README.md) | Signal packs and pending real-model evaluations. |

## License

The project declares the Apache License 2.0 in [pyproject.toml](pyproject.toml).
