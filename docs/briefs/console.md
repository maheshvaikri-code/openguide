# Brief: OpenGuide Console (Phase 3)

Class L · Owner: Product Owner · Status: approved by the human (stack + scope chosen)

## Problem
Operators and prospects can run OpenGuide only through a CLI and raw JSON. Nobody
can *see* a fleet drifting, scrub a governed run to the moment a correction fired,
or verify that a trace is intact without reading hashes. The blueprint calls the
demo "the product's primary sales asset"; today it is ASCII output.

## Users
- **Evaluator / buyer** watching a 5-minute demo.
- **Agent operator** looking for which runs drifted and why.
- **Auditor / compliance reviewer** who needs a verifiable, exportable record.

## Scope (all six blueprint pages, per human decision)
1. **Fleet** — one cell per run coloured by max drift; filters (contract, model,
   tier, min drift, halted); live tail (polling); click a cell → Run.
2. **Run** — drift/invariant sparklines, signal strip (turn × signal), trace event
   log, scrub + play/pause replay, jump to first correction.
3. **Trajectory** — behavioural state path in a 3-axis projection of invariant
   readings, contract safe region as a translucent volume, excursions/recoveries.
4. **Contracts** — list by hash, JSON editor with server-side validation, diff of
   two contracts, copy-ready `X-OpenGuide-Contract` activation snippet.
5. **Packs** — pack registry from `eval_card.json`, signals/layers, eval slots with
   unfilled slots shown as **"not measured"**, staleness vs. model.
6. **Audit** — run search, trace verification status, exportable report (print CSS).

Plus: a one-command demo (`make console-demo`) that seeds realistic data and serves
the Console from the proxy.

## Non-goals
- No claim of real-model results: all demo data is labelled **SIMULATED**.
- No auth system beyond the proxy's existing admin token.
- No write path other than registering a contract (no run mutation, no deploy action).
- Fleet *diff view between contract versions* ("what changed Tuesday") — Deferred.
- TOML editing in the browser (needs a parser dependency; server accepts JSON) — Deferred.
- Postgres, multi-user, SSO, hosted deployment.

## Acceptance criteria (each maps to a test in the plan)
| # | Criterion | Test |
|---|-----------|------|
| AC1 | `make console-demo` starts one process; `GET /console/` returns the app and `GET /healthz` is 200. | `tests/test_console_server.py` |
| AC2 | `GET /v1/openguide/contracts` lists registered contracts (hash, name, version, floor); `GET .../contracts/{hash}` returns the body; unknown hash → 404. | `tests/test_console_api.py` |
| AC3 | `POST /v1/openguide/contracts/validate` returns 200 `{ok:true,hash}` for a valid contract and 422 with a message for an invalid one, **without registering**. | `tests/test_console_api.py` |
| AC4 | `GET /v1/openguide/packs` returns each pack's hash, model, signals, layers and eval slots; empty dir → `[]`. | `tests/test_console_api.py` |
| AC5 | Fleet renders N runs as N cells; filtering by min drift reduces the cell count to the API's count; 10 000 runs render in < 1 s (measured). | vitest + browser check |
| AC6 | Run page: scrubbing to turn *t* shows that turn's drift/invariants from the trace; "jump to first correction" lands on the first record with `recovery_fired`. | vitest (`replay.ts`) |
| AC7 | Trajectory: projection is deterministic and bounded; excursion turns (drift above threshold) are flagged. | vitest (`projection.ts`) |
| AC8 | Contracts: invalid JSON or a server 422 shows the message next to the editor and does not register; diff shows added/removed/changed paths. | vitest (`diff.ts`, editor) |
| AC9 | Packs: an eval slot with value `null` renders "not measured", never `0`. | vitest |
| AC10 | Audit: a tampered trace is reported **INVALID** and the report states which check failed; a valid trace is **VERIFIED** with head hash. | vitest + pytest (tampered fixture) |
| AC11 | Every page renders the five states (empty, loading, partial, error, success); the error state is rendered in a test for each. | vitest |
| AC12 | Keyboard-only path: all interactive controls reachable; status is never colour-only (text/icon accompanies colour). | manual checklist + axe-style assertions |
| AC13 | `GET /v1/openguide/*` still honours the admin token; the Console prompts for it on 401 and keeps it in `sessionStorage` only. | `tests/test_console_api.py` + vitest |

## Edge cases (enumerated at intake)
- **Empty:** no runs, no contracts, no packs, trace with zero records.
- **Huge:** 10 000 runs; 100-step runs; contracts with many invariants.
- **Concurrent:** live tail polling while runs are inserted; stale response must not overwrite a newer one.
- **Malformed:** trace missing `STATE` records; unknown `ev`; null readings (sensor gaps); non-JSON error bodies.

## Constraints
- Reads only the proxy REST API — no privileged path (blueprint).
- Design tokens from the blueprint (bg `#101318` etc.); accessible contrast verified.
- New npm dependencies must pass `standards/dependency-policy.md` (see ADR-001).

## Assumptions (correct me)
- Fleet "heatmap" is one cell per run (the fleet index stores per-run summaries,
  not per-turn drift); per-turn drift appears on the Run page.
- "Deploy to fleet" is rendered as the activation header snippet, not an action.
- Demo data is generated locally (`benchmarks/fleet_gen.py` + simulated runs with
  real reconciler traces); the Console labels it SIMULATED.

## Open questions
None blocking.
