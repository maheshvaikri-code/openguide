"""The quickstart example runs and demonstrates the drift -> recover loop."""
import importlib.util
import os

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "quickstart-proxy", "run.py")


def _load():
    spec = importlib.util.spec_from_file_location("quickstart_run", EXAMPLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quickstart_demo_shows_drift_and_recovery():
    mod = _load()
    out = mod.demo()
    drifts = [d for _, d, _ in out["rows"]]
    recoveries = [rec for _, _, rec in out["rows"]]
    assert max(drifts) >= 0.27                      # the injected decay is visible
    assert any(rec == "re_anchor" for rec in recoveries)
    s = out["session"]
    assert s["turns"] == len(out["rows"])
    assert s["trace_verified"] is True
    assert s["recoveries"] >= 1
