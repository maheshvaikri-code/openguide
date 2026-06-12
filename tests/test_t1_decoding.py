"""T1 constrained decoding: logit masking + constraints."""
import numpy as np

from guidancegrid.channels.t1_decoding import (
    AllowlistConstraint,
    ConstrainedDecoder,
    SequenceConstraint,
    apply_logit_mask,
    outlines_available,
)


def test_apply_logit_mask_numpy():
    logits = np.array([1.0, 5.0, 2.0, 9.0])
    masked = apply_logit_mask(logits, {0, 2})
    assert masked[0] == 1.0 and masked[2] == 2.0
    assert masked[1] == float("-inf") and masked[3] == float("-inf")
    assert int(np.argmax(masked)) == 2          # 9.0 was masked out


def test_apply_logit_mask_none_is_identity():
    logits = np.array([1.0, 2.0])
    assert np.allclose(apply_logit_mask(logits, None), logits)


def test_allowlist_constraint_decode():
    dec = ConstrainedDecoder(AllowlistConstraint({1, 3}))
    logits = np.array([10.0, 1.0, 9.0, 2.0])    # argmax would be 0
    assert dec.next_token(logits, []) == 3       # but only {1,3} allowed -> 3


def test_sequence_constraint_restricts_paths():
    # tool names tokenized as id paths: "search"=[5,6], "shell"=[5,7]
    c = SequenceConstraint([[5, 6], [5, 7]])
    assert c.allowed([]) == {5}                  # both start with 5
    assert c.allowed([5]) == {6, 7}              # then diverge
    assert c.allowed([5, 6]) is None             # sequence complete


def test_constrained_decoder_with_torch_logits():
    import pytest
    torch = pytest.importorskip("torch")
    dec = ConstrainedDecoder(AllowlistConstraint({2}))
    logits = torch.tensor([9.0, 8.0, 1.0, 7.0])
    masked = dec.mask_logits(logits, [])
    assert masked[0].item() == float("-inf")
    assert dec.next_token(logits, []) == 2


def test_outlines_available_is_boolean():
    assert isinstance(outlines_available(), bool)
