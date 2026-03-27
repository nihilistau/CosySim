"""
Synthetic Tasks — Position-sensitive benchmarks for PE evaluation.
===================================================================

Four tasks designed so that positional encoding quality DIRECTLY determines
performance. Each task requires the model to know, compute, or exploit
position information in a different way.

All tasks use the same vocabulary (64 tokens) and produce (input, target)
tensor pairs. Token 0 is padding, tokens 1-60 are data, tokens 61-63 are
special markers.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Four tasks: copy, reversal, needle, first-last
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import torch


# ──── Constants ──────────────────────────────────────────────────────────────

VOCAB_SIZE = 64
PAD_TOKEN = 0
DATA_TOKENS = list(range(1, 51))      # 50 data tokens
MARKER_TOKEN = 61                      # special marker for needle task
QUERY_TOKEN = 62                       # query marker
ANSWER_PREFIX = 63                     # answer prefix marker
NUM_DATA_TOKENS = len(DATA_TOKENS)


# ──── Task Base ──────────────────────────────────────────────────────────────

@dataclass
class TaskBatch:
    """A batch of (input, target) pairs for training or evaluation."""
    inputs: torch.Tensor    # (batch_size, seq_len)
    targets: torch.Tensor   # (batch_size, seq_len) or (batch_size,)
    task_name: str
    seq_len: int


# ──── Task 1: Copy ──────────────────────────────────────────────────────────
# Input:  [A, B, C, D, | PAD... | QUERY, PAD...]
# Target: [PAD...         | A, B, C, D]
#
# The model sees a sequence, then must reproduce it in the second half.
# Tests: exact position memory — model must know WHERE each token was.

def generate_copy_batch(
    batch_size: int = 32,
    seq_len: int = 128,
    seed: int | None = None,
) -> TaskBatch:
    """Generate a copy task batch.

    The first half contains random data tokens. The target is to reproduce
    those same tokens in the second half, in the same order.

    Args:
        batch_size: Number of examples.
        seq_len: Total sequence length (data fills first half).
        seed: Random seed for reproducibility.

    Returns:
        TaskBatch with inputs and targets.
    """
    if seed is not None:
        torch.manual_seed(seed)

    half = seq_len // 2

    # Random data tokens in the first half
    data = torch.randint(1, NUM_DATA_TOKENS + 1, (batch_size, half))

    # Input: [data | QUERY | PAD...]
    inputs = torch.zeros(batch_size, seq_len, dtype=torch.long)
    inputs[:, :half] = data
    inputs[:, half] = QUERY_TOKEN

    # Target: [PAD... | data]  — model must predict data tokens in second half
    targets = torch.zeros(batch_size, seq_len, dtype=torch.long)
    targets[:, half:half + half] = data  # copy data to second half

    return TaskBatch(inputs=inputs, targets=targets, task_name="copy", seq_len=seq_len)


# ──── Task 2: Reversal ──────────────────────────────────────────────────────
# Input:  [A, B, C, D | QUERY | PAD...]
# Target: [PAD...       | D, C, B, A]
#
# Tests: relative position computation — model must map pos_i to pos_(n-1-i).

def generate_reversal_batch(
    batch_size: int = 32,
    seq_len: int = 128,
    seed: int | None = None,
) -> TaskBatch:
    """Generate a reversal task batch.

    Args:
        batch_size: Number of examples.
        seq_len: Total sequence length.
        seed: Random seed.

    Returns:
        TaskBatch with inputs and reversed targets.
    """
    if seed is not None:
        torch.manual_seed(seed)

    half = seq_len // 2

    data = torch.randint(1, NUM_DATA_TOKENS + 1, (batch_size, half))

    inputs = torch.zeros(batch_size, seq_len, dtype=torch.long)
    inputs[:, :half] = data
    inputs[:, half] = QUERY_TOKEN

    # Target: reversed data in second half
    targets = torch.zeros(batch_size, seq_len, dtype=torch.long)
    targets[:, half:half + half] = data.flip(dims=[1])

    return TaskBatch(inputs=inputs, targets=targets, task_name="reversal", seq_len=seq_len)


# ──── Task 3: Needle in Haystack ────────────────────────────────────────────
# Input:  [PAD, PAD, ..., MARKER, PAD, ..., PAD, QUERY]
# Target: [position_of_marker] (single integer, classification)
#
# A single MARKER_TOKEN is placed at a random position in a sea of padding.
# The model must output the position. Tests: long-range position discrimination.
# This directly measures "lost in the middle" — can the model find a token
# regardless of where it is in the sequence?

def generate_needle_batch(
    batch_size: int = 32,
    seq_len: int = 256,
    seed: int | None = None,
) -> TaskBatch:
    """Generate a needle-in-haystack batch.

    Args:
        batch_size: Number of examples.
        seq_len: Total sequence length (needle can be anywhere).
        seed: Random seed.

    Returns:
        TaskBatch with targets as position indices (batch_size,).
    """
    if seed is not None:
        torch.manual_seed(seed)

    # Fill with random noise tokens (not PAD — makes it harder)
    inputs = torch.randint(1, 10, (batch_size, seq_len))

    # Place one MARKER at a random position (not first or last)
    positions = torch.randint(1, seq_len - 1, (batch_size,))
    for i in range(batch_size):
        inputs[i, positions[i]] = MARKER_TOKEN

    # Last token is QUERY
    inputs[:, -1] = QUERY_TOKEN

    # Target: the position of the marker (classification over seq_len positions)
    targets = positions

    return TaskBatch(inputs=inputs, targets=targets, task_name="needle", seq_len=seq_len)


# ──── Task 4: First-Last Dependency ─────────────────────────────────────────
# Input:  [KEY_TOKEN, noise, noise, ..., noise, QUERY]
# Target: [KEY_TOKEN] (single token, classification)
#
# The first token determines what the last output should be. Everything
# in between is random noise. Tests: information flow across full context.
# Longer sequences = harder (more noise to attend through).

def generate_first_last_batch(
    batch_size: int = 32,
    seq_len: int = 256,
    seed: int | None = None,
) -> TaskBatch:
    """Generate a first-last dependency batch.

    Args:
        batch_size: Number of examples.
        seq_len: Total sequence length.
        seed: Random seed.

    Returns:
        TaskBatch with targets as the first token (batch_size,).
    """
    if seed is not None:
        torch.manual_seed(seed)

    # Random noise fill
    inputs = torch.randint(1, NUM_DATA_TOKENS + 1, (batch_size, seq_len))

    # First token is the "key" (what the model must remember)
    keys = torch.randint(1, NUM_DATA_TOKENS + 1, (batch_size,))
    inputs[:, 0] = keys

    # Last token is QUERY
    inputs[:, -1] = QUERY_TOKEN

    # Target: the key token
    targets = keys

    return TaskBatch(inputs=inputs, targets=targets, task_name="first_last", seq_len=seq_len)


# ──── Task Registry ─────────────────────────────────────────────────────────

TASK_GENERATORS = {
    "copy": generate_copy_batch,
    "reversal": generate_reversal_batch,
    "needle": generate_needle_batch,
    "first_last": generate_first_last_batch,
}

# Which tasks produce sequence targets vs classification targets
SEQUENCE_TASKS = {"copy", "reversal"}           # target shape: (batch, seq_len)
CLASSIFICATION_TASKS = {"needle", "first_last"} # target shape: (batch,)

# Recommended sequence lengths per task
TASK_LENGTHS = {
    "copy":       [32, 64, 128, 256],
    "reversal":   [32, 64, 128, 256],
    "needle":     [64, 128, 256, 512],
    "first_last": [64, 128, 256, 512],
}
