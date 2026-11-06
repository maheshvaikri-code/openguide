# Implementation plan: Console (Phase 3)

Brief: `docs/briefs/console.md` · ADR: `docs/adr/001-console-stack.md` · Class L

## Slices (vertical; each independently green and demonstrable)
| Slice | Delivers | Proves |
|---|---|---|
| S1 Foundation + Fleet | API additions, static mount, demo seeder, Vite scaffold, shell, tokens, router, API client, Fleet page | AC1-5, AC11 (Fleet), AC13 |
| S2 Run | Trace parsing, replay engine, sparklines, signal strip, event log, scrub/play | AC6 |
| S3 Audit | Search, verification display, print-CSS report | AC10 |
| S4 Contracts | List, editor + validate, diff, activation snippet | AC8 |
| S5 Packs | Registry view, unfilled slots as "not measured" | AC9 |
| S6 Trajectory | Projection + three.js scene, safe region, excursions | AC7 |

## Layout
```
console/
  src/lib/        api.ts  types.ts  replay.ts  projection.ts  diff.ts  heat.ts  router.ts
  src/ui/         Shell, StateView (five states), Sparkline, Heatmap, ...
  src/pages/      Fleet Run Trajectory Contracts Packs Audit
  src/styles.css  tokens
proxy/console_api.py    new routes (contracts list/detail/validate, packs, run detail)
proxy/app.py            mounts routes + static /console
scripts/console_demo.py seed + serve
```

## Risks and mitigations
- **10k-run render cost** → draw Fleet on a `<canvas>`, not 10k DOM nodes; DOM fallback list for a11y.
- **Stale poll overwrites newer data** → request sequence number guard (tested).
- **Dishonest demo data** → every seeded run carries a `mock:` model id; UI shows a SIMULATED badge when any `mock:` run is present.
- **three.js bundle size** → code-split Trajectory page (dynamic import).
- **Windows console encoding** → ASCII-only output in the seeder (per project notes).

## Test plan
Backend: pytest for each new endpoint, admin-token enforcement, empty/malformed inputs.
Frontend: vitest for pure logic (replay, projection, diff, heat bucketing, API state machine) and component tests for the five states per page. Visual/keyboard check in a real browser via Playwright, with screenshots.

## Definition of done
All ACs evidenced; `ruff`, `pytest`, `tsc --noEmit`, `vitest`, `vite build` clean; docs + CHANGELOG updated; QA report in `docs/qa/console.md`; committed per git conventions. Publishing is not in scope.
