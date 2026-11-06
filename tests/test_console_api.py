"""Console-facing control-plane endpoints: contracts list/detail/validate, packs, run detail."""
import copy
import json
import os

from fastapi.testclient import TestClient

from guidancegrid.obc import load_contract
from guidancegrid.store import RunRecord, Store
from proxy.app import create_app
from proxy.registry import ContractRegistry
from proxy.upstream import MockUpstream

EX = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")
CONTRACT = os.path.join(EX, "coding-agent-default.toml")
ADMIN = "secret-admin-token"


def _client(tmp_path=None, packs_dir=None, admin=None, with_contract=True):
    reg = ContractRegistry()
    h = reg.load_file(CONTRACT) if with_contract else None
    store = Store()
    app = create_app(registry=reg, upstream=MockUpstream(lambda b: "ok"), store=store,
                     admin_token=admin, packs_dir=packs_dir)
    return TestClient(app), h, reg, store


# ── AC2: list / detail ───────────────────────────────────────────────
def test_contracts_list_has_summary_fields():
    c, h, _, _ = _client()
    body = c.get("/v1/openguide/contracts").json()
    row = body["contracts"][0]
    assert row["hash"] == h
    assert row["name"] == "coding-agent-default"
    assert row["version"] == "0.1.0"
    assert row["enforcement_floor"] == "t3"
    assert row["invariants"] >= 1


def test_contracts_list_empty():
    c, _, _, _ = _client(with_contract=False)
    assert c.get("/v1/openguide/contracts").json() == {"contracts": []}


def test_contract_detail_and_404():
    c, h, _, _ = _client()
    got = c.get(f"/v1/openguide/contracts/{h}").json()
    assert got["hash"] == h and got["contract"]["contract"]["name"] == "coding-agent-default"
    assert c.get("/v1/openguide/contracts/sha256:nope").status_code == 404


# ── AC3: dry-run validation never registers ──────────────────────────
def test_validate_ok_does_not_register():
    c, _, reg, _ = _client(with_contract=False)
    body = load_contract(CONTRACT)
    r = c.post("/v1/openguide/contracts/validate", json=body)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["hash"].startswith("sha256:")
    assert reg.has(r.json()["hash"]) is False          # dry run


def test_validate_invalid_is_422_with_message():
    c, _, _, _ = _client(with_contract=False)
    bad = copy.deepcopy(load_contract(CONTRACT))
    bad["contract"]["enforcement_floor"] = "t9"
    r = c.post("/v1/openguide/contracts/validate", json=bad)
    assert r.status_code == 422 and "enforcement_floor" in r.json()["error"]


def test_validate_malformed_json_is_422():
    c, _, _, _ = _client(with_contract=False)
    r = c.post("/v1/openguide/contracts/validate", content=b"{not json",
               headers={"content-type": "application/json"})
    assert r.status_code == 422 and "error" in r.json()


# ── AC4: packs ───────────────────────────────────────────────────────
def _card(model="qwen2.5-7b"):
    return {"model_id": model, "pack_hash": "sha256:abc", "signals": ["anchor"], "layers": 32,
            "dim": 64, "status": "synthetic",
            "evals": {"mmlu_delta_at_gain": {"0.2": None}, "coherence_ok": None}}


def test_packs_lists_cards(tmp_path):
    d = tmp_path / "qwen"
    d.mkdir()
    (d / "eval_card.json").write_text(json.dumps(_card()), encoding="utf-8")
    c, _, _, _ = _client(packs_dir=str(tmp_path))
    packs = c.get("/v1/openguide/packs").json()["packs"]
    assert len(packs) == 1 and packs[0]["model_id"] == "qwen2.5-7b"
    assert packs[0]["evals"]["mmlu_delta_at_gain"]["0.2"] is None     # null preserved, not 0


def test_packs_empty_or_unconfigured(tmp_path):
    assert _client(packs_dir=str(tmp_path))[0].get("/v1/openguide/packs").json() == \
        {"packs": [], "skipped": []}
    assert _client(packs_dir=None)[0].get("/v1/openguide/packs").json() == \
        {"packs": [], "skipped": []}


def test_packs_malformed_card_is_skipped_not_fatal(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "eval_card.json").write_text(json.dumps(_card()), encoding="utf-8")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "eval_card.json").write_text("{oops", encoding="utf-8")
    body = _client(packs_dir=str(tmp_path))[0].get("/v1/openguide/packs").json()
    assert len(body["packs"]) == 1 and body["skipped"] == ["bad"]


# ── run detail ───────────────────────────────────────────────────────
def test_run_detail_and_404():
    c, h, _, store = _client()
    store.put_run(RunRecord(run_id="r1", contract_hash=h, model="mock:x", tier="t2", turns=10,
                            max_drift=0.2, recoveries=1, halted=False, verified=True,
                            trace_hash="sha256:t"))
    assert c.get("/v1/openguide/runs/r1").json()["run_id"] == "r1"
    assert c.get("/v1/openguide/runs/missing").status_code == 404


# ── AC10: the chain report says WHERE it breaks, and claims no more than it can prove ──
def _trace(n=6):
    from guidancegrid.core.trace import Trace

    t = Trace({"model": "mock:x", "seed": 1})
    for i in range(n):
        t.append({"ev": "STATE", "turn": i, "drift": 0.1 * i})
    return t


def _reload(t):
    """Round-trip through JSON the way stored traces are loaded (genesis is re-derived)."""
    from guidancegrid.core.trace import Trace

    return Trace.from_json(t.to_json())


def test_chain_report_ok():
    from proxy.console_api import chain_report

    assert chain_report(_trace()) == {"ok": True, "checked": 6, "break_at": None, "reason": None}


def test_edited_record_breaks_the_chain_at_the_next_link():
    from proxy.console_api import chain_report

    t = _trace()
    t.records[2]["drift"] = 0.0
    r = chain_report(_reload(t))
    assert r["ok"] is False and r["break_at"] == 3 and r["checked"] == 3
    assert "between record 2 and record 3" in r["reason"]


def test_deleting_a_middle_record_is_not_blamed_on_an_intact_record():
    from proxy.console_api import chain_report

    t = _trace()
    del t.records[3]
    r = chain_report(_reload(t))
    assert r["ok"] is False
    # it may say WHERE the chain breaks and list what could have happened; it must not
    # assert that one specific record was edited
    assert "was changed" not in r["reason"]
    assert "removed" in r["reason"] and "altered" in r["reason"]


def test_chain_report_last_record_and_truncation():
    from proxy.console_api import chain_report

    t = _trace()
    t.records[-1]["drift"] = 9.0
    r = chain_report(_reload(t))
    assert r["ok"] is False and r["break_at"] == 6 and "last record" in r["reason"]

    t2 = _trace()
    t2.records.pop()
    r2 = chain_report(_reload(t2))
    assert r2["ok"] is False and "later records were removed" in r2["reason"]


def test_chain_report_reorder_and_first_record():
    from proxy.console_api import chain_report

    t = _trace()
    t.records[1], t.records[2] = t.records[2], t.records[1]
    assert chain_report(_reload(t))["ok"] is False

    t2 = _trace()
    t2.records[0]["drift"] = 0.5
    r = chain_report(_reload(t2))
    assert r["ok"] is False and r["break_at"] == 1

    t3 = _trace()
    del t3.records[0]
    r3 = chain_report(_reload(t3))
    assert r3["ok"] is False and r3["break_at"] == 0 and "manifest or the first record" in r3["reason"]


def test_chain_report_edited_manifest_of_a_stored_trace():
    from proxy.console_api import chain_report

    t = _trace()
    t.manifest["seed"] = 2                          # edit the manifest in the stored JSON
    r = chain_report(_reload(t))
    assert r["ok"] is False and r["break_at"] == 0


def test_chain_report_agrees_with_verify_for_many_mutations():
    import random

    from proxy.console_api import chain_report

    rnd = random.Random(7)
    for _ in range(200):
        t = _trace(rnd.randint(0, 8))
        if t.records and rnd.random() < 0.8:
            kind = rnd.choice(["edit", "delete", "swap", "prev"])
            i = rnd.randrange(len(t.records))
            if kind == "edit":
                t.records[i]["drift"] = rnd.random() + 5
            elif kind == "delete":
                del t.records[i]
            elif kind == "swap" and len(t.records) > 1:
                j = (i + 1) % len(t.records)
                t.records[i], t.records[j] = t.records[j], t.records[i]
            elif kind == "prev":
                t.records[i]["prev"] = "sha256:" + "0" * 64
        loaded = _reload(t)
        assert chain_report(loaded)["ok"] == loaded.verify()


def test_trace_endpoint_includes_chain_report():
    c, h, _, store = _client()
    t = _trace()
    store.put_run(RunRecord(run_id="t1", contract_hash=h, model="mock:x", tier="t2", turns=6,
                            max_drift=0.5, recoveries=0, halted=False, verified=True,
                            trace_hash=t.head, trace_cas_key=store.put_trace(t)))
    body = c.get("/v1/openguide/runs/t1/trace").json()
    assert body["verified"] is True and body["chain"]["ok"] is True and body["chain"]["checked"] == 6


# ── security review: bounds, status, pack validation ─────────────────
def test_oversized_body_is_rejected_before_parsing():
    c, _, _, _ = _client(with_contract=False)
    big = b'{"a":"' + b"x" * (300 * 1024) + b'"}'
    for path in ("/v1/openguide/contracts/validate", "/v1/openguide/contracts"):
        r = c.post(path, content=big, headers={"content-type": "application/json"})
        assert r.status_code == 413, path


def test_register_malformed_json_is_422_not_500():
    c, _, _, _ = _client(with_contract=False)
    r = c.post("/v1/openguide/contracts", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "error" in r.json()


def test_runs_limit_is_clamped():
    c, _, _, _ = _client()
    assert c.get("/v1/openguide/runs?limit=999999999").status_code == 422
    assert c.get("/v1/openguide/runs?limit=0").status_code == 422
    assert c.get("/v1/openguide/runs?limit=10000").status_code == 200


def test_status_endpoint_reports_whether_auth_is_required():
    open_c, _, _, _ = _client()
    assert open_c.get("/v1/openguide/status").json() == {"auth_required": False}
    locked, _, _, _ = _client(admin=ADMIN)
    assert locked.get("/v1/openguide/status").json() == {"auth_required": True}   # readable without a token


def test_pack_card_with_the_wrong_shape_is_skipped(tmp_path):
    cards = {"empty": {}, "bad_signals": {**_card(), "signals": "anchor"},
             "bad_evals": {**_card(), "evals": []}, "no_model": {"pack_hash": "x"}}
    for name, card in cards.items():
        d = tmp_path / name
        d.mkdir()
        (d / "eval_card.json").write_text(json.dumps(card), encoding="utf-8")
    good = tmp_path / "good"
    good.mkdir()
    (good / "eval_card.json").write_text(json.dumps(_card()), encoding="utf-8")
    body = _client(packs_dir=str(tmp_path))[0].get("/v1/openguide/packs").json()
    assert [p["name"] for p in body["packs"]] == ["good"]
    assert sorted(body["skipped"]) == ["bad_evals", "bad_signals", "empty", "no_model"]


def test_pack_directory_name_wins_over_a_name_inside_the_card(tmp_path):
    d = tmp_path / "real-dir"
    d.mkdir()
    (d / "eval_card.json").write_text(json.dumps({**_card(), "name": "spoofed"}), encoding="utf-8")
    packs = _client(packs_dir=str(tmp_path))[0].get("/v1/openguide/packs").json()["packs"]
    assert packs[0]["name"] == "real-dir"


# ── AC13: admin token ────────────────────────────────────────────────
def test_new_endpoints_require_admin_token_when_configured():
    c, h, _, _ = _client(admin=ADMIN)
    for path in ("/v1/openguide/contracts", f"/v1/openguide/contracts/{h}",
                 "/v1/openguide/packs", "/v1/openguide/runs/x"):
        assert c.get(path).status_code == 401, path
    assert c.post("/v1/openguide/contracts/validate", json={}).status_code == 401
    ok = {"authorization": f"Bearer {ADMIN}"}
    assert c.get("/v1/openguide/contracts", headers=ok).status_code == 200
    assert c.get("/v1/openguide/packs", headers=ok).status_code == 200


def test_runs_endpoint_filters_to_runs_with_a_stored_trace():
    c, h, _, store = _client()
    for i in range(5):
        store.put_run(RunRecord(run_id=f"hot{i}", contract_hash=h, model="mock:x", tier="t2", turns=1,
                                max_drift=0.9, recoveries=0, halted=False, verified=True, trace_hash="t"))
    store.put_run(RunRecord(run_id="kept", contract_hash=h, model="mock:x", tier="t2", turns=1,
                            max_drift=0.1, recoveries=0, halted=False, verified=True, trace_hash="t",
                            trace_cas_key="sha256:k"))
    ids = [r["run_id"] for r in c.get("/v1/openguide/runs?has_trace=true&limit=2").json()["runs"]]
    assert ids == ["kept"]
