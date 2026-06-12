"""Session continuity: behavioral state that feeds forward across calls.

A conversation id maps to one persistent Session holding the Reconciler (and its
accumulating hash-chained Trace), the turn counter, and a pending re-anchor.
The re-anchor computed after turn N is injected into the request of turn N+1 —
this is the "feeds forward" claim made real across separate HTTP calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from guidancegrid.compiler import CompiledContract
from guidancegrid.controller import Reconciler
from guidancegrid.sensors import MeasureRegistry


@dataclass
class Session:
    session_id: str
    compiled: CompiledContract
    reconciler: Reconciler
    turn: int = 0
    pending_reanchor: str | None = None
    max_drift: float = 0.0
    recoveries: int = 0
    halted: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    """In-memory session store (pluggable to a persistent backend later)."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str, compiled: CompiledContract,
                      measures: MeasureRegistry, manifest: dict[str, Any]) -> Session:
        sess = self._sessions.get(session_id)
        if sess is None:
            rc = Reconciler(compiled, measures, manifest)
            sess = Session(session_id=session_id, compiled=compiled, reconciler=rc)
            self._sessions[session_id] = sess
        return sess

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._sessions)
