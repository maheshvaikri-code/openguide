"""The experiment scripts must at least import: a removed default once left one of them unable to start."""
import importlib

import pytest

pytest.importorskip("torch")

SCRIPTS = [
    "scripts.real_closed_loop", "scripts.replicate_t0", "scripts.replicate_cap", "scripts.replicate_pool2",
    "scripts.pilot_second_model", "scripts.derive_steering_pack", "scripts.real_t0_gate",
    "scripts.replicate_direction_control", "scripts.granite_gain_ladder", "scripts.diagnose_granite_sensitivity",
]


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_experiment_script_imports(name):
    importlib.import_module(name)
