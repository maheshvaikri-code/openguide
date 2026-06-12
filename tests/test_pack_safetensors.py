"""SignalPack safetensors round-trip + pack-build script."""
import numpy as np

from guidancegrid.core.grid import SignalPack


def _pack():
    p = SignalPack("tiny-model", 8)
    rng = np.random.default_rng(0)
    for layer in range(4):
        p.set_vector("anchor", layer, rng.standard_normal(8).astype(np.float32))
        p.set_vector("precision", layer, rng.standard_normal(8).astype(np.float32))
    return p


def test_safetensors_roundtrip_preserves_hash(tmp_path):
    p = _pack()
    path = str(tmp_path / "pack.safetensors")
    h = p.save_safetensors(path)
    assert h == p.hash()
    back = SignalPack.load_safetensors(path)
    assert back.hash() == h
    assert back.model_id == "tiny-model"
    assert np.allclose(back.get("anchor", 2), p.get("anchor", 2))


def test_build_pack_script_synthetic(tmp_path):
    import importlib.util
    import json
    import os

    here = os.path.dirname(__file__)
    spec = importlib.util.spec_from_file_location(
        "build_pack", os.path.join(here, "..", "packs", "build_pack.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pack = mod.synthetic_pack("synthetic-test", layers=6, d=16)
    out = tmp_path / "p"
    out.mkdir()
    h = pack.save_safetensors(str(out / "pack.safetensors"))
    card = mod.eval_card(pack, "synthetic-test", 6)
    with open(out / "eval_card.json", "w") as f:
        json.dump(card, f)

    assert card["pack_hash"] == h
    assert card["signals"] == ["anchor", "precision", "explore", "syc-damp"]
    assert card["status"] == "synthetic"
    # eval slots present but unfilled (require a real model)
    assert card["evals"]["mmlu_delta_at_gain"]["0.4"] is None
