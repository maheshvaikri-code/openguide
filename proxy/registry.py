"""Contract + measure registry for the proxy.

Maps an ``X-OpenGuide-Contract`` hash to a loaded OBC contract, and compiles it
on demand per target model (cached by (contract_hash, model)). Also holds the
MeasureRegistry the reconciler reads — deployments wire real sensors here; an
unwired measure degrades to a recorded sensor gap, never a crash.
"""
from __future__ import annotations

import os
from typing import Any

from guidancegrid.compiler import CompiledContract, compile_contract
from guidancegrid.obc import contract_hash, load_contract, validate_contract
from guidancegrid.sensors import MeasureRegistry


class ContractRegistry:
    def __init__(self, measures: MeasureRegistry | None = None):
        self._contracts: dict[str, dict[str, Any]] = {}     # hash -> OBC dict
        self._compiled: dict[tuple[str, str], CompiledContract] = {}
        self.measures = measures or MeasureRegistry()

    # ── registration ─────────────────────────────────────────────────
    def register(self, contract: dict[str, Any]) -> str:
        contract = validate_contract(contract)
        h = contract_hash(contract)
        self._contracts[h] = contract
        return h

    def load_file(self, path: str) -> str:
        return self.register(load_contract(path))

    def load_dir(self, directory: str) -> list[str]:
        hashes = []
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".toml"):
                hashes.append(self.load_file(os.path.join(directory, fn)))
        return hashes

    # ── lookup ───────────────────────────────────────────────────────
    def has(self, contract_hash_: str) -> bool:
        return contract_hash_ in self._contracts

    def get(self, contract_hash_: str) -> dict[str, Any] | None:
        return self._contracts.get(contract_hash_)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        """(hash, contract) pairs in registration order."""
        return list(self._contracts.items())

    def compiled(self, contract_hash_: str, model_id: str) -> CompiledContract:
        key = (contract_hash_, model_id)
        if key not in self._compiled:
            obc = self._contracts[contract_hash_]
            self._compiled[key] = compile_contract(obc, model_id)
        return self._compiled[key]
