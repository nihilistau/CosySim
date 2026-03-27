"""Tests for the TinyTransformer model."""
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prime_encoding.model import TinyTransformer, create_model


class TestTinyTransformer:
    def test_forward_shape(self):
        model = create_model("sinusoidal", vocab_size=64, d_model=128)
        x = torch.randint(0, 64, (2, 50))
        out = model(x)
        assert out.shape == (2, 50, 64)

    def test_parameter_count(self):
        model = create_model("sinusoidal")
        params = model.count_parameters()
        assert params > 0
        assert params < 1_000_000  # should be tiny

    @pytest.mark.parametrize("pe_type", ["sinusoidal", "prime", "zeta", "hybrid"])
    def test_all_pe_types_work(self, pe_type):
        model = create_model(pe_type, vocab_size=64, d_model=128)
        x = torch.randint(0, 64, (1, 32))
        out = model(x)
        assert out.shape == (1, 32, 64)
        assert not torch.isnan(out).any()

    def test_prime_with_alpha(self):
        model = create_model("prime", alpha=0.5)
        x = torch.randint(0, 64, (1, 32))
        out = model(x)
        assert out.shape == (1, 32, 64)

    def test_gradient_flow(self):
        model = create_model("sinusoidal")
        x = torch.randint(0, 64, (2, 16))
        out = model(x)
        loss = out.sum()
        loss.backward()
        # Check that embedding has gradients
        assert model.embedding.weight.grad is not None
        assert model.embedding.weight.grad.abs().sum() > 0
