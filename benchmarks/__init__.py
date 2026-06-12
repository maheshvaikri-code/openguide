"""OpenGuide benchmarks (simulated).

These harnesses encode the *methodology* from the blueprint — the intervention
comparison (T1 benchmark), turn-wise drift divergence, and fleet generation —
against a deterministic mock agent. They run offline with no API keys. Real-model
numbers (closed + open) require keys/weights and replace the simulated results;
every output is labeled accordingly.
"""
from .agent_sim import STRATEGIES, ScenarioResult, run_scenario

__all__ = ["run_scenario", "ScenarioResult", "STRATEGIES"]
