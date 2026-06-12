"""T0 activation steering on a tiny synthetic HF-style model.

No weights, no download — a 4-layer toy stack with the HF `.model.layers`
shape, layers returning a `(hidden,)` tuple. Exercises the full hook path:
per-(layer,step) gain evaluation, norm-preserving injection, Σ-cap, trace
recording, and replay identity.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
import torch.nn as nn  # noqa: E402

from guidancegrid.channels.t0_activation import (  # noqa: E402
    ActivationSteerer,
    decoder_layers,
    inject_torch,
)
from guidancegrid.core.grid import Grid, SignalPack  # noqa: E402

L, D = 4, 8


class _Layer(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.lin = nn.Linear(d, d)

    def forward(self, h):
        return (h + 0.05 * torch.tanh(self.lin(h)),)


class _Inner(nn.Module):
    def __init__(self, d, n):
        super().__init__()
        self.layers = nn.ModuleList([_Layer(d) for _ in range(n)])

    def forward(self, h):
        for layer in self.layers:
            h = layer(h)[0]
        return h


class _TinyModel(nn.Module):
    def __init__(self, d=D, n=L):
        super().__init__()
        self.model = _Inner(d, n)

    def forward(self, h):
        return self.model(h)


def _grid_pack():
    grid = Grid(layers=L, frame=8)
    grid.field("anchor").write_ramp(1, 3, 0, 16, 0.1, 0.6)   # ramp over steps
    pack = SignalPack("tiny", D)
    rng = np.random.default_rng(0)
    for layer in range(L):
        v = rng.standard_normal(D).astype(np.float32)
        pack.set_vector("anchor", layer, v / np.linalg.norm(v))
    return grid, pack


def _manifest(pack):
    return {"model": "tiny", "pack_hash": pack.hash(), "runtime": "ggrid-t0-0.1", "seed": 7}


def test_inject_torch_preserves_norm():
    h = torch.randn(2, 3, D)
    v = torch.randn(D)
    v = v / v.norm()
    out = inject_torch(h, v, 0.5)
    assert torch.allclose(out.norm(dim=-1), h.norm(dim=-1), atol=1e-4)
    assert not torch.allclose(out, h)


def test_decoder_layers_lookup():
    m = _TinyModel()
    assert len(decoder_layers(m)) == L


def test_steering_changes_output_and_records():
    torch.manual_seed(0)
    m = _TinyModel().eval()
    grid, pack = _grid_pack()
    x = torch.randn(1, 5, D)
    with torch.no_grad():
        base = m(x).clone()

    steerer = ActivationSteerer(grid, pack, _manifest(pack), num_layers=L)
    steerer.register(model=m)
    with torch.no_grad():
        steered = m(x)
    steerer.remove()

    assert not torch.allclose(base, steered)          # steering moved the output
    assert steerer.t == 1                              # one forward = one step
    rec = steerer.trace.records[-1]
    assert rec["ev"] == "STEP" and "anchor" in rec["applied"]
    assert steerer.trace.verify()


def test_sigma_cap_enforced_and_recorded():
    torch.manual_seed(0)
    m = _TinyModel().eval()
    grid = Grid(layers=L, frame=8)
    grid.field("anchor").write_const(0, 3, 0, 8, 5.0)   # absurd overdrive
    pack = SignalPack("tiny", D)
    for layer in range(L):
        pack.set_vector("anchor", layer, np.ones(D, np.float32) / np.sqrt(D))
    steerer = ActivationSteerer(grid, pack, _manifest(pack), sigma_cap=1.25, num_layers=L)
    steerer.register(model=m)
    with torch.no_grad():
        m(torch.randn(1, 3, D))
    steerer.remove()
    rec = steerer.trace.records[-1]
    assert rec["sigma_peak"] > 1.25
    assert rec["norm_corr"] > 0                         # column was scaled down


def test_replay_identity_bit_identical_heads():
    def run():
        torch.manual_seed(0)
        m = _TinyModel().eval()
        grid, pack = _grid_pack()
        st = ActivationSteerer(grid, pack, _manifest(pack), num_layers=L)
        st.register(model=m)
        x = torch.ones(1, 4, D)
        with torch.no_grad():
            for _ in range(6):
                m(x)
        st.remove()
        return st.trace.head
    assert run() == run()                               # replay key holds


def test_control_channel_override_recorded():
    torch.manual_seed(0)
    m = _TinyModel().eval()
    grid, pack = _grid_pack()
    st = ActivationSteerer(grid, pack, _manifest(pack), num_layers=L)
    st.register(model=m)
    st.set_gain("anchor", 0.0, source="operator")       # mute
    with torch.no_grad():
        m(torch.randn(1, 3, D))
    st.remove()
    evs = [r["ev"] for r in st.trace.records]
    assert "OVERRIDE" in evs
    # muted: anchor gain zero -> not applied this step
    step_rec = [r for r in st.trace.records if r["ev"] == "STEP"][-1]
    assert "anchor" not in step_rec["applied"]
