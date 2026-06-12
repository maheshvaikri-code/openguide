"""sqlite-backed CAS + fleet index.

Two tables:
  cas(hash PRIMARY KEY, kind, body)         — content-addressed blobs
  runs(run_id PRIMARY KEY, contract_hash, model, tier, turns,
       max_drift, recoveries, halted, verified, trace_hash, created)

The CAS is idempotent: putting the same bytes twice is a no-op. The fleet index
is the query surface the console reads; there is no privileged path.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from ..core.canonical import bhash, canonical_json


@dataclass
class RunRecord:
    run_id: str
    contract_hash: str
    model: str
    tier: str
    turns: int
    max_drift: float
    recoveries: int
    halted: bool
    verified: bool
    trace_hash: str
    created: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cas (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    body BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    contract_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    tier TEXT NOT NULL,
    turns INTEGER NOT NULL,
    max_drift REAL NOT NULL,
    recoveries INTEGER NOT NULL,
    halted INTEGER NOT NULL,
    verified INTEGER NOT NULL,
    trace_hash TEXT NOT NULL,
    created TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_contract ON runs(contract_hash);
CREATE INDEX IF NOT EXISTS idx_runs_drift ON runs(max_drift);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── CAS ──────────────────────────────────────────────────────────
    def put_blob(self, obj: Any, kind: str) -> str:
        """Store a canonical-encodable object; returns its content hash."""
        body = canonical_json(obj).encode("utf-8")
        key = bhash(body)
        self.conn.execute(
            "INSERT OR IGNORE INTO cas(hash, kind, body) VALUES (?,?,?)", (key, kind, body)
        )
        self.conn.commit()
        return key

    def get_blob(self, key: str) -> bytes | None:
        row = self.conn.execute("SELECT body FROM cas WHERE hash=?", (key,)).fetchone()
        return bytes(row["body"]) if row else None

    def has_blob(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM cas WHERE hash=?", (key,)).fetchone() is not None

    # ── fleet index ──────────────────────────────────────────────────
    def put_run(self, run: RunRecord) -> None:
        d = asdict(run)
        self.conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, contract_hash, model, tier, turns, max_drift, recoveries,
                halted, verified, trace_hash, created)
               VALUES (:run_id,:contract_hash,:model,:tier,:turns,:max_drift,:recoveries,
                       :halted,:verified,:trace_hash,:created)""",
            {**d, "halted": int(run.halted), "verified": int(run.verified)},
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def query_runs(self, *, contract_hash: str | None = None, min_drift: float | None = None,
                   halted: bool | None = None, limit: int = 100) -> list[RunRecord]:
        clauses, params = [], []
        if contract_hash is not None:
            clauses.append("contract_hash=?")
            params.append(contract_hash)
        if min_drift is not None:
            clauses.append("max_drift>=?")
            params.append(min_drift)
        if halted is not None:
            clauses.append("halted=?")
            params.append(int(halted))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM runs{where} ORDER BY max_drift DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_run(r) for r in self.conn.execute(sql, params).fetchall()]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"], contract_hash=row["contract_hash"], model=row["model"],
            tier=row["tier"], turns=row["turns"], max_drift=row["max_drift"],
            recoveries=row["recoveries"], halted=bool(row["halted"]),
            verified=bool(row["verified"]), trace_hash=row["trace_hash"], created=row["created"],
        )
