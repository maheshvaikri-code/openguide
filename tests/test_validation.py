"""Steering fails closed: a model with no validation record of its own is refused (ADR-003, REPORT 7.7)."""
import dataclasses
import os

import numpy as np
import pytest

from benchmarks import models
from guidancegrid.core.grid import STEER_SIGNAL, SignalPack
from proxy import validation as val
from proxy.steering import SteeringConfig

BAND = (1, 4)


def _weights(tmp_path, files, name="w"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    for fname, data in files.items():
        (d / fname).write_bytes(data)
    return str(d)


def _pack(dim=8, band=BAND):
    pack = SignalPack("m", dim)
    for layer in range(*band):
        pack.set_vector(STEER_SIGNAL, layer, np.ones(dim, dtype=np.float32))
    return pack


def _record(path, pack, band=BAND, ceiling=0.05):
    return val.ValidationRecord(
        key="tiny", weights_sha256=val.weights_identity(path), band=band, gain_ceiling=ceiling,
        pack_hash=pack.hash(), evidence=(("benchmarks/results/tiny.json", "abc1234"),))


# -- what identifies a model ----------------------------------------------------------------
def test_the_identity_is_the_same_for_the_same_files_wherever_they_live(tmp_path):
    a = _weights(tmp_path, {"model.safetensors": b"weights"}, name="one")
    b = _weights(tmp_path, {"model.safetensors": b"weights"}, name="two")
    assert val.weights_identity(a) == val.weights_identity(b)


def test_the_identity_changes_when_a_weight_file_changes_or_is_renamed(tmp_path):
    base = val.weights_identity(_weights(tmp_path, {"model.safetensors": b"weights"}, name="a"))
    assert val.weights_identity(_weights(tmp_path, {"model.safetensors": b"weightz"}, name="b")) != base
    assert val.weights_identity(_weights(tmp_path, {"other.safetensors": b"weights"}, name="c")) != base


def test_the_identity_covers_every_shard_and_ignores_files_that_are_neither_weights_nor_config(tmp_path):
    two = val.weights_identity(_weights(tmp_path, {"a.safetensors": b"1", "b.safetensors": b"2"}, name="x"))
    one = val.weights_identity(_weights(tmp_path, {"a.safetensors": b"1"}, name="y"))
    assert two != one
    extra = {"a.safetensors": b"1", "b.safetensors": b"2", "tokenizer.json": b"{}", "vocab.txt": b"v"}
    noisy = val.weights_identity(_weights(tmp_path, extra, name="z"))
    assert noisy == two                                                    # the tokenizer is not part of it


def test_a_directory_with_no_weights_has_no_identity(tmp_path):
    with pytest.raises(ValueError, match="safetensors"):
        val.weights_identity(_weights(tmp_path, {"config.json": b"{}"}))


# -- the one record ---------------------------------------------------------------------------
def test_qwen_is_the_only_validated_model_and_its_record_cites_the_three_studies():
    assert len(val.RECORDS) == 1
    rec = next(iter(val.RECORDS.values()))
    assert rec.key == "qwen2.5-1.5b-instruct" and rec.band == (10, 19) and rec.gain_ceiling == 0.05
    assert rec.pack_hash == "sha256:7d293722ca740ee286715992969ad0f88db58cf894690604412bd5fab701b61f"
    assert rec.dtype == "float16"                                      # the numeric type the evidence ran in
    files = [f for f, _ in rec.evidence]
    assert any(f.endswith("replication_t0.json") for f in files)
    assert any(f.endswith("replication_cap.json") for f in files)
    assert any(f.endswith("replication_pool2.json") for f in files)
    assert all(len(c) >= 7 for _, c in rec.evidence)                   # each with the commit that holds it


def test_the_qwen_record_describes_the_weights_that_were_tested():
    if not os.path.isdir(models.QWEN.path):
        pytest.skip("Qwen weights are not here")
    assert val.weights_identity(models.QWEN.path) in val.RECORDS


# -- deciding ------------------------------------------------------------------------------------
def test_a_model_with_no_record_is_refused_and_the_message_names_the_missing_evidence(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"unknown model"})
    cfg = SteeringConfig(_pack(), BAND, 0.025)
    with pytest.raises(val.NotValidated) as err:
        val.authorise(path, cfg, records={})
    msg = str(err.value)
    assert "no validation record" in msg and "pre-registered" in msg and "experimental" in msg
    assert val.weights_identity(path)[:16] in msg                       # which weights, to find the evidence


def test_a_model_whose_weights_cannot_be_identified_is_refused(tmp_path):
    with pytest.raises(val.NotValidated, match="identify"):
        val.authorise(None, SteeringConfig(_pack(), BAND, 0.025), records={})


def test_a_validated_model_is_accepted_and_gets_its_own_ceiling(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"validated model"})
    pack = _pack()
    rec = _record(path, pack, ceiling=0.04)
    got = val.authorise(path, SteeringConfig(pack, BAND, 0.03), records={rec.weights_sha256: rec})
    assert got.mode == "validated" and got.ceiling == 0.04 and got.record is rec


@pytest.mark.parametrize("what", ["band", "pack", "gain", "ceiling"])
def test_a_validated_model_is_refused_if_the_setup_differs_from_what_was_tested(tmp_path, what):
    path = _weights(tmp_path, {"model.safetensors": b"validated model"})
    pack = _pack(band=(0, 6))
    rec = _record(path, pack, band=BAND, ceiling=0.04)
    cfg = {
        "band": SteeringConfig(pack, (2, 5), 0.03),
        "pack": SteeringConfig(_pack(dim=9, band=(0, 6)), BAND, 0.03),       # a different pack
        "gain": SteeringConfig(pack, BAND, 0.05),
        "ceiling": SteeringConfig(pack, BAND, 0.03, gain_ceiling=0.05),
    }[what]
    with pytest.raises(val.NotValidated, match=what):
        val.authorise(path, cfg, records={rec.weights_sha256: rec})


def test_the_validated_ceiling_may_be_narrowed_but_not_raised(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"validated model"})
    pack = _pack()
    rec = _record(path, pack, ceiling=0.05)
    cfg = SteeringConfig(pack, BAND, 0.02, gain_ceiling=0.03)
    ok = val.authorise(path, cfg, records={rec.weights_sha256: rec})
    assert ok.ceiling == 0.03


# -- the explicit override ------------------------------------------------------------------------
def test_an_experiment_needs_an_explicit_ceiling_and_no_record(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"unknown model"})
    with pytest.raises(ValueError, match="gain_ceiling"):
        val.authorise(path, SteeringConfig(_pack(), BAND, 0.025, experimental=True), records={})
    cfg = SteeringConfig(_pack(), BAND, 0.025, experimental=True, gain_ceiling=0.075)
    got = val.authorise(path, cfg, records={})
    assert got.mode == "experimental" and got.ceiling == 0.075 and got.record is None


def test_an_experiment_works_even_without_a_weights_path(tmp_path):
    cfg = SteeringConfig(_pack(), BAND, 0.025, experimental=True, gain_ceiling=0.05)
    got = val.authorise(None, cfg, records={})
    assert got.mode == "experimental"


def test_experimental_is_off_by_default_and_the_gain_has_no_default():
    assert SteeringConfig(_pack(), BAND, 0.025).experimental is False
    with pytest.raises(TypeError):
        SteeringConfig(_pack(), BAND)                                        # no implicit gain either


def test_no_environment_variable_or_server_setting_can_switch_steering_or_the_override_on():
    from proxy.config import ProxyConfig

    names = {f.name for f in dataclasses.fields(ProxyConfig)}
    assert not [n for n in names if "steer" in n or "experimental" in n]
    import inspect

    src = inspect.getsource(ProxyConfig)
    assert "STEER" not in src.upper() and "EXPERIMENTAL" not in src.upper()


def test_there_is_no_implicit_qwen_ceiling_left_in_the_steering_module():
    import proxy.steering as st

    assert not hasattr(st, "MAX_SAFE_GAIN") and not hasattr(st, "DEFAULT_GAIN")


# -- hardening from the security review ---------------------------------------------------------------
def test_the_identity_follows_the_file_contents_even_if_size_and_mtime_are_unchanged(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"AAAA"})
    f = os.path.join(path, "model.safetensors")
    stamp = os.stat(f).st_mtime_ns
    before = val.weights_identity(path)
    with open(f, "wb") as fh:
        fh.write(b"BBBB")                                                    # same size
    os.utime(f, ns=(stamp, stamp))                                           # same mtime
    assert val.weights_identity(path) != before                              # nothing is cached


def test_the_architecture_config_is_part_of_the_identity(tmp_path):
    def ident(cfg, name):
        files = {"model.safetensors": b"w", "config.json": cfg}
        return val.weights_identity(_weights(tmp_path, files, name=name))

    a, b = ident(b'{"rope": 1}', "a"), ident(b'{"rope": 2}', "b")
    none = val.weights_identity(_weights(tmp_path, {"model.safetensors": b"w"}, name="c"))
    assert len({a, b, none}) == 3


@pytest.mark.parametrize("bad", ["Qwen/Qwen2.5-1.5B-Instruct", "no/such/dir"])
def test_a_hub_id_or_missing_path_is_a_clear_refusal_not_an_os_error(bad):
    with pytest.raises(val.NotValidated, match="local directory"):
        val.weights_identity(bad)


def test_a_path_to_a_single_file_is_a_clear_refusal(tmp_path):
    f = tmp_path / "model.safetensors"
    f.write_bytes(b"w")
    with pytest.raises(val.NotValidated, match="local directory"):
        val.weights_identity(str(f))


def test_the_dtype_the_evidence_ran_in_is_part_of_what_is_validated(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"validated model"})
    pack = _pack()
    rec = dataclasses.replace(_record(path, pack), dtype="float16")
    recs = {rec.weights_sha256: rec}
    cfg = SteeringConfig(pack, BAND, 0.03)
    assert val.authorise(path, cfg, recs, dtype="float16").mode == "validated"
    with pytest.raises(val.NotValidated, match="float16"):
        val.authorise(path, cfg, recs, dtype="bfloat16")
    # a record that does not pin a dtype accepts any
    plain = _record(path, pack)
    assert val.authorise(path, cfg, {plain.weights_sha256: plain}, dtype="bfloat16").mode == "validated"


def test_the_loaded_model_must_report_the_path_that_was_hashed(tmp_path):
    path = _weights(tmp_path, {"model.safetensors": b"validated model"})
    pack = _pack()
    rec = _record(path, pack)
    recs = {rec.weights_sha256: rec}
    cfg = SteeringConfig(pack, BAND, 0.03)
    assert val.authorise(path, cfg, recs, loaded_from=path, check_loaded=True).mode == "validated"
    for wrong in (None, "", str(tmp_path / "elsewhere")):
        with pytest.raises(val.NotValidated, match="loaded"):
            val.authorise(path, cfg, recs, loaded_from=wrong, check_loaded=True)


def test_only_a_real_steering_config_is_accepted():
    class Imposter:
        experimental, gain_ceiling, gain, band, pack_hash = True, 1.0, 0.09, (1, 4), "x"

    with pytest.raises(TypeError, match="SteeringConfig"):
        val.authorise(None, Imposter())


def test_an_authorisation_covers_a_config_only_within_what_it_allowed():
    pack = _pack()
    cfg = SteeringConfig(pack, BAND, 0.03)
    auth = val.Authorisation("validated", 0.05, None, BAND, pack.hash())
    assert auth.not_covered_reason(cfg) is None
    assert auth.not_covered_reason(SteeringConfig(pack, BAND, 0.05)) is None             # at the ceiling
    assert "gain" in auth.not_covered_reason(SteeringConfig(pack, BAND, 0.06))
    assert "band" in auth.not_covered_reason(SteeringConfig(_pack(band=(0, 6)), (2, 5), 0.03))
    assert "pack" in auth.not_covered_reason(SteeringConfig(_pack(dim=9), BAND, 0.03))
    exp = SteeringConfig(pack, BAND, 0.03, experimental=True, gain_ceiling=0.05)
    assert "experimental" in auth.not_covered_reason(exp)                       # validated vs experimental
