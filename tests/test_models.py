"""Model profiles: where a model lives, how it is loaded, and the steering band mapped to its depth."""
import os

import pytest

from benchmarks import models


def test_the_band_keeps_qwens_relative_position_at_any_depth():
    assert models.relative_band(28) == (10, 19)            # Qwen2.5-1.5B: the band every earlier result used
    assert models.relative_band(40) == (14, 27)            # Granite-3.1-2B
    assert models.relative_band(26) == (9, 18)             # Gemma-2-2B (the original plan)


@pytest.mark.parametrize("depth", [12, 24, 28, 32, 40, 80])
def test_a_band_is_always_a_valid_range_inside_the_model(depth):
    lo, hi = models.relative_band(depth)
    assert 0 <= lo < hi < depth                            # never the last layer (read after the final norm)


def test_the_qwen_profile_reproduces_the_registered_setup():
    q = models.QWEN
    assert q.band == (10, 19) and q.dtype == "float16" and q.n_layers == 28
    assert q.served_name == "local:qwen2.5-1.5b-instruct"
    assert q.path.replace(chr(92), "/").endswith(".models/Qwen2.5-1.5B-Instruct")


def test_the_granite_profile_maps_the_band_to_its_depth_and_uses_bfloat16():
    g = models.GRANITE
    assert g.n_layers == 40 and g.band == models.relative_band(40) == (14, 27)
    assert g.dtype == "bfloat16"
    assert g.served_name == "local:granite-3.1-2b-instruct" and g.key == "granite-3.1-2b-instruct"
    assert g.hf_repo == "ibm-granite/granite-3.1-2b-instruct"


def test_each_model_has_its_own_pack_file():
    assert models.QWEN.pack_path != models.GRANITE.pack_path
    assert models.GRANITE.pack_path.endswith("granite-3.1-2b-instruct.safetensors")


def test_profiles_are_found_by_key_and_unknown_keys_are_an_error():
    assert models.get("granite") is models.GRANITE and models.get("qwen") is models.QWEN
    with pytest.raises(ValueError, match="model"):
        models.get("gpt")


def test_the_pinned_revision_must_match_what_the_local_files_record(tmp_path):
    import dataclasses
    import os

    dl = tmp_path / ".cache" / "huggingface" / "download"
    dl.mkdir(parents=True)
    (dl / "a.safetensors.metadata").write_text("abc123\netag\n123\n", encoding="utf-8")
    (dl / "config.json.metadata").write_text("abc123\netag\n123\n", encoding="utf-8")
    prof = dataclasses.replace(models.GRANITE, path=str(tmp_path), revision="abc123")
    assert models.local_revision(str(tmp_path)) == "abc123"
    assert models.revision_ok(prof)[0] is True
    other = dataclasses.replace(prof, revision="def456")
    ok, why = models.revision_ok(other)
    assert ok is False and "abc123" in why and "def456" in why
    (dl / "tokenizer.json.metadata").write_text("zzz999\netag\n1\n", encoding="utf-8")   # mixed revisions
    assert models.local_revision(str(tmp_path)) is None and models.revision_ok(prof)[0] is False
    assert models.revision_ok(dataclasses.replace(prof, revision=None))[0] is True  # no pin: always passes
    assert os.path.exists(str(tmp_path))


def test_the_downloaded_granite_weights_are_the_pinned_revision():
    if not os.path.isdir(models.GRANITE.path):
        pytest.skip("Granite weights are not downloaded here")
    assert models.revision_ok(models.GRANITE)[0] is True
