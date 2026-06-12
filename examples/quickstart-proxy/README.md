# Quickstart: governed in 30 lines

The smallest end-to-end OpenGuide loop — no Docker, no network. It builds the
proxy in-process against a mock model that drifts, sends a few governed calls,
and prints the behavioral state the control plane recorded.

```bash
python examples/quickstart-proxy/run.py
```

Expected: drift climbs as the mock model degrades, a `re_anchor` fires, the next
turn recovers, and the hash-chained trace verifies — the same loop the real
proxy runs against a live OpenAI-compatible endpoint.

To run against a real model instead, start the stack in
[`deploy/compose/`](../../deploy/compose/) and point the OpenAI SDK at it (see
[`integrations/openai_sdk_example.py`](../../integrations/openai_sdk_example.py)).
