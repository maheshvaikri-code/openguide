# Plan: drift-gated T0 in the proxy (ADR-003)

Class L. Owner asked: "wire it" (T0 / GridRuntime-level steering into the live path) and add a "how the pieces fit" diagram to the README.

## Work packages (each test-first)
1. **Library** `guidancegrid/channels/t0_activation.py`: move `SIGNAL`, `MAX_STEPS`, `steering_context` here from
   `benchmarks/real_t0.py` (which re-exports them, so existing tests and scripts are unchanged).
2. **Trace** `guidancegrid/core/trace.py`: `steer_event(turn, gain, band, pack_hash)`; document `STEER` in `spec/trace/README.md`.
3. **Config** `proxy/steering.py`: `SteeringConfig` (pack, band, gain; validated; `MAX_SAFE_GAIN`), `wants_steering(out)`.
4. **Upstream** `proxy/hf_upstream.py`: `enable_steering(config)`, `supports_steering`, `steer=` on `chat`/`stream`;
   hooks always removed, also on error; `steer > 0` without steering support is an error.
5. **Governor** `proxy/governance.py`, `proxy/session.py`, `proxy/app.py`: `steering=` option; refuse an upstream that cannot steer;
   decide per turn; append `STEER`; passthrough is never steered.
6. **Console**: parse `STEER`; the turn panel says when steering was on and at what gain.
7. **Tools**: `scripts/derive_steering_pack.py` (derive and save a pack), `scripts/real_closed_loop.py` (paired experiment:
   T2 only vs T2 + drift-gated T0, same conversations); `benchmarks/real_model.run_contract(steering=...)`.
8. **Docs**: README "how the pieces fit" diagram, REPORT §7.3 with the measured result, CHANGELOG, QA report.

## Risks
- A steered generation that raises must not leave hooks on the model (test it).
- Steering must not be reachable from client input (test it).
- The experiment may show no benefit over T2 alone; report whatever it shows.

## Verification
pytest (new `tests/test_proxy_steering.py`, `tests/test_hf_upstream.py`, `tests/test_real_t0.py`), `ruff`, Console tests/typecheck/build,
a real-model run through the governed proxy on the GPU.
