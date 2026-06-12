# OpenGuide / GuidanceGrid — Complete Product Blueprint
**Version 0.1 · For execution by Claude Code · Apache-2.0 throughout**

---

## 0. Vision and Naming

**Thesis:** The AI stack has seven data-plane layers and zero control plane. OpenGuide is the control plane — the reconciliation loop between *declared* agent behavior and *actual* agent behavior, running for the entire life of every trajectory.

**Category line:** "The last unmanaged layer of the AI stack."

**Naming structure (final):**
- **OpenGuide** — the open standard / project umbrella
- **OBC (Open Behavioral Contract)** — the contract file format; the procurement word ("must support OBC v1")
- **GuidanceGrid** — the reference runtime
- **Console** — the dashboard product surface

**What it does in one paragraph:** A behavioral contract (OBC) declares invariants, phases, triggers, and recovery for an agent. The runtime compiles it to the strongest enforcement channel each model allows (activation steering on open weights → constrained decoding → scheduled re-anchoring on closed APIs), measures behavioral state every turn through typed sensors, reconciles drift against setpoints, and records everything in a hash-chained, replayable trace. One contract, any model, provable behavior.

**Core differentiators (validated against literature, June 2026):**
1. Per-token hash-chained control-signal trace (no prior art)
2. The (layer × step) grid as a persisted, addressable, composable, learnable artifact
3. Behavior as a content-addressed, versioned, eval-scored deployment artifact
4. One contract compiling across the open/closed model divide (tiered fidelity)

**Claims to NEVER make:** "guarantees behavior" (it biases trajectories statistically), "novel control-theory framing" (PID Steering/LiSeCo/RE-Control occupy this — cite them), "first time-varying steering" (Dynamic Activation Composition exists — cite it). The honest delta: persistence, addressability, composition, replay, universality.

---

## 1. Repository Structure (GitHub org: `openguide`)

```
openguide/
├── spec/                      # THE STANDARD (publish first)
│   ├── obc/                   # contract schema, JSON Schema + docs
│   ├── state/                 # behavioral state object schema
│   ├── trace/                 # trace + manifest format spec
│   ├── measures/              # measure type registry spec
│   ├── tiers/                 # tier profiles + capability descriptor
│   ├── conformance/           # golden vectors, test suites
│   └── rfcs/                  # change process
├── guidancegrid/              # REFERENCE RUNTIME (Python, seeded from v0.1.0)
│   ├── core/                  # field, grid, canonical, trace (EXISTS)
│   ├── compiler/              # OBC → tier artifacts
│   ├── channels/              # t0_activation, t1_decoding, t2_text, t3_validate
│   ├── sensors/               # probe, structural, external, judge executors
│   ├── controller/            # reconciler, drift estimator, recovery
│   ├── store/                 # CAS + fleet index (sqlite → postgres)
│   └── tune/                  # grid tuning (EXISTS, toy; extend to real)
├── proxy/                     # THE WEDGE (Python/FastAPI or Go later)
├── console/                   # DASHBOARD (Next.js + TypeScript)
├── packs/                     # starter SignalPacks per model
├── integrations/              # langgraph, litellm, openai-sdk, llamacpp
├── examples/                  # runnable quickstarts
├── benchmarks/                # T1, drift, capability retention protocols
├── deploy/                    # docker-compose, helm, terraform (AWS reference)
└── site/                      # openguide.dev — docs + landing
```

**Language decisions:** Python for runtime v1 (velocity; the working v0.1.0 core exists). TypeScript for console. Rust core port is **Phase 6+, not before product-market signal** — resist the instinct to rewrite early; the moat right now is the spec and the demo, not nanoseconds.

---

## 2. Phase Plan with Acceptance Gates

Claude Code executes phases in order. Each gate must pass (tests green + acceptance criteria) before the next phase begins. Every phase ends with a tagged release and an updated demo.

### Phase 0 — The Spec Core (1 sprint)
Publish the three interop surfaces. This establishes priority on the uncontested claims.

**Deliverables:**
- `spec/obc/`: OBC v0.1 JSON Schema (§3 below) + 3 worked example contracts
- `spec/state/`: Behavioral State JSON Schema + `gen_ai.behavior.*` OTel attribute mapping table
- `spec/trace/`: trace format spec — chain construction, canonical encoding rules (port from existing `canonical.py`), manifest tuple, verification procedure
- `spec/conformance/`: golden vectors — 10 canonical-encoding vectors, 5 chain-verification vectors (valid + tampered), 3 contract-compilation expected outputs
- README leading with the thesis, the architecture mermaid diagrams (exist), and the honest prior-art positioning paragraph

**Gate:** an independent script using only the spec docs + golden vectors can verify a trace produced by the existing v0.1.0 runtime. Spec hash stability test across Python/Node implementations of canonical encoding.

### Phase 1 — Universal Runtime (2 sprints)
The closed-model product, end to end. Seed from existing v0.1.0 code (field/grid/trace/runtime/tune modules — 18 passing tests).

**Deliverables:**
- `compiler/`: OBC → {T2 prompt fragments + re-anchor schedule, T3 validator set, ProbeSpec, TriggerTable}. Capability Resolver with static capability descriptors for OpenAI/Anthropic/Google/vLLM/llama.cpp targets.
- `channels/t2_text.py`: scheduled re-anchor assembler (frame-boundary injection of contract fragments, budget-aware)
- `channels/t3_validate.py`: structural validators (JSON schema, regex, file-scope, custom fn) + retry policy
- `sensors/`: structural executor; external adapter interface (webhook + python callable); judge adapter (any OpenAI-compatible endpoint, explicitly tagged `determinism: stochastic`)
- `controller/`: per-turn reconciler — drift scalar = weighted invariant violations; recovery dispatch (re_anchor | escalate | halt); all actions recorded
- `store/`: sqlite CAS + fleet index; query API ("runs where drift > X", "by contract_hash")
- Wire everything through the existing Recorder. **Invariant: no component may mutate run state without a trace record. Enforce by construction — the control channel is the only write path.**

**Gate:** end-to-end test — a 50-turn scripted agent (mock LLM) under contract: drift injected at turn 30, sensor detects, reconciler fires re-anchor, drift recovers, trace verifies, replay produces bit-identical head. 60+ tests total.

### Phase 2 — The Proxy Wedge (1 sprint)
**Deliverables:**
- `proxy/`: FastAPI OpenAI-compatible `/v1/chat/completions` (+ streaming SSE). Pass-through by default; `X-OpenGuide-Contract: <hash>` header activates governance. Handles: chunk assembly, tool-call delta reassembly (the known fragmentation problem — test against OpenAI + Anthropic + vLLM stream formats), trigger token detection in stream.
- Session continuity: conversation-id → persistent behavioral state across calls (this is the "feeds forward" claim made real)
- OTel exporter: every turn emits a span with `gen_ai.behavior.*` attributes; works with any OTLP collector
- `integrations/litellm/` callback + `integrations/langgraph/` middleware node + `integrations/openai-sdk/` base_url drop-in example

**Gate:** `docker compose up` → point any OpenAI SDK app at the proxy → behavioral state appears in Phoenix/Jaeger within 5 minutes, zero app code changes. Latency overhead < 25ms p50 non-streaming pass-through.

### Phase 3 — Console (2 sprints)
The dashboard UI. Next.js, dark instrument aesthetic (design tokens below).

**Pages:**
1. **Fleet** (4D): runs × turns heatmap colored by drift; filters (contract, pack, model, time); "what changed Tuesday" diff view between contract/pack versions; live tail
2. **Run** (2D): the run console — grid spectrogram (layer × step where tier 0; turn × signal strip where tier 2), token/message stream with signal annotations, trace event log, behavioral state sparklines, scrub + replay controls. Port the proven React artifact designs.
3. **Trajectory** (3D): behavioral state path through 3-axis projection (selectable invariants or PCA), contract safe-region as translucent volume, drift excursions and recovery snap-backs visible. three.js.
4. **Contracts**: contract list by hash, YAML/TOML editor with schema validation, diff view between versions, "deploy to fleet" action
5. **Packs**: pack registry, eval scores, model-compat matrix, staleness warnings
6. **Audit**: run search → trace verification status → exportable report (PDF via print CSS)

**Design tokens** (from validated artifact work): bg `#101318`, panel `#161b22/#0b0e12`, border `#2a313c`, text `#c9d1d9/#eef2f6`, signal hues amber `#e8a33d` cyan `#46c8d2` violet `#9b7bf0` rose `#e06a8a` green `#7ddb8a` red `#ff6b5e`; type: Space Grotesk display / IBM Plex Mono data. Dimensionality rule: each added dimension must answer a question the lower one can't; default views are 2D + linked panels.

**API:** console reads only from store query API + trace files. No privileged path — the console is a consumer like any other (dogfoods interface #2 and #3).

**Gate:** demo dataset (Phase 5 generator) renders all six pages; run page scrubs a 100-step run at 60fps; fleet page handles 10k runs.

### Phase 4 — Signal Tier (2–3 sprints)
Open-weight enforcement. The research-grade differentiator.

**Deliverables:**
- `channels/t0_activation.py`: PyTorch forward hooks for HF transformers (target: Qwen2.5-7B-Instruct + Llama-3.1-8B-Instruct); norm-preserving injection (literature-validated design — cite Selective Steering 2601.19375); Σ-cap mechanical enforcement; per-step column evaluation from frame tiles (core exists)
- `sensors/probe.py`: linear probe executor on residual stream; probe training script (offline toolchain) from labeled contrast data
- `packs/`: starter pack v0 for both models — 4 signals (anchor, precision, explore, syc-damp), derivation scripts, eval cards (MMLU delta at gain 0.2/0.4/0.6, generation coherence check), content-hashed safetensors
- `channels/t1_decoding.py`: Outlines/llguidance integration for structural hard invariants on local models
- vLLM plugin spike (logits processor + hidden-state hook feasibility doc — full plugin is post-v1)
- `tune/`: extend grid tuning from toy plant to real model: learn re-anchor schedule (T2) and gain schedule (T0) against a measured adherence probe; reproduce-or-kill the "learned schedule beats constant" result on real model

**Gate:** on Qwen2.5-7B — a 50-step agent run with ANCHOR ramp shows measured adherence improvement vs no-grid baseline, MMLU delta < 1.5pts at deployed gains, all enforced/recorded/replayable. **If the learned schedule collapses to constant-over-time, document it honestly and reposition the claim** (this is falsifiability threat T4's empirical test).

### Phase 5 — Benchmarks, Demo, Case Studies (2 sprints)
**The T1 benchmark (commercial gate):** scheduled contract re-anchoring (T2) vs periodic naive re-prompting vs no intervention, on closed model (GPT/Claude via API) + open model, 50–100 step agent tasks, matched token budgets. Metrics: instruction adherence (judge panel + structural checks), task completion, tokens consumed, $/run. Publish regardless of outcome. **Kill criterion: if naive re-prompting matches at equal cost, scope the product to observability + open-weight tiers and say so publicly.**

**The drift benchmark:** adopt turn-wise divergence methodology from "Drift No More?" (2510.07777) + τ-Bench-style tasks; with/without contract.

**Capability retention:** MMLU + GSM8K at gain ladder, per pack, published as eval cards.

**The killer demo (`examples/demo/`):** one command (`make demo`) launches: proxy + console + a scripted 60-step coding-agent scenario (mock or real model, both supported) where the baseline visibly drifts (scope creep + instruction decay), the governed run holds, the fleet view shows both, and the presenter scrubs the governed run's replay to the exact re-anchor event. Synthetic data generator producing 10k realistic runs for fleet view. **The demo is the product's primary sales asset — invest accordingly.**

**Case studies (3, explicitly labeled "reference scenarios — simulated" until design partners replace them):**
1. *Coding agent fleet*: 100-step SWE tasks; contract = scope-discipline + tests-before-commit + CESR setpoint (CodeMonk adapter as external measure — real integration, shipping both projects' story)
2. *Multi-tenant support*: one model, 5 tenant temperament contracts (pack compose `tenant ⊕ task`); shows behavior-as-config economics
3. *Browsing agent injection detection*: behavioral-state divergence (adherence-to-user vs adherence-to-context) flagging injected instructions before action — the novel detection channel; this one is a paper on its own

**Gate:** demo runs cold on a clean machine in < 10 minutes; benchmark report drafted as arXiv preprint.

### Phase 6+ — Post-launch (not in initial scope; documented for direction)
Rust core port (perf + embedded), llama.cpp scheduled-control-vector patch upstream, vLLM production plugin, K8s operator, closed-loop controller v2 (PID per 2510.04309, cited), hosted control plane (commercial), OTel SIG `gen_ai.behavior.*` proposal submission.

---

## 3. OBC v0.1 Schema (normative sketch — full JSON Schema in spec/obc/)

```toml
[contract]
name = "coding-agent-default"
version = "0.1.0"
enforcement_floor = "t3"          # minimum tier; runtime refuses below

[identity]
persona = "precise, terse, skeptical"
boundaries = ["no edits outside declared paths", "no force push"]

[[invariants]]
id = "adherence"
measure = "judge:instruction_adherence"   # or probe:/structural:/external:
floor = 0.85
weight = 1.0                               # drift contribution

[[invariants]]
id = "tests_gate"
measure = "structural:tests_pass_before_commit"
hard = true                                # tier-1/3 enforced, never advisory

[[invariants]]
id = "cesr"
measure = "external:codemonk.cesr"
floor = 0.80

[[phases]]
name = "plan"
window = { turns = [0, 5] }
signals = [{ ref = "explore", gain = 0.5 }]

[[phases]]
name = "act"
window = { turns = [5, -1] }
signals = [{ ref = "anchor", gain = { ramp = [0.1, 0.6] } }]

[[triggers]]
on = "token:<tool_call>"
apply = { ref = "precision", gain = 0.7, decay_tau = 8 }

[recovery]
drift_threshold = 0.27
actions = ["re_anchor", "escalate@0.45", "halt@0.60"]

[signals]                                  # tier-binding indirection
anchor    = { pack = "sha256:...", t2_template = "templates/anchor.md" }
precision = { pack = "sha256:...", t1_grammar = "grammars/tool.lark" }
explore   = { pack = "sha256:..." }
```

Canonical encoding rules: sorted keys, 9-sig-digit floats, UTF-8, no insignificant whitespace → `contract_hash = sha256(canonical(contract))`. (Port existing `canonical.py` verbatim; it has golden vectors.)

**Behavioral State object (per turn, normative fields):** `turn, tier_active, invariants{id→reading}, drift, signals_active{ref→gain}, sigma_peak, norm_correction, recovery_fired?, sensor_gaps[], hash_prev, hash`. OTel mapping: `gen_ai.behavior.drift`, `gen_ai.behavior.tier`, `gen_ai.behavior.invariant.<id>`, `gen_ai.behavior.recovery`.

---

## 4. Cloud Implementations

**Local (default, `deploy/compose/`):** docker-compose — proxy + console + postgres (store) + jaeger (OTLP). One command. This is the OSS experience; optimize it relentlessly.

**Self-host (`deploy/helm/`):** Helm chart — proxy (HPA, stateless), console, postgres (or external), object store for traces (S3-compatible), optional vLLM pod with t0 channel enabled. Trace writes are append-only to object store; index in postgres; CAS keys = content hashes (idempotent, cache-friendly).

**AWS reference (`deploy/terraform/aws/`):** ALB → ECS Fargate (proxy, console) · S3 (CAS: contracts/packs/traces, versioning + object-lock for audit retention) · Aurora Postgres (fleet index) · optional ClickHouse on EC2 for >10M-run fleets · CloudWatch/ADOT for OTel. Document the trust boundary: the proxy sees prompts/outputs — provide a "metadata-only" mode (state + trace, content redacted/hashed) for sensitive deployments. GCP/Azure: document-level parity notes only for v1.

**Sizing guidance to document:** trace ≈ 50–200 bytes/turn/signal → 10M runs × 100 turns ≈ low-GB range in S3 — storage is never the cost problem; judge-sensor API calls are. Make judge sampling rate a contract-level knob.

---

## 5. Examples (each: README + runnable in < 5 min)

1. `examples/quickstart-proxy/` — OpenAI SDK app + 10-line contract → drift visible in console
2. `examples/langgraph-middleware/` — research agent graph, contract delegation to a subagent, parent-child trace chaining
3. `examples/litellm-callback/` — multi-provider, same contract, tier auto-selection visible in state
4. `examples/local-qwen-t0/` — full activation tier on Qwen2.5-7B, grid spectrogram live in console
5. `examples/codemonk-setpoint/` — CESR as external measure governing a coding agent (cross-project)
6. `examples/injection-detection/` — browsing agent, behavioral divergence alarm
7. `examples/demo/` — the killer demo (Phase 5)

---

## 6. GTM Plan (OSS-first)

**Launch sequence:**
1. arXiv preprint: systems framing — "OpenGuide: A Control Plane for LLM Inference Trajectories" — leading with the three validated claims, citing PID Steering/DAC/CAST honestly (the validation study is the related-work section, pre-written)
2. Spec repo public + openguide.dev (docs + the two architecture diagrams + demo video)
3. Show HN: "OpenGuide – see and stop your agents' behavioral drift (OSS)" — lead with the demo GIF (fleet heatmap → replay scrub), not the thesis
4. OTel GenAI SIG: `gen_ai.behavior.*` proposal (first-mover schema advantage)
5. Blog series (4 posts): the drift problem with data · behavior as a versioned artifact · the tiered compiler · the trace (why logprobs aren't observability)
6. Conference CFPs: MLSys (runtime), CCS/S&P (trace plane — separate paper), KubeCon AI day (control-plane framing), AI engineering summits (demo-driven talk)
7. Integrations PRs upstream: LiteLLM callback, LangGraph middleware — distribution through ecosystems, not against them

**Design partner program (gate to commercial):** 5 partners, criteria: >50-step agent runs in production, regulated or high-volume, willing to publish metrics. Offer: free hosted console + pack maintenance for case-study rights. **Success = measured drift reduction on partner workloads; this replaces the simulated case studies.**

**Pricing sketch (post-validation, hosted):** Free OSS self-host forever · Cloud: per-governed-run metered (Helicone-style) · Enterprise: audit retention/SSO/compliance reports + SignalPack subscription (per model family, refreshed within 7 days of model releases). Do not monetize the spec or runtime, ever.

**Kill criteria (write them down, honor them):** T1 benchmark fails → scope to observability + open-weight, publicly. < 3 design partners in 2 quarters → career-capital/acquisition path, not venture path. A major framework ships equivalent behavioral state natively → double down on trace/replay + standard, or contribute and fold.

---

## 7. Engineering Conventions for Claude Code

1. **Determinism is law.** Every hashable artifact goes through canonical encoding. Any new serialization gets golden vectors in the same PR. Same manifest ⇒ bit-identical trace head is a CI test, always.
2. **No side doors.** Run state mutates only via the control channel; the recorder sees every event. PRs adding state writes outside it are rejected by design review (add an architecture test asserting Recorder coverage).
3. **Sensors are typed by honesty.** Every measure declares `determinism: deterministic|stochastic` and `latency_class`. Judge-based measures must never silently substitute for structural ones.
4. **Data plane never blocks on control plane.** Sensor timeout → proceed with stale gains + record `sensor_gap`. Test this failure path explicitly.
5. **Tests:** pytest, every component; conformance vectors are cross-language (Python + Node runners in CI). Target: zero flaky tests — stochastic paths get seeded.
6. **Honest docs.** Every README states scope limits (statistical biasing not guarantees; tier-2 = text-level; toy results labeled toy). The credibility budget is the company.
7. **Releases:** semver; spec versions independently from runtime; CHANGELOG per repo; every phase gate = tagged release + demo update.
8. **When uncertain, ask the human:** model API keys/spend, design decisions that change spec surfaces, anything touching claims/positioning copy.

---

## 8. Sprint-Zero Checklist (Claude Code starts here)

- [ ] Create org/repos per §1; CI (pytest + node conformance runner + ruff + tsc)
- [ ] Port v0.1.0 modules (`canonical, field, grid, trace, runtime, tune`) into `guidancegrid/core/` — tests must stay green (18/18)
- [ ] Write OBC v0.1 JSON Schema + the 3 example contracts (§3, §5)
- [ ] Generate golden vectors from existing implementation; stand up cross-language conformance test
- [ ] Draft spec/README with thesis + diagrams + prior-art positioning paragraph
- [ ] `deploy/compose/` skeleton: proxy stub (pass-through) + postgres + jaeger
- [ ] Issue backlog: file every deliverable in §2 as issues with phase labels and gate criteria

**Definition of done for v1.0 (the launch):** Phases 0–5 gates passed · demo cold-starts in <10 min · T1 benchmark published with whatever result is true · 6 examples run · console renders 10k-run fleet · spec at v0.1 with conformance suite · arXiv preprint submitted.
