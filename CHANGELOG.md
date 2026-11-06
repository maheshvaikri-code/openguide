# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Console** (`console/`): Vite + React + TypeScript dashboard with Fleet, Run replay,
  Trajectory (3D), Contracts, Packs and Audit pages. `make console-demo` seeds simulated
  data and serves it from the proxy. See `console/README.md` and ADR-001.
- Proxy endpoints (additive): `GET /v1/openguide/contracts`, `GET /v1/openguide/contracts/{hash}`,
  `POST /v1/openguide/contracts/validate` (dry run), `GET /v1/openguide/packs`,
  `GET /v1/openguide/runs/{id}`; the trace payload now includes a `chain` report saying where the
  hash chain breaks (and what could have caused it) when verification fails. Static Console mount at `/console`.
- `OPENGUIDE_PACKS_DIR` and `OPENGUIDE_CONSOLE_DIR` settings.
- `benchmarks/seed_sweep.py`: 50-seed sweep of the simulated T1 benchmark.
- `docs/paper/`: arXiv preprint draft (LaTeX) with a generated bibliography.
- Apache-2.0 `LICENSE`.

### Security
- **The proxy control plane (`/v1/openguide/*`) is open unless `OPENGUIDE_ADMIN_TOKEN` is set.** Now logged as a
  startup warning, shown as a notice in the Console, and documented in `console/README.md`. Set a token before exposing it.
- Contract endpoints reject bodies over 256 KB (413); `GET /v1/openguide/runs` clamps `limit` to 1-10 000;
  registering malformed JSON returns 422 instead of 500; pack cards with the wrong shape are skipped and reported.
- New unauthenticated, non-sensitive `GET /v1/openguide/status` returns `{"auth_required": bool}`.

### Fixed
- CI: `scikit-learn` added to the `dev` extra (probe tests); Python 3.10 timestamp parsing
  of a trailing `Z` in `tools/doctrine_metrics.py`.
- `Reconciler` docstring said "weighted mean"; drift is a clipped weighted sum (per the
  state spec). Tests now pin the sum semantics.
