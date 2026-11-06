# QA + Security Report: drift-gated T0 steering in the proxy (ADR-003)

**Reviews:** independent security review and code review by read-only reviewer agents, then fixes and re-test.
**Scope:** `proxy/steering.py`, `proxy/hf_upstream.py`, `proxy/governance.py`, `guidancegrid/channels/t0_activation.py`,
`guidancegrid/core/trace.py` (`STEER`), the Console's turn panel, `scripts/derive_steering_pack.py`,
`scripts/real_closed_loop.py`.

## What was asked
"Wire it" (T0 activation steering into the live path) and a README "how the pieces fit" diagram.

## Verification (final state)
- `python -m pytest` -> **496 passed**; `ruff check .` clean.
- Console: `tsc --noEmit` clean; `vitest` **197 passed** on two consecutive runs; `vite build` succeeds.
- Real model (GPU): two conversations re-run with the final code reproduce the saved closed-loop results exactly
  (16/16 identical replies each, the same steered turns, chains verify). The derived steering pack has the same hash
  as the pack used in the earlier T0 experiments.
- Measured effect: `benchmarks/REPORT.md` 7.3. **Weak evidence** (n = 5, 2 of 5 conversations drifted, p = 0.50, gain chosen
  after seeing the same conversations). Not a claim that steering works in general.

## Security review: no BLOCKER; two MAJOR, four MINOR, all addressed
| Finding | Disposition |
|---|---|
| MAJOR-1: the gain cap bounds the gain, not the effect: a huge-norm or NaN pack vector replaces the hidden state | **Fixed.** Config refuses non-finite or mis-shaped vectors; `enable_steering` refuses a vector above 4x the model's measured residual norm; optional `expected_pack_hash` pin. Tested. The real pack is at 0.7-1.0x. |
| MAJOR-2: the `STEER` record's gain/band did not describe the gaussian envelope, and pack layers outside the band were steered | **Fixed.** The pack is cut to the band; `gain` documented as the envelope's peak (spec, ADR, docs, Console, REPORT). Behaviour unchanged (every reported number used the envelope). My earlier docstring "constant-gain field" was wrong and is corrected. |
| MINOR-1: a steered stream abandoned by the client left no record | **Fixed** (see code review M1). |
| MINOR-2: incomplete pack validation | **Fixed** with MAJOR-1. |
| MINOR-3: steering silently stops after 1024 steps | **Fixed:** `enable_steering` and `chat` refuse a longer reply length. |
| MINOR-4: ceiling enforced only in the config | **Fixed:** `HFUpstream.chat` rejects a gain above it. |
| INFO: session ids are client-chosen and unauthenticated; an open registry lets a client register a contract that always recovers | **Accepted, documented in ADR-003.** Effect: one generation, at most gain 0.1, in that session only. Pre-existing exposure. |

## Code review: REQUEST-CHANGES (two MAJOR); addressed
| Finding | Disposition |
|---|---|
| M1: a steered generation can leave no `STEER` record (client cancel, scoring failure) | **Fixed differently from the suggestion.** The upstream reports through a `SteerReceipt` that a steered reply was *produced*; the Governor records on that, including when scoring fails or the client closes the stream (marked `"scored": false`). A client that cancels while the model is still writing receives no reply, so nothing is recorded; this is a deliberate choice, documented in the spec and ADR. |
| M2: every steered run showed "N records were left out of the replay" in the Console | **Fixed**, with a test. |
| MINOR: `preflight_stream` path untested; `pack_in_band` use untested | **Fixed:** tests added for both. |
| MINOR: duplicate / early `STEER` after an abandoned stream | **Documented** in the spec; the Console ignores unscored records. |
| MINOR: Console implied a uniform gain | **Fixed** ("peak gain"). |
| MINOR: same-session concurrent requests read the same steering state | **Documented** in ADR-003 (same pattern as the pending re-anchor). |
| MINOR: no command-line switch | **Documented** (README, ADR, `docs/t0-steering.md`); configured in Python today. |
| NIT: `.register()` outside the `try` | **Fixed.** |
| NIT: redundant `isfinite`; `Upstream` protocol does not declare `steer` | Left as is (harmless / documented). |

## Known limitations (not fixed)
- Evidence for benefit is small and not independent (see REPORT 7.3). Capability was not re-measured through the loop.
- Steering reacts one turn late, so it cannot prevent the first failure or the "shock" turns.
- One model, one rule set. Hosted APIs cannot be steered.
- No operator switch (CLI/env). `halt` also triggers steering; the proxy still never blocks a halted session (unchanged).
- Tool-loop "latest user message" labelling, the missing `rebuilt_from` manifest field and the fidelity check's raw-reading
  comparison remain as recorded in `docs/qa/console-turn-detail.md`.
