"""
Training Loop — Train and evaluate tiny transformers on synthetic tasks.
========================================================================

Trains one model on one task at one sequence length, returning accuracy
and loss curves. The benchmark module calls this repeatedly to compare
all PE schemes.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Training loop with seq/classification task support
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .model import create_model
from .tasks import (
    CLASSIFICATION_TASKS,
    SEQUENCE_TASKS,
    TASK_GENERATORS,
    VOCAB_SIZE,
    TaskBatch,
)


# ──── Device Selection ──────────────────────────────────────────────────────

def get_device() -> torch.device:
    """Get the best available device (CUDA > CPU).

    Set PRIME_PE_CPU=1 to force CPU (useful when CUDA has version issues).
    """
    import os
    if os.environ.get("PRIME_PE_CPU"):
        return torch.device("cpu")
    if torch.cuda.is_available():
        try:
            # Quick sanity check — some CUDA installs are broken
            torch.zeros(1, device="cuda")
            return torch.device("cuda")
        except RuntimeError:
            return torch.device("cpu")
    return torch.device("cpu")


# ──── Training Result ───────────────────────────────────────────────────────

@dataclass
class TrainResult:
    """Results from a single training run."""
    pe_type: str
    task_name: str
    seq_len: int
    final_accuracy: float
    final_loss: float
    best_accuracy: float
    train_steps: int
    train_time_secs: float
    loss_curve: List[float] = field(default_factory=list)
    accuracy_curve: List[float] = field(default_factory=list)
    pe_kwargs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pe_type": self.pe_type,
            "task_name": self.task_name,
            "seq_len": self.seq_len,
            "final_accuracy": round(self.final_accuracy, 4),
            "final_loss": round(self.final_loss, 4),
            "best_accuracy": round(self.best_accuracy, 4),
            "train_steps": self.train_steps,
            "train_time_secs": round(self.train_time_secs, 1),
            "pe_kwargs": self.pe_kwargs,
        }


# ──── Training Loop ─────────────────────────────────────────────────────────

def train_and_evaluate(
    pe_type: str,
    task_name: str,
    seq_len: int,
    train_steps: int = 2000,
    batch_size: int = 32,
    lr: float = 3e-4,
    eval_every: int = 200,
    eval_batches: int = 16,
    seed: int = 42,
    device: Optional[torch.device] = None,
    pe_kwargs: Optional[Dict[str, Any]] = None,
    quiet: bool = False,
) -> TrainResult:
    """Train a tiny transformer on a synthetic task and evaluate.

    Args:
        pe_type: Positional encoding type.
        task_name: Task name (copy, reversal, needle, first_last).
        seq_len: Sequence length for this run.
        train_steps: Number of training steps.
        batch_size: Batch size.
        lr: Learning rate.
        eval_every: Evaluate every N steps.
        eval_batches: Number of batches for evaluation.
        seed: Random seed for reproducibility.
        device: Compute device (auto-detected if None).
        pe_kwargs: Extra PE constructor args.
        quiet: Suppress progress output.

    Returns:
        TrainResult with accuracy, loss, and timing data.
    """
    if device is None:
        device = get_device()

    torch.manual_seed(seed)
    kw = pe_kwargs or {}

    # Create model
    max_len = max(seq_len + 128, 2048)  # ensure PE covers the sequence
    model = create_model(
        pe_type=pe_type,
        vocab_size=VOCAB_SIZE,
        d_model=128,
        max_len=max_len,
        **kw,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    generate = TASK_GENERATORS[task_name]
    is_classification = task_name in CLASSIFICATION_TASKS

    loss_curve: List[float] = []
    accuracy_curve: List[float] = []
    best_acc = 0.0
    t0 = time.time()

    for step in range(1, train_steps + 1):
        model.train()

        # Generate training batch
        batch = generate(batch_size=batch_size, seq_len=seq_len, seed=None)
        inputs = batch.inputs.to(device)
        targets = batch.targets.to(device)

        # Forward
        logits = model(inputs)  # (batch, seq_len, vocab_size)

        # Compute loss
        if is_classification:
            if task_name == "needle":
                # Needle: target is a position index (0..seq_len-1), not a token ID
                # Use all logits projected down to seq_len classes
                # We use a simple approach: take the mean of all position logits
                # and classify which position the needle is at
                last_logits = logits[:, -1, :seq_len]  # (batch, seq_len)
                loss = F.cross_entropy(last_logits, targets)
            else:
                # First-last: target is a token ID (within vocab)
                last_logits = logits[:, -1, :]  # (batch, vocab_size)
                loss = F.cross_entropy(last_logits, targets)
        else:
            # Sequence prediction: flatten and compute cross-entropy
            # Only compute loss on non-zero target positions
            mask = targets != 0
            if mask.any():
                loss = F.cross_entropy(
                    logits[mask],  # (N, vocab_size)
                    targets[mask],  # (N,)
                )
            else:
                loss = torch.tensor(0.0, device=device)

        # Backward
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        # Evaluate periodically
        if step % eval_every == 0 or step == train_steps:
            acc = evaluate(model, task_name, seq_len, eval_batches, batch_size, device)
            loss_val = loss.item()
            loss_curve.append(loss_val)
            accuracy_curve.append(acc)
            best_acc = max(best_acc, acc)

            if not quiet:
                elapsed = time.time() - t0
                print(f"    step {step:>5}/{train_steps}  loss={loss_val:.4f}  "
                      f"acc={acc:.4f}  best={best_acc:.4f}  [{elapsed:.0f}s]")

    elapsed = time.time() - t0

    return TrainResult(
        pe_type=f"{pe_type}({kw})" if kw else pe_type,
        task_name=task_name,
        seq_len=seq_len,
        final_accuracy=accuracy_curve[-1] if accuracy_curve else 0.0,
        final_loss=loss_curve[-1] if loss_curve else 0.0,
        best_accuracy=best_acc,
        train_steps=train_steps,
        train_time_secs=elapsed,
        loss_curve=loss_curve,
        accuracy_curve=accuracy_curve,
        pe_kwargs=kw,
    )


# ──── Evaluation ────────────────────────────────────────────────────────────

@torch.no_grad()
def evaluate(
    model: nn.Module,
    task_name: str,
    seq_len: int,
    n_batches: int = 16,
    batch_size: int = 32,
    device: Optional[torch.device] = None,
) -> float:
    """Evaluate accuracy on fresh generated data.

    Args:
        model: Trained model.
        task_name: Task to evaluate on.
        seq_len: Sequence length.
        n_batches: Number of evaluation batches.
        batch_size: Batch size.
        device: Compute device.

    Returns:
        Accuracy (0.0 to 1.0).
    """
    if device is None:
        device = get_device()

    model.eval()
    generate = TASK_GENERATORS[task_name]
    is_classification = task_name in CLASSIFICATION_TASKS

    correct = 0
    total = 0

    for i in range(n_batches):
        batch = generate(batch_size=batch_size, seq_len=seq_len, seed=10000 + i)
        inputs = batch.inputs.to(device)
        targets = batch.targets.to(device)

        logits = model(inputs)

        if is_classification:
            if task_name == "needle":
                preds = logits[:, -1, :seq_len].argmax(dim=-1)
            else:
                preds = logits[:, -1, :].argmax(dim=-1)
            correct += (preds == targets).sum().item()
            total += targets.shape[0]
        else:
            # Sequence: check accuracy on non-zero target positions only
            mask = targets != 0
            if mask.any():
                preds = logits.argmax(dim=-1)  # (batch, seq_len)
                correct += (preds[mask] == targets[mask]).sum().item()
                total += mask.sum().item()

    return correct / total if total > 0 else 0.0
