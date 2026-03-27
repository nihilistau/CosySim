"""
Tiny Transformer — Minimal transformer with swappable positional encoding.
==========================================================================

A 2-layer, 4-head transformer designed for synthetic benchmarks. The ONLY
variable between experiments is the positional encoding — architecture,
optimizer, data, and hyperparameters are identical.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Initial: encoder-decoder, additive PE, RoPE support
"""
from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .encodings import PositionalEncoding, RoPE, create_encoding, create_rope


# ──── Tiny Transformer ──────────────────────────────────────────────────────

class TinyTransformer(nn.Module):
    """Minimal transformer for PE benchmarking.

    Encoder-only architecture with a linear output head. Positional encoding
    is the ONLY variable — everything else is fixed.

    Args:
        vocab_size: Number of tokens in the vocabulary.
        d_model: Embedding dimension.
        n_heads: Number of attention heads.
        n_layers: Number of transformer layers.
        d_ff: Feed-forward hidden dimension.
        max_len: Maximum sequence length.
        dropout: Dropout rate.
        pe_type: Positional encoding type ("sinusoidal", "prime", "zeta", "hybrid").
        pe_kwargs: Extra args for the PE constructor (e.g. alpha for PrimePE).
    """

    def __init__(
        self,
        vocab_size: int = 64,
        d_model: int = 128,
        n_heads: int = 4,
        n_layers: int = 2,
        d_ff: int = 256,
        max_len: int = 2048,
        dropout: float = 0.1,
        pe_type: str = "sinusoidal",
        pe_kwargs: Optional[dict] = None,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.pe_type = pe_type

        # Token embedding
        self.embedding = nn.Embedding(vocab_size, d_model)

        # Positional encoding (the variable under test)
        kwargs = pe_kwargs or {}
        self.pe = create_encoding(pe_type, d_model=d_model, max_len=max_len, **kwargs)

        # Transformer layers (using PyTorch's built-in for reliability)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Output head
        self.output_head = nn.Linear(d_model, vocab_size)

        # Initialize weights
        self._init_weights()

    def _init_weights(self) -> None:
        """Xavier uniform initialization for all linear layers."""
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(
        self,
        src: torch.Tensor,
        src_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            src: Input token IDs, shape (batch, seq_len).
            src_mask: Optional attention mask.

        Returns:
            Logits, shape (batch, seq_len, vocab_size).
        """
        seq_len = src.shape[1]

        # Embed tokens
        x = self.embedding(src) * math.sqrt(self.d_model)

        # Add positional encoding
        pe = self.pe(seq_len)  # (seq_len, d_model)
        x = x + pe.unsqueeze(0)  # broadcast over batch

        # Transformer
        x = self.transformer(x, mask=src_mask)

        # Project to vocab
        return self.output_head(x)

    def count_parameters(self) -> int:
        """Return total trainable parameter count."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# ──── Factory ────────────────────────────────────────────────────────────────

def create_model(
    pe_type: str = "sinusoidal",
    vocab_size: int = 64,
    d_model: int = 128,
    max_len: int = 2048,
    **pe_kwargs,
) -> TinyTransformer:
    """Create a TinyTransformer with the specified PE type.

    All other hyperparameters are fixed to ensure fair comparison.

    Args:
        pe_type: One of "sinusoidal", "prime", "zeta", "hybrid".
        vocab_size: Vocabulary size.
        d_model: Embedding dimension.
        max_len: Maximum sequence length.
        **pe_kwargs: Extra PE arguments (e.g. alpha=0.5 for PrimePE).

    Returns:
        TinyTransformer instance.
    """
    return TinyTransformer(
        vocab_size=vocab_size,
        d_model=d_model,
        n_heads=4,
        n_layers=2,
        d_ff=256,
        max_len=max_len,
        dropout=0.1,
        pe_type=pe_type,
        pe_kwargs=pe_kwargs if pe_kwargs else None,
    )
