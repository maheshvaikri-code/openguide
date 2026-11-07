# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Drift-gated T0 activation steering in the proxy** (opt-in; ADR-003, `docs/t0-steering.md`). With a local-weights
  upstream (`HFUpstream.enable_steering`) and `create_app(..., steering=SteeringConfig(...))`, the generation after a
  turn that needed a correction is steered at a small gain (default and hard cap 0.05, the only gain measured not to damage reasoning); otherwise nothing is
  steered. Each steered turn adds a hash-chained `STEER` trace record, shown in the Console's turn panel. Refused for
  upstreams that cannot steer. A client cannot turn it on or change the gain. New tools:
  `scripts/derive_steering_pack.py`, `scripts/real_closed_loop.py`. Pre-registered replication (60 conversations, one small
  model): recovery 68.5% -> 90.8%, GSM8K drop 1.7 points with steering always on, within the registered bars. Most of the
  benefit comes from the first steered turn, and steering that stays on can hurt (`benchmarks/REPORT.md` 7.4).
- README "How the pieces fit" diagram.
- Opt-in cap on consecutive steered turns (`SteeringConfig(max_consecutive=..., pause_turns=...)`, off by default) and its
  pre-registered study (`docs/preregistration/t0-cap-study.md`, `scripts/replicate_cap.py`).
- Pre-registration of the T0 replication (`docs/preregistration/t0-replication.md`, frozen before the run) and its runner
  (`scripts/replicate_t0.py`, which refuses to start unless the spec is committed) and tested analysis (`benchmarks/replication.py`).
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

### Changed (Console and proxy detail)
- **Opt-in message capture.** New `TURN` trace record (what the user asked, the model's reply, the re-anchor that
  was sent), off by default; enable with `OPENGUIDE_CAPTURE_CONTENT=1`. Inside the hash chain; never in the
  metadata-only view. See ADR-002 and `spec/trace/README.md`.
- Console Run replay: per-turn panel (what was said, rule-by-rule results and the drift arithmetic, the
  contract's response steps), an "Every turn" list, and a panel of what the contract requires.
- Console Fleet: the grid, legend and side panel layout, with the explanation inside the panel that opens when a
  square is clicked (why it has its colour, what the marks mean, what was detected in that run from its own trace,
  run details). Grouping runs into series is an optional "By series" view; richer hover cards.
- `benchmarks/real_rebuild.py`: rebuild saved real-model runs with message text, refusing to write unless every
  turn reproduces the recording exactly.

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
