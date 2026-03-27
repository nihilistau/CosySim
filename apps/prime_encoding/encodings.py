"""
Positional Encoding Implementations
=====================================

Four encoding schemes for direct comparison:
1. SinusoidalPE  — Standard (Vaswani et al., 2017) — BASELINE
2. PrimePE       — Prime-harmonic frequencies
3. ZetaPE        — Riemann zeta zero frequencies
4. RoPEStandard  — Rotary Position Embedding (geometric) — BASELINE
5. RoPEPrime     — Rotary Position Embedding with prime frequencies
6. RoPEZeta      — Rotary Position Embedding with zeta zero frequencies

All encodings produce (seq_len, d_model) tensors and implement the same
interface for drop-in comparison.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Six encoding schemes: 2 baselines + 4 experimental
"""
from __future__ import annotations

import math
from typing import List, Optional

import torch
import torch.nn as nn

from .primes import (
    geometric_frequencies,
    hybrid_frequencies,
    prime_frequencies,
    zeta_frequencies,
)


# ──── Base Class ─────────────────────────────────────────────────────────────

class PositionalEncoding(nn.Module):
    """Abstract base for all positional encoding schemes.

    All subclasses produce a (seq_len, d_model) tensor of position
    encodings that can be added to token embeddings.
    """

    def __init__(self, d_model: int, max_len: int = 8192) -> None:
        super().__init__()
        self.d_model = d_model
        self.max_len = max_len
        self.name = "base"

    def forward(self, seq_len: int) -> torch.Tensor:
        """Generate positional encoding for positions 0..seq_len-1.

        Args:
            seq_len: Number of positions to encode.

        Returns:
            Tensor of shape (seq_len, d_model).
        """
        raise NotImplementedError

    def encode_position(self, pos: int) -> torch.Tensor:
        """Encode a single position.

        Args:
            pos: Position index.

        Returns:
            Tensor of shape (d_model,).
        """
        return self.forward(pos + 1)[pos]

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(d={self.d_model}, max_len={self.max_len}, name={self.name})"


# ──── Sinusoidal PE (Vaswani Baseline) ───────────────────────────────────────

class SinusoidalPE(PositionalEncoding):
    """Standard sinusoidal positional encoding from 'Attention Is All You Need'.

    PE(pos, 2i)   = sin(pos / 10000^(2i/d))
    PE(pos, 2i+1) = cos(pos / 10000^(2i/d))

    Frequencies form a geometric progression from 1 to 1/10000.
    This is the baseline that all other schemes are compared against.
    """

    def __init__(self, d_model: int, max_len: int = 8192, base: float = 10000.0) -> None:
        super().__init__(d_model, max_len)
        self.name = "sinusoidal"
        self.base = base

        # Precompute the encoding matrix
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        # Geometric frequency progression
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float)
            * -(math.log(base) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe)

    def forward(self, seq_len: int) -> torch.Tensor:
        return self.pe[:seq_len]


# ──── Prime-Harmonic PE ──────────────────────────────────────────────────────

class PrimePE(PositionalEncoding):
    """Prime-harmonic positional encoding.

    PE(pos, 2i)   = sin(pos * freq_i)
    PE(pos, 2i+1) = cos(pos * freq_i)

    Where freq_i = 1 / prime(i)^alpha.

    The key difference from standard PE: prime frequencies are coprime,
    so the encoding never aliases. The "beat period" (primorial) grows
    super-exponentially: for 10 frequency pairs, it's 6.5 billion.

    Args:
        d_model: Embedding dimension.
        max_len: Maximum sequence length to precompute.
        alpha: Frequency scaling exponent. Controls frequency spread.
               alpha=1.0 gives raw prime reciprocals (wide spread).
               alpha=0.5 gives sqrt-prime reciprocals (narrower spread).
    """

    def __init__(self, d_model: int, max_len: int = 8192, alpha: float = 1.0) -> None:
        super().__init__(d_model, max_len)
        self.name = f"prime(a={alpha})"
        self.alpha = alpha

        freqs = prime_frequencies(d_model, alpha=alpha)
        freq_tensor = torch.tensor(freqs, dtype=torch.float)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        pe[:, 0::2] = torch.sin(position * freq_tensor)
        pe[:, 1::2] = torch.cos(position * freq_tensor)
        self.register_buffer("pe", pe)

    def forward(self, seq_len: int) -> torch.Tensor:
        return self.pe[:seq_len]


# ──── Zeta-Zero PE ───────────────────────────────────────────────────────────

class ZetaPE(PositionalEncoding):
    """Riemann zeta zero positional encoding.

    PE(pos, 2i)   = sin(pos * freq_i)
    PE(pos, 2i+1) = cos(pos * freq_i)

    Where freq_i = 1 / t_i, and t_i is the imaginary part of the i-th
    non-trivial zero of the Riemann zeta function.

    The zeta zeros are quasi-random but structured — they encode the
    distribution of primes. Using them as frequencies guarantees:
    - No two frequency bands produce the same pattern
    - Coverage is optimal (in an information-theoretic sense)
    - Spacing is irregular (preventing systematic aliasing)
    """

    def __init__(self, d_model: int, max_len: int = 8192, normalize: bool = True) -> None:
        super().__init__(d_model, max_len)
        self.name = "zeta"

        freqs = zeta_frequencies(d_model, normalize=normalize)
        freq_tensor = torch.tensor(freqs, dtype=torch.float)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        pe[:, 0::2] = torch.sin(position * freq_tensor)
        pe[:, 1::2] = torch.cos(position * freq_tensor)
        self.register_buffer("pe", pe)

    def forward(self, seq_len: int) -> torch.Tensor:
        return self.pe[:seq_len]


# ──── Hybrid PE ──────────────────────────────────────────────────────────────

class HybridPE(PositionalEncoding):
    """Hybrid prime + zeta zero positional encoding.

    Uses zeta-zero frequencies for low-frequency bands (long-range structure)
    and prime frequencies for high-frequency bands (local detail).

    This mirrors how music works: the deep harmonic structure (chord progressions)
    follows zeta-like patterns, while the rhythmic detail (beats, subdivisions)
    follows prime patterns.
    """

    def __init__(self, d_model: int, max_len: int = 8192, prime_ratio: float = 0.5) -> None:
        super().__init__(d_model, max_len)
        self.name = f"hybrid(pr={prime_ratio})"

        freqs = hybrid_frequencies(d_model, prime_ratio=prime_ratio)
        freq_tensor = torch.tensor(freqs, dtype=torch.float)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        pe[:, 0::2] = torch.sin(position * freq_tensor)
        pe[:, 1::2] = torch.cos(position * freq_tensor)
        self.register_buffer("pe", pe)

    def forward(self, seq_len: int) -> torch.Tensor:
        return self.pe[:seq_len]


# ──── RoPE Variants ──────────────────────────────────────────────────────────
# Rotary Position Embeddings operate in complex space. Instead of adding
# a position vector, they rotate the query/key vectors. This naturally
# encodes relative position in the attention score.
#
# The frequency selection is the ONLY difference between RoPE variants.

class RoPE(nn.Module):
    """Rotary Position Embedding base with configurable frequency basis.

    RoPE encodes position as complex rotations:
        f(x, pos) = x * e^(i * pos * theta)

    Different frequency bases (geometric, prime, zeta) produce different
    "rotation speeds" at different dimensions. The key insight:
    - Geometric: uniform log-spacing (standard RoPE)
    - Prime: coprime spacing (no aliasing, longer uniqueness)
    - Zeta: quasi-random spacing (optimal coverage)

    Args:
        d_model: Embedding dimension (must be even).
        max_len: Maximum sequence length.
        freq_type: One of "geometric", "prime", "zeta", "hybrid".
        base: Base for geometric frequencies (default 10000).
        alpha: Exponent for prime frequencies (default 1.0).
    """

    def __init__(
        self,
        d_model: int,
        max_len: int = 8192,
        freq_type: str = "geometric",
        base: float = 10000.0,
        alpha: float = 1.0,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.max_len = max_len
        self.freq_type = freq_type

        # Generate frequency basis based on type
        n_freqs = d_model // 2
        if freq_type == "geometric":
            freqs = geometric_frequencies(d_model, base=base)
        elif freq_type == "prime":
            freqs = prime_frequencies(d_model, alpha=alpha)
        elif freq_type == "zeta":
            freqs = zeta_frequencies(d_model, normalize=True)
        elif freq_type == "hybrid":
            freqs = hybrid_frequencies(d_model, prime_ratio=0.5)
        else:
            raise ValueError(f"Unknown freq_type: {freq_type}")

        # theta_i = freq_i (already computed as 1/base^... or 1/prime^...)
        theta = torch.tensor(freqs, dtype=torch.float)
        self.register_buffer("theta", theta)

        # Precompute cos/sin tables for all positions
        positions = torch.arange(0, max_len, dtype=torch.float)
        # (max_len, n_freqs) — angle for each position and frequency
        angles = torch.outer(positions, theta)
        self.register_buffer("cos_cached", angles.cos())
        self.register_buffer("sin_cached", angles.sin())

    def forward(self, x: torch.Tensor, offset: int = 0) -> torch.Tensor:
        """Apply rotary position encoding to input tensor.

        Args:
            x: Input tensor of shape (..., seq_len, d_model).
            offset: Position offset (for KV cache continuation).

        Returns:
            Rotated tensor of same shape.
        """
        seq_len = x.shape[-2]
        # Split into pairs for complex rotation
        x1 = x[..., 0::2]  # even dims
        x2 = x[..., 1::2]  # odd dims

        cos = self.cos_cached[offset: offset + seq_len]
        sin = self.sin_cached[offset: offset + seq_len]

        # Broadcast cos/sin to match x shape
        # cos, sin are (seq_len, n_freqs)
        # x1, x2 are (..., seq_len, n_freqs)
        out1 = x1 * cos - x2 * sin
        out2 = x1 * sin + x2 * cos

        # Interleave back
        out = torch.stack([out1, out2], dim=-1).flatten(-2)
        return out

    def __repr__(self) -> str:
        return f"RoPE(d={self.d_model}, type={self.freq_type})"


# ──── Factory ────────────────────────────────────────────────────────────────

ENCODING_REGISTRY = {
    "sinusoidal": SinusoidalPE,
    "prime": PrimePE,
    "zeta": ZetaPE,
    "hybrid": HybridPE,
}

ROPE_TYPES = ["geometric", "prime", "zeta", "hybrid"]


def create_encoding(
    name: str,
    d_model: int = 128,
    max_len: int = 8192,
    **kwargs,
) -> PositionalEncoding:
    """Create a positional encoding by name.

    Args:
        name: One of "sinusoidal", "prime", "zeta", "hybrid".
        d_model: Embedding dimension.
        max_len: Maximum sequence length.
        **kwargs: Additional arguments passed to the constructor.

    Returns:
        PositionalEncoding instance.
    """
    if name not in ENCODING_REGISTRY:
        raise ValueError(f"Unknown encoding: {name}. Available: {list(ENCODING_REGISTRY.keys())}")
    return ENCODING_REGISTRY[name](d_model=d_model, max_len=max_len, **kwargs)


def create_rope(
    freq_type: str = "geometric",
    d_model: int = 128,
    max_len: int = 8192,
    **kwargs,
) -> RoPE:
    """Create a RoPE variant by frequency type.

    Args:
        freq_type: One of "geometric", "prime", "zeta", "hybrid".
        d_model: Embedding dimension.
        max_len: Maximum sequence length.

    Returns:
        RoPE instance.
    """
    return RoPE(d_model=d_model, max_len=max_len, freq_type=freq_type, **kwargs)
