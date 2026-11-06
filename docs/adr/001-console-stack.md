# ADR-001: Console stack — Vite + React + TypeScript, served by the proxy

Status: accepted (human chose this option) · Gate: G1 · Owner: Chief Architect

## Context
The blueprint specifies "Next.js + TypeScript" for the Console. The Console is a
pure consumer of the proxy's REST API (`/v1/openguide/*`), with no server-side
data fetching, SEO or auth flows that SSR would serve.

## Decision
Build a **Vite + React + TypeScript** single-page app in `console/`. `vite build`
emits static files; the FastAPI proxy mounts them at `/console`. In development,
Vite proxies `/v1` to the proxy, so no CORS configuration is needed.

This **deviates from the blueprint's "Next.js"**; the human approved it. Rationale:
smaller dependency tree, a single process for the demo (`make console-demo`), and
no unused SSR machinery.

## Consequences
- + One command, one process, nothing to deploy separately.
- + Fewer transitive packages to audit.
- − No SSR/streaming server components (not needed).
- − Routing is hash-based (`#/run/<id>`), implemented in ~30 owned lines.

## Rejected
- Next.js: larger tree, second server or export step, SSR unused.
- No-build vanilla JS: harder to maintain across six pages.

## Dependency interview (standards/dependency-policy.md)
| Package | Need | Health | Weight | License |
|---|---|---|---|---|
| `react`, `react-dom` | UI runtime for six stateful views | Very widely used, active | small runtime, no transitive deps | MIT |
| `three` | 3-D trajectory view; ~0 lines of owned code can replace WebGL | Very widely used, active | single package, no runtime deps | MIT |
| `vite`, `@vitejs/plugin-react`, `typescript` (dev) | build + types | Very widely used, active | dev only | MIT / Apache-2.0 |
| `vitest`, `jsdom`, `@testing-library/react` (dev) | unit/component tests | Very widely used, active | dev only | MIT |

**Not added** (owned code instead): router (hash router, ~30 lines), chart library
(SVG/canvas drawn by hand), state manager (local state + hooks), CSS framework
(tokens in one stylesheet), TOML parser (editor is JSON).

Lockfile (`package-lock.json`) is committed; CI installs with `npm ci`. `npm audit`
findings are dispositioned in the plan's QA report.

## API additions (additive; recorded here because they touch the public surface)
- `GET  /v1/openguide/contracts` · `GET /v1/openguide/contracts/{hash}`
- `POST /v1/openguide/contracts/validate` (dry run, never registers)
- `GET  /v1/openguide/packs`
- `GET  /v1/openguide/runs/{id}` (run summary)
All remain behind the admin token when one is configured. No existing endpoint
changes behaviour.

## Data-model note
The fleet index stores per-run summaries only. The Fleet heatmap therefore draws
one cell per run; per-turn series come from the trace on the Run page.
