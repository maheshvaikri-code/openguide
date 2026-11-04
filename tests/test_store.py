"""sqlite CAS + fleet index."""
from guidancegrid.store import RunRecord, Store


def _run(run_id, contract_hash="sha256:abc", max_drift=0.1, halted=False,
         trace_cas_key=""):
    return RunRecord(
        run_id=run_id, contract_hash=contract_hash, model="openai:gpt-4o", tier="t2",
        turns=50, max_drift=max_drift, recoveries=1, halted=halted, verified=True,
        trace_hash="sha256:deadbeef", trace_cas_key=trace_cas_key, created="2026-06-12",
    )


def test_cas_is_idempotent():
    s = Store()
    k1 = s.put_blob({"b": 1, "a": 2}, "contract")
    k2 = s.put_blob({"a": 2, "b": 1}, "contract")   # same canonical content
    assert k1 == k2
    assert s.has_blob(k1)
    assert s.get_blob(k1) is not None


def test_cas_distinguishes_content():
    s = Store()
    assert s.put_blob({"x": 1}, "c") != s.put_blob({"x": 2}, "c")


def test_run_roundtrip_and_query():
    s = Store()
    s.put_run(_run("r1", max_drift=0.5))
    s.put_run(_run("r2", max_drift=0.1))
    s.put_run(_run("r3", contract_hash="sha256:other", max_drift=0.9, halted=True))

    got = s.get_run("r1")
    assert got is not None and got.max_drift == 0.5

    # query: high-drift runs, ordered desc
    hi = s.query_runs(min_drift=0.4)
    assert [r.run_id for r in hi] == ["r3", "r1"]

    # query: by contract hash
    by_c = s.query_runs(contract_hash="sha256:abc")
    assert {r.run_id for r in by_c} == {"r1", "r2"}

    # query: halted only
    assert [r.run_id for r in s.query_runs(halted=True)] == ["r3"]


def test_run_replace_on_same_id():
    s = Store()
    s.put_run(_run("r1", max_drift=0.2))
    s.put_run(_run("r1", max_drift=0.8))
    assert s.get_run("r1").max_drift == 0.8


def test_run_roundtrip_keeps_trace_cas_key():
    s = Store()
    s.put_run(_run("r1", trace_cas_key="sha256:tracebody"))
    assert s.get_run("r1").trace_cas_key == "sha256:tracebody"
