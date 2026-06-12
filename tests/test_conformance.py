"""Wire the independent spec conformance runner into CI.

This guards the Phase 0 gate: the spec's golden vectors must stay in sync with
the reference implementation, and the independent runner (which never imports
guidancegrid) must reproduce every hash.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.abspath(os.path.join(HERE, "..", "spec", "conformance"))


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_conformance", os.path.join(CONF, "run_conformance.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_independent_conformance_runner_passes():
    runner = _load_runner()
    assert runner.run() is True


def test_golden_vectors_match_reference_impl():
    """The reference canonical encoder must agree with the stored golden hashes."""
    import glob
    import json

    from guidancegrid.core.canonical import canonical_json, chash

    for path in glob.glob(os.path.join(CONF, "vectors", "canonical", "*.json")):
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        assert canonical_json(v["input"]) == v["canonical"], path
        assert chash(v["input"]) == v["hash"], path
