# QA + Security Report — Console (Phase 3) @ uncommitted working tree

**QA Engineer** · **Security Reviewer** · **Date:** 2026-11-06
**Build under test:** the working tree at the time of commit (the commit that adds this file).

Brief: `docs/briefs/console.md` · ADR: `docs/adr/001-console-stack.md` · Plan: `docs/plans/console.md`

## Acceptance criteria verification

| # | Criterion | How executed | Evidence | Pass |
|---|-----------|--------------|----------|------|
| AC1 | One process serves the app at `/console/`; `/healthz` is 200 | `tests/test_console_server.py` (4), `tests/test_console_demo_script.py` (2); launched `scripts/console_demo.py` and loaded `/console/` in a browser | tests pass; browser screenshots of Fleet, Run, Trajectory, Audit, Contracts, Packs | Pass. **Caveat:** `make` is not installed on the authoring machine, so the `make console-demo` target itself was not run; its two steps (`npm run build`, `python scripts/console_demo.py`) were run directly. |
| AC2 | Contracts list / detail / 404 | `tests/test_console_api.py` | passes | Pass |
| AC3 | Validate is a dry run (200 / 422 / no registration) | `tests/test_console_api.py` | passes | Pass |
| AC4 | Packs endpoint | `tests/test_console_api.py` | passes. Deviation from the brief: an empty directory returns `{"packs":[],"skipped":[]}`, not `[]`, so malformed cards can be reported | Pass (shape deviation, intentional) |
| AC5 | N runs render as N cells; 10 000 runs in < 1 s | Browser measurement against a 10 000-run server; `layoutGrid` unit tests | Fleet summary and canvas painted in **250, 280 and 316 ms** (three loads, fetch included; budget 1000 ms). Summary read "10,000 runs shown". The canvas itself is not covered by a jsdom test (jsdom has no canvas), so cell count is evidenced by the summary figure and layout tests, not a pixel assertion. | Pass |
| AC6 | Scrubbing shows that turn's values; "jump to first correction" lands on it | `pages.test.tsx`, `review.test.tsx`, `lib.test.ts` | passes; browser check landed on turn 16 for `demo-governed-sparse` | Pass |
| AC7 | Projection deterministic, bounded, excursions flagged | `lib.test.ts` | passes (incl. at-or-above edge, no-threshold, `drift_guard` name collision) | Pass |
| AC8 | Invalid JSON / server 422 shown, nothing registered; diff works | `pages.test.tsx`, `review.test.tsx` (register flow, stale check) | passes | Pass |
| AC9 | Unmeasured eval reads "not measured", never 0 | `pages.test.tsx`; browser screenshot of Packs | passes | Pass |
| AC10 | Tampered trace reported broken; says where | `tests/test_console_api.py` (chain report, incl. a 200-mutation comparison against `Trace.verify()`), `tests/test_console_seed.py`, `pages.test.tsx`; browser check of `demo-tampered` | passes. The report states where the chain breaks and what could have caused it; it names no specific record as altered (see Bugs found). | Pass |
| AC11 | Five states per page; error state rendered per page | `pages.test.tsx`, `review.test.tsx` | error state tested for Fleet, Run, Trajectory, Contracts, Packs, Audit report, Audit search; empty tested for each; loading asserted on Fleet; partial (skipped packs, ignored records, poll failure) tested | Pass |
| AC12 | Keyboard path; status never colour-only | Role/label-based tests; browser keyboard pass; computed contrast | See "Accessibility" below. **No automated axe-style audit was run** (not installed; it would be a new dependency). | Partial |
| AC13 | Admin token enforced; Console prompts on 401, keeps token in `sessionStorage` | `tests/test_console_api.py` (every route 401), `lib.test.ts` (bearer header), `pages.test.tsx` (token prompt) | passes. After entering a token the page reloads so every panel refetches. "sessionStorage only" is by construction in `lib/api.ts`; no test asserts that it never touches `localStorage`. | Pass |

## Adversarial & edge matrix

| Input/scenario | Expected | Observed | Pass |
|----------------|----------|----------|------|
| Empty fleet / contracts / packs / zero-record trace | Empty state with next step | tests render each | Yes |
| 10 000 runs | Renders < 1 s | 250–316 ms | Yes |
| New run arrives while one is selected (live tail) | Selection stays on the same run | `review.test.tsx` | Yes (was a bug) |
| Selected run leaves the list | Selection clears | `review.test.tsx` | Yes |
| Slow response after a newer request | Dropped | `useResource.test.tsx` | Yes |
| Hidden tab | No polling | `useResource.test.tsx` | Yes |
| Contract with different / missing / unreadable threshold | Line drawn at its own value; none if unknown | `review.test.tsx` | Yes (was a bug) |
| Chain: edit, delete middle, reorder, truncate, edit first record, edit manifest, edit last | `ok` equals `Trace.verify()`; reason lists possibilities, accuses no record | 200 random mutations + named cases | Yes |
| Malformed trace record (wrong types) | Normalised; page renders | `lib.test.ts` | Yes (was a crash) |
| Pack card `{}`, wrong-typed `signals`/`evals`, JSON that isn't an object | Skipped and reported | `tests/test_console_api.py` | Yes |
| Pack card with extra `name` | Directory name wins | `tests/test_console_api.py` | Yes |
| Request body 300 KB | 413 before parsing | `tests/test_console_api.py` | Yes |
| Malformed JSON to register | 422, not 500 | `tests/test_console_api.py` | Yes |
| `limit=0`, `limit=999999999` | 422 | `tests/test_console_api.py` | Yes |
| Run in the fleet index without a stored trace | "Not re-checked", never "verified" | `review.test.tsx` | Yes (was a false claim) |
| Simulated runs on a real model's pack | Not counted | `review.test.tsx` | Yes |
| Clipboard denied | Says so | `review.test.tsx` | Yes |
| View throws while rendering | Error panel, not a blank page | `review.test.tsx` | Yes |
| Phone width (390 px) | No horizontal page scroll | measured on all pages: fits | Yes |

## Regression

- `python -m pytest` → **352 passed**; `ruff check .` clean.
- `npm --prefix console test` → **100 passed**; stable over repeated runs. `npm run typecheck` clean. `npm run build` clean (Trajectory/three.js code-split into its own chunk, 565 kB).
- No flaky tests observed.

## Bugs found (G4 code review, then fixed)

| # | Finding | Severity | Fix | Regression test |
|---|---------|----------|-----|-----------------|
| B1 | Fleet/Run/Trajectory drew "contract threshold 0.27" for every run; the demo contract's real threshold is 0.05 | Blocker | Read `recovery.drift_threshold` and the `halt@x` rung from the run's own contract; draw nothing if unknown; Fleet uses a neutral scale and says contracts set their own | `review.test.tsx` "contract thresholds are never invented" |
| M1 | Fleet selection was a list position; live tail silently changed the selected run | Major | Select by run id | `review.test.tsx` "fleet selection" |
| M2 | Registering reloaded the parent, unmounting the editor and its confirmation | Major | Silent refresh | `review.test.tsx` "contract registration" |
| M3 | Chain report named an intact record when one was deleted or inserted; headline asserted "altered" | Major | Report only where the chain breaks and list the possible causes | `tests/test_console_api.py` |
| M4 | Fleet and Audit showed "Chain verified" for runs with no stored trace | Major | "Not re-checked", counted separately | `review.test.tsx` |
| M5 | Simulated badge came from one run and went stale after a token | Major | Computed from up to 500 runs ("Simulated data" vs "Includes simulated runs"); page reloads after a token | `review.test.tsx` |
| M6 | 401 left sibling panels empty | Major | Reload after token entry; run count shows "unavailable", not 0 | `review.test.tsx` |
| M7 | A malformed pack card or trace field could blank the whole app | Major | Server validates cards; client normalises records; top-level error boundary | `tests/test_console_api.py`, `lib.test.ts`, `review.test.tsx` |
| M8 | Text that misdescribed behaviour (sensor gap, re-anchor timing, safe region, comparison run, mock runs on real packs) | Major | Reworded to what the record proves | `review.test.tsx` |
| minor | stale validation race; model filter option vanishing; `drift_guard` treated as drift; `>` vs `>=`; "Simulated: No" for absent flag; polling hidden tab; skip link + focus on route change; clipboard silence; "null" names; Scene3D fallback hidden from assistive tech; `make console-demo` on a fresh clone | Minor | each fixed | each covered in `review.test.tsx` / `useResource.test.tsx` / `lib.test.ts` |

**Verification gap:** after the final round of fixes the browser tool could not be started (its profile was locked by a stale instance from before a session restart), so the last UI changes were verified by the 100 component tests, a production build, and HTTP checks against a live demo server (contract threshold 0.05 served; tampered trace reports the break between records 16 and 17; 413 on a 300 KB body; 422 on `limit=0`; both packs labelled synthetic). The earlier browser checks (layout at desktop and 390 px, keyboard, the 10 000-run render time) predate these fixes. Re-run a visual pass before a public demo.

**Not fixed (accepted, recorded):** Fleet "new since you opened" can mislabel runs when the 10 000-run cap or filters change the list; Fleet and Audit cap at 10 000 runs (Audit now says when it is showing the first 10 000); `Trace.verify()` ignores the manifest while the chain report checks it, so the two `/trace` fields can disagree on an in-memory trace whose manifest was mutated (the UI uses both and shows the stricter result).

## Security sweep (per skills/security.md)

Reviewed by the security-reviewer agent (read-only). Verdict recorded below; its findings were verified before acting.

- **Admin token on every route:** pass (`require_admin` first in each handler; `secrets.compare_digest`).
- **Path traversal / symlinks:** pass (`read_packs` takes no request input; `StaticFiles` does not follow symlinks by default).
- **SQL:** pass (only fixed literals interpolated; values bound).
- **XSS:** pass (no `dangerouslySetInnerHTML`/`innerHTML`/`eval`; server strings rendered as text).
- **Token handling:** `sessionStorage` only, sent as a bearer header, never in URLs or logs.
- **Dep audit (verbatim):** `npm audit` → `found 0 vulnerabilities`. Runtime deps: react, react-dom, three. Licences checked from installed `package.json`: react, react-dom, three, vite, vitest, @vitejs/plugin-react, jsdom, @testing-library/react, @types/three are MIT; typescript is Apache-2.0. `package-lock.json` is committed.
- **Findings and disposition:**
  - M1 *open control plane when no token is set* → startup WARNING in `proxy/server.py`; unauthenticated `GET /v1/openguide/status`; the Console shows a notice when no token is configured. The proxy still starts without a token (unchanged, pre-existing behaviour); **the README and release notes must say the proxy is unauthenticated unless `OPENGUIDE_ADMIN_TOKEN` is set.**
  - M2 *unbounded bodies / `limit` / register 500* → 256 KB body cap (413), `limit` 1–10 000, register parse inside the try (422).
  - L1 *audit wording overstated the guarantee* → headline is now "Hash chain consistent"; the caveat that it does not prove authorship, and that the head must be anchored or signed externally, sits beside the verdict and prints with it.
  - INFO `--admin-token` on the command line is visible in process listings → prefer the `OPENGUIDE_ADMIN_TOKEN` environment variable (the launcher reads it by default).

**Security verdict:** SIGN-OFF (veto lifted by the security-reviewer: no critical or high findings) · human override: n/a
**QA verdict:** pass, with AC12 partial (no automated accessibility audit) and the `make console-demo` caveat under AC1.

## Accessibility (AC12)

- Status is glyph + text everywhere (`●◐▲■`, "Chain verified / broken / Not re-checked", "below floor"); colour is never the only signal.
- Computed WCAG contrast of text colours on the three surface colours: lowest ratio **5.34:1** (violet on panel); body text 11.2–12.5:1. All pass AA (4.5:1).
- Keyboard: Fleet canvas (arrows, Home/End, Enter) and the replay slider (arrows, PageUp/Down, Home/End) verified by key events in a real browser and in tests; event-log rows have a real button; skip link and focus-on-route-change added.
- Not done: an automated axe audit, and screen-reader testing with a real assistive technology.
