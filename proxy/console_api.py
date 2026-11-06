"""Read-mostly control-plane endpoints that the Console consumes, plus its static mount.

Additive to the proxy API (docs/adr/001-console-stack.md):

  GET  /v1/openguide/contracts            list registered contracts (summaries)
  GET  /v1/openguide/contracts/{hash}     one contract body
  POST /v1/openguide/contracts/validate   dry-run validation, never registers
  GET  /v1/openguide/packs                SignalPack eval cards from a directory
  GET  /v1/openguide/runs/{id}            one fleet-index run summary
  /console                                the built Console (static), if present

Every /v1/openguide/* route honours the admin token via ``require_admin``.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from guidancegrid.core.canonical import chash
from guidancegrid.obc import contract_hash, validate_contract

from .registry import ContractRegistry

Guard = Callable[[Request], JSONResponse | None]


def _summary(h: str, c: dict[str, Any]) -> dict[str, Any]:
    meta = c.get("contract", {})
    return {
        "hash": h,
        "name": meta.get("name"),
        "version": meta.get("version"),
        "enforcement_floor": meta.get("enforcement_floor", "t3"),
        "invariants": len(c.get("invariants", [])),
    }


def chain_report(trace: Any) -> dict[str, Any]:
    """Re-verify a trace's hash chain and say *where* it breaks, claiming no more than is provable.

    Same rule as Trace.verify() (spec/trace): each record's ``prev`` must equal the hash of the
    record before it (the manifest hash for the first), and the last hash must equal the stored
    head. A break between two records proves that *something at or before that point* changed
    (an edit, a removal or a reorder all look alike), so ``break_at`` is the index of the first
    record whose link fails, and the reason lists the possibilities rather than naming a culprit.
    ``checked`` is how many records verified before the break.
    """
    head = chash(trace.manifest)
    if head != trace.genesis:
        return {"ok": False, "checked": 0, "break_at": 0,
                "reason": "the manifest was changed after the run started"}
    n = len(trace.records)
    for i, rec in enumerate(trace.records):
        if rec.get("prev") != head:
            if i == 0:
                return {"ok": False, "checked": 0, "break_at": 0,
                        "reason": "the first record does not link to the manifest: the manifest or "
                                  "the first record was altered, or records before it were removed"}
            return {"ok": False, "checked": i, "break_at": i,
                    "reason": f"the chain breaks between record {i - 1} and record {i}: one of them "
                              "was altered, or records between them were removed or reordered"}
        head = chash(rec)
    if head != trace.head:
        if n == 0:
            return {"ok": False, "checked": 0, "break_at": 0,
                    "reason": "the stored head does not match an empty trace"}
        return {"ok": False, "checked": n, "break_at": n,
                "reason": "the stored head does not match the last record: the last record was "
                          "altered, or later records were removed"}
    return {"ok": True, "checked": n, "break_at": None, "reason": None}


MAX_BODY = 256 * 1024


class BodyTooLarge(Exception):
    pass


async def read_json(req: Request, limit: int = MAX_BODY) -> Any:
    """Parse a JSON body, refusing anything over ``limit`` bytes before it is parsed."""
    declared = req.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise BodyTooLarge
    raw = await req.body()
    if len(raw) > limit:
        raise BodyTooLarge
    return json.loads(raw)


def too_large() -> JSONResponse:
    return JSONResponse({"error": f"request body is larger than {MAX_BODY // 1024} KB"}, status_code=413)


def _valid_card(card: Any) -> bool:
    """The shape the Console relies on; anything else is reported as skipped, not rendered."""
    if not isinstance(card, dict):
        return False
    return (
        isinstance(card.get("model_id"), str)
        and isinstance(card.get("signals"), list)
        and all(isinstance(x, str) for x in card["signals"])
        and isinstance(card.get("evals"), dict)
    )


def read_packs(packs_dir: str | None) -> dict[str, list]:
    """Collect ``<packs_dir>/*/eval_card.json``. Malformed cards are reported, not fatal."""
    packs: list[dict[str, Any]] = []
    skipped: list[str] = []
    if not packs_dir or not os.path.isdir(packs_dir):
        return {"packs": packs, "skipped": skipped}
    for name in sorted(os.listdir(packs_dir)):
        card_path = os.path.join(packs_dir, name, "eval_card.json")
        if not os.path.isfile(card_path):
            continue
        try:
            with open(card_path, encoding="utf-8") as f:
                card = json.load(f)
            if not _valid_card(card):
                raise ValueError("eval card has the wrong shape")
        except (OSError, ValueError):
            skipped.append(name)
            continue
        packs.append({**card, "name": name})
    return {"packs": packs, "skipped": skipped}


def install(app: FastAPI, *, registry: ContractRegistry, store: Any, require_admin: Guard,
            packs_dir: str | None = None, auth_required: bool = False) -> None:
    @app.get("/v1/openguide/status")
    async def status() -> dict[str, bool]:
        # Deliberately unauthenticated and non-sensitive: lets the Console warn when the
        # control plane is open and know whether to ask for a token.
        return {"auth_required": auth_required}

    @app.get("/v1/openguide/contracts")
    async def list_contracts(req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        return {"contracts": [_summary(h, c) for h, c in registry.items()]}

    @app.get("/v1/openguide/contracts/{contract_hash_}")
    async def get_contract(contract_hash_: str, req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        c = registry.get(contract_hash_)
        if c is None:
            return JSONResponse({"error": "no such contract"}, status_code=404)
        return {"hash": contract_hash_, "contract": c}

    @app.post("/v1/openguide/contracts/validate")
    async def validate(req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        try:
            body = await read_json(req)
            if not isinstance(body, dict):
                raise ValueError("contract must be a JSON object")
            c = validate_contract(body)
            return {"ok": True, "hash": contract_hash(c), **{
                k: v for k, v in _summary("", c).items() if k != "hash"}}
        except BodyTooLarge:
            return too_large()
        except Exception as exc:                      # validation / parse error -> 422
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)

    @app.get("/v1/openguide/packs")
    async def packs(req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        return read_packs(packs_dir)

    @app.get("/v1/openguide/runs/{run_id}")
    async def run_detail(run_id: str, req: Request):
        denied = require_admin(req)
        if denied is not None:
            return denied
        if store is None:
            return JSONResponse({"error": "no store configured"}, status_code=501)
        run = store.get_run(run_id)
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return run.__dict__


def mount_console(app: FastAPI, console_dir: str | None) -> bool:
    """Serve the built Console at /console. Returns False (no mount) if it isn't built."""
    if not console_dir or not os.path.isfile(os.path.join(console_dir, "index.html")):
        return False
    app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")
    return True
