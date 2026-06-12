"""Store: content-addressed blob store + fleet index over runs.

CAS keys are content hashes (idempotent, cache-friendly). The fleet index holds
one row per run for queries like "runs where drift > X" or "by contract_hash".
sqlite now; the same interface backs postgres later.
"""
from .sqlite_store import RunRecord, Store

__all__ = ["Store", "RunRecord"]
