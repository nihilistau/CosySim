"""Tests for synthetic task data generators."""
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prime_encoding.tasks import (
    VOCAB_SIZE,
    MARKER_TOKEN,
    QUERY_TOKEN,
    generate_copy_batch,
    generate_reversal_batch,
    generate_needle_batch,
    generate_first_last_batch,
)


class TestCopyTask:
    def test_shape(self):
        batch = generate_copy_batch(batch_size=8, seq_len=64, seed=42)
        assert batch.inputs.shape == (8, 64)
        assert batch.targets.shape == (8, 64)

    def test_targets_match_inputs(self):
        batch = generate_copy_batch(batch_size=4, seq_len=32, seed=42)
        half = 16
        # Second half of targets should equal first half of inputs
        assert torch.equal(batch.targets[:, half:half + half], batch.inputs[:, :half])

    def test_deterministic(self):
        b1 = generate_copy_batch(batch_size=4, seq_len=32, seed=42)
        b2 = generate_copy_batch(batch_size=4, seq_len=32, seed=42)
        assert torch.equal(b1.inputs, b2.inputs)


class TestReversalTask:
    def test_shape(self):
        batch = generate_reversal_batch(batch_size=8, seq_len=64, seed=42)
        assert batch.inputs.shape == (8, 64)
        assert batch.targets.shape == (8, 64)

    def test_targets_are_reversed(self):
        batch = generate_reversal_batch(batch_size=4, seq_len=32, seed=42)
        half = 16
        input_data = batch.inputs[:, :half]
        target_data = batch.targets[:, half:half + half]
        assert torch.equal(target_data, input_data.flip(dims=[1]))


class TestNeedleTask:
    def test_shape(self):
        batch = generate_needle_batch(batch_size=8, seq_len=128, seed=42)
        assert batch.inputs.shape == (8, 128)
        assert batch.targets.shape == (8,)  # classification

    def test_marker_present(self):
        batch = generate_needle_batch(batch_size=16, seq_len=128, seed=42)
        for i in range(16):
            pos = batch.targets[i].item()
            assert batch.inputs[i, pos] == MARKER_TOKEN

    def test_query_at_end(self):
        batch = generate_needle_batch(batch_size=4, seq_len=128, seed=42)
        assert (batch.inputs[:, -1] == QUERY_TOKEN).all()

    def test_positions_vary(self):
        batch = generate_needle_batch(batch_size=32, seq_len=256, seed=42)
        positions = batch.targets.unique()
        assert len(positions) > 5  # should have diverse positions


class TestFirstLastTask:
    def test_shape(self):
        batch = generate_first_last_batch(batch_size=8, seq_len=128, seed=42)
        assert batch.inputs.shape == (8, 128)
        assert batch.targets.shape == (8,)  # classification

    def test_target_matches_first_token(self):
        batch = generate_first_last_batch(batch_size=16, seq_len=128, seed=42)
        assert torch.equal(batch.targets, batch.inputs[:, 0])

    def test_query_at_end(self):
        batch = generate_first_last_batch(batch_size=4, seq_len=128, seed=42)
        assert (batch.inputs[:, -1] == QUERY_TOKEN).all()


class TestVocabBounds:
    """All tasks should produce tokens within vocab range."""

    @pytest.mark.parametrize("gen", [
        generate_copy_batch, generate_reversal_batch,
        generate_needle_batch, generate_first_last_batch,
    ])
    def test_input_in_range(self, gen):
        batch = gen(batch_size=8, seq_len=64, seed=42)
        assert batch.inputs.min() >= 0
        assert batch.inputs.max() < VOCAB_SIZE
