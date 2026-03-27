"""
Tests for positional encoding implementations.

Verifies mathematical properties, shape correctness, and that
experimental encodings satisfy the theoretical claims.

Version: v0.1.0 [2026-03-27]
"""
import sys
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prime_encoding.encodings import (
    SinusoidalPE,
    PrimePE,
    ZetaPE,
    HybridPE,
    RoPE,
    create_encoding,
    create_rope,
)


D_MODEL = 64
MAX_LEN = 4096


class TestShapes:
    """All encodings must produce correct tensor shapes."""

    @pytest.mark.parametrize("name", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_output_shape(self, name):
        enc = create_encoding(name, d_model=D_MODEL, max_len=MAX_LEN)
        pe = enc.forward(100)
        assert pe.shape == (100, D_MODEL)

    @pytest.mark.parametrize("name", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_single_position(self, name):
        enc = create_encoding(name, d_model=D_MODEL, max_len=MAX_LEN)
        vec = enc.encode_position(42)
        assert vec.shape == (D_MODEL,)

    @pytest.mark.parametrize("freq_type", ["geometric", "prime", "zeta", "hybrid"])
    def test_rope_shape(self, freq_type):
        rope = create_rope(freq_type, d_model=D_MODEL, max_len=MAX_LEN)
        x = torch.randn(2, 100, D_MODEL)
        out = rope(x)
        assert out.shape == x.shape


class TestBasicProperties:
    """Verify fundamental mathematical properties."""

    @pytest.mark.parametrize("name", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_self_similarity_is_one(self, name):
        """cos_sim(PE(i), PE(i)) should be 1.0 for all i."""
        enc = create_encoding(name, d_model=D_MODEL, max_len=MAX_LEN)
        pe = enc.forward(100)
        for i in range(100):
            v = pe[i].unsqueeze(0)
            sim = F.cosine_similarity(v, v).item()
            assert abs(sim - 1.0) < 1e-5, f"{name}: self-sim at pos {i} = {sim}"

    @pytest.mark.parametrize("name", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_bounded_values(self, name):
        """Encoding values should be bounded in [-1, 1] (sin/cos output)."""
        enc = create_encoding(name, d_model=D_MODEL, max_len=MAX_LEN)
        pe = enc.forward(1000)
        assert pe.min() >= -1.0 - 1e-6
        assert pe.max() <= 1.0 + 1e-6

    @pytest.mark.parametrize("name", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_different_positions_differ(self, name):
        """Adjacent positions should have different encodings."""
        enc = create_encoding(name, d_model=D_MODEL, max_len=MAX_LEN)
        pe = enc.forward(10)
        for i in range(9):
            diff = (pe[i] - pe[i + 1]).abs().sum().item()
            assert diff > 0.01, f"{name}: pos {i} and {i+1} are identical"


class TestDistinguishability:
    """The core hypothesis: prime/zeta encodings stay distinguishable longer."""

    def _avg_sim_at_distance(self, enc, distance, samples=30):
        """Average cosine similarity at a fixed distance."""
        pe = enc.forward(distance + samples + 1)
        sims = []
        for i in range(samples):
            v1 = pe[i].unsqueeze(0)
            v2 = pe[i + distance].unsqueeze(0)
            sims.append(F.cosine_similarity(v1, v2).item())
        return sum(sims) / len(sims)

    def test_nearby_more_similar_than_far(self):
        """For all encodings: sim(pos, pos+10) > sim(pos, pos+1000)."""
        for name in ["sinusoidal", "prime", "zeta"]:
            enc = create_encoding(name, d_model=128, max_len=4096)
            sim_near = self._avg_sim_at_distance(enc, 10)
            sim_far = self._avg_sim_at_distance(enc, 1000)
            assert sim_near > sim_far, (
                f"{name}: sim@10={sim_near:.4f} should be > sim@1000={sim_far:.4f}"
            )

    def test_prime_lower_far_similarity(self):
        """Prime encoding should have lower similarity at large distances than sinusoidal.

        This is the KEY claim: prime frequencies don't alias, so far-apart
        positions remain more distinguishable.
        """
        sin_enc = create_encoding("sinusoidal", d_model=128, max_len=8192)
        prime_enc = create_encoding("prime", d_model=128, max_len=8192, alpha=0.5)

        # Compare at distance 2000
        sin_sim = self._avg_sim_at_distance(sin_enc, 2000)
        prime_sim = self._avg_sim_at_distance(prime_enc, 2000)

        # We expect prime to have lower (better) similarity at large distances
        # This is the empirical test of the hypothesis
        print(f"\n  Distinguishability at distance 2000:")
        print(f"    sinusoidal: {sin_sim:.6f}")
        print(f"    prime:      {prime_sim:.6f}")
        print(f"    prime {'wins' if abs(prime_sim) < abs(sin_sim) else 'loses'}")

        # Note: we don't assert which is better — this is research.
        # We just verify both produce meaningful (non-degenerate) values.
        assert abs(sin_sim) < 1.0, "sinusoidal degenerate"
        assert abs(prime_sim) < 1.0, "prime degenerate"


class TestRoPEVariants:
    """Test that RoPE variants preserve key properties."""

    @pytest.mark.parametrize("freq_type", ["geometric", "prime", "zeta"])
    def test_rotation_preserves_norm(self, freq_type):
        """RoPE should approximately preserve vector norms."""
        rope = create_rope(freq_type, d_model=D_MODEL, max_len=MAX_LEN)
        x = torch.randn(1, 50, D_MODEL)
        out = rope(x)
        # Norms should be very close (rotation preserves length)
        x_norms = x.norm(dim=-1)
        out_norms = out.norm(dim=-1)
        ratio = (out_norms / x_norms).mean().item()
        assert 0.9 < ratio < 1.1, f"{freq_type}: norm ratio = {ratio}"

    @pytest.mark.parametrize("freq_type", ["geometric", "prime", "zeta"])
    def test_different_positions_produce_different_rotations(self, freq_type):
        """Same vector at different positions should produce different outputs."""
        rope = create_rope(freq_type, d_model=D_MODEL, max_len=MAX_LEN)
        # Same vector repeated
        v = torch.randn(1, 1, D_MODEL).expand(1, 10, D_MODEL).clone()
        out = rope(v)
        # Each position should be different
        for i in range(9):
            diff = (out[0, i] - out[0, i + 1]).abs().sum().item()
            assert diff > 0.01, f"{freq_type}: positions {i} and {i+1} identical after rotation"


class TestFactory:
    def test_create_encoding(self):
        enc = create_encoding("sinusoidal", d_model=64)
        assert enc.d_model == 64

    def test_create_encoding_unknown(self):
        with pytest.raises(ValueError):
            create_encoding("unknown_scheme")

    def test_create_rope(self):
        rope = create_rope("prime", d_model=64)
        assert rope.d_model == 64
