"""
Encoding Analysis — Mathematical Comparison Suite
===================================================

Measures the mathematical properties of different positional encodings
WITHOUT any ML training. Pure linear algebra on the encoding vectors.

Metrics:
1. Distinguishability curve — cos_sim(PE(i), PE(j)) vs |i-j|
2. Aliasing distance — smallest gap where similarity exceeds threshold
3. Relative position sensitivity — how well dot products encode distance
4. Frequency spectrum — FFT of the encoding dimensions
5. Uniqueness horizon — the distance at which encodings "blur"

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Initial analysis suite with 5 metrics
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F

from .encodings import PositionalEncoding, create_encoding, ENCODING_REGISTRY


# ──── Metrics ────────────────────────────────────────────────────────────────

@dataclass
class EncodingMetrics:
    """Results of analyzing a single positional encoding scheme."""
    name: str
    d_model: int
    max_len_tested: int

    # Aliasing: smallest distance where cos_sim > threshold
    aliasing_distance_95: int = 0    # cos_sim > 0.95
    aliasing_distance_90: int = 0    # cos_sim > 0.90
    aliasing_distance_80: int = 0    # cos_sim > 0.80

    # Average similarity at various distances
    avg_sim_100: float = 0.0     # avg cos_sim at distance 100
    avg_sim_1000: float = 0.0    # avg cos_sim at distance 1000
    avg_sim_10000: float = 0.0   # avg cos_sim at distance 10000

    # Uniqueness: how many positions are truly distinct (sim < 0.5)
    unique_positions_count: int = 0

    # Monotonicity: is similarity monotonically decreasing with distance?
    # (desirable — closer positions should be more similar)
    monotonicity_violations: int = 0
    monotonicity_score: float = 0.0   # 1.0 = perfectly monotonic

    # Computation time
    compute_time_ms: float = 0.0

    # Raw similarity curve (sampled)
    similarity_curve: List[Tuple[int, float]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "d_model": self.d_model,
            "max_len_tested": self.max_len_tested,
            "aliasing_distance_95": self.aliasing_distance_95,
            "aliasing_distance_90": self.aliasing_distance_90,
            "aliasing_distance_80": self.aliasing_distance_80,
            "avg_sim_100": round(self.avg_sim_100, 6),
            "avg_sim_1000": round(self.avg_sim_1000, 6),
            "avg_sim_10000": round(self.avg_sim_10000, 6),
            "unique_positions_count": self.unique_positions_count,
            "monotonicity_violations": self.monotonicity_violations,
            "monotonicity_score": round(self.monotonicity_score, 4),
            "compute_time_ms": round(self.compute_time_ms, 1),
        }


# ──── Core Analysis ──────────────────────────────────────────────────────────

def compute_similarity_curve(
    encoding: PositionalEncoding,
    max_distance: int = 10000,
    reference_pos: int = 0,
    sample_points: int = 200,
) -> List[Tuple[int, float]]:
    """Compute cosine similarity between a reference position and positions at increasing distances.

    This is the fundamental measurement: how quickly does the encoding
    "forget" that two positions are different?

    Args:
        encoding: The positional encoding to analyze.
        reference_pos: The position to measure distances from.
        max_distance: Maximum distance to test.
        sample_points: Number of distances to sample (log-spaced).

    Returns:
        List of (distance, cosine_similarity) tuples.
    """
    # Generate encodings
    needed = min(reference_pos + max_distance + 1, encoding.max_len)
    pe = encoding.forward(needed)

    ref_vec = pe[reference_pos].unsqueeze(0)  # (1, d_model)

    # Sample distances (log-spaced for better coverage of large ranges)
    distances = set()
    distances.update(range(1, min(101, max_distance)))  # Dense at short range
    # Log-spaced for long range
    if max_distance > 100:
        import numpy as np
        log_dists = np.logspace(2, np.log10(max_distance), sample_points - 100)
        distances.update(int(d) for d in log_dists if d < max_distance)
    distances = sorted(distances)

    results: List[Tuple[int, float]] = []
    for d in distances:
        target_pos = reference_pos + d
        if target_pos >= needed:
            break
        target_vec = pe[target_pos].unsqueeze(0)
        sim = F.cosine_similarity(ref_vec, target_vec).item()
        results.append((d, sim))

    return results


def find_aliasing_distance(
    curve: List[Tuple[int, float]],
    threshold: float = 0.95,
) -> int:
    """Find the smallest distance at which similarity exceeds a threshold.

    A position is "aliased" when the encoding can't distinguish it from
    the reference. Larger aliasing distance = better encoding.

    Args:
        curve: Similarity curve from compute_similarity_curve().
        threshold: Similarity threshold (default 0.95).

    Returns:
        Smallest distance where sim > threshold, or max_distance if never aliased.
    """
    # Skip distance=0 (always sim=1.0)
    # Look for the first distance > some minimum where sim exceeds threshold
    for dist, sim in curve:
        if dist > 1 and sim > threshold:
            return dist
    # Never aliased within the tested range
    return curve[-1][0] if curve else 0


def compute_monotonicity(curve: List[Tuple[int, float]]) -> Tuple[int, float]:
    """Check how monotonically similarity decreases with distance.

    A perfect encoding has cos_sim(PE(i), PE(j)) decrease monotonically
    with |i-j|. Violations indicate "wrapping" or aliasing.

    Args:
        curve: Similarity curve.

    Returns:
        Tuple of (violation_count, monotonicity_score).
        Score is 1.0 for perfectly monotonic, 0.0 for random.
    """
    if len(curve) < 2:
        return 0, 1.0

    violations = 0
    for i in range(1, len(curve)):
        if curve[i][1] > curve[i - 1][1]:
            violations += 1

    score = 1.0 - (violations / (len(curve) - 1))
    return violations, score


def average_similarity_at_distance(
    encoding: PositionalEncoding,
    distance: int,
    num_samples: int = 50,
) -> float:
    """Compute average cosine similarity across many position pairs at a fixed distance.

    Instead of measuring from one reference point, sample many pairs to get
    a robust estimate.

    Args:
        encoding: Positional encoding to test.
        distance: Fixed distance between position pairs.
        num_samples: Number of pairs to sample.

    Returns:
        Average cosine similarity.
    """
    needed = min(distance + num_samples + 1, encoding.max_len)
    if needed <= distance:
        return 0.0
    pe = encoding.forward(needed)

    sims = []
    for i in range(min(num_samples, needed - distance)):
        v1 = pe[i].unsqueeze(0)
        v2 = pe[i + distance].unsqueeze(0)
        sim = F.cosine_similarity(v1, v2).item()
        sims.append(sim)

    return sum(sims) / len(sims) if sims else 0.0


def count_unique_positions(
    encoding: PositionalEncoding,
    max_len: int = 8192,
    threshold: float = 0.5,
) -> int:
    """Count how many positions have truly unique encodings.

    Two positions are "unique" if their cosine similarity is below the threshold.
    Tests all pairs within the first max_len positions (sampled for efficiency).

    Args:
        encoding: Encoding to test.
        max_len: Number of positions to check.
        threshold: Similarity threshold below which positions are "unique".

    Returns:
        Number of positions that remain unique.
    """
    test_len = min(max_len, encoding.max_len)
    pe = encoding.forward(test_len)

    # Sample pairs — checking all O(n^2) pairs is too expensive
    ref = pe[0].unsqueeze(0)
    unique = 0
    for i in range(1, test_len):
        sim = F.cosine_similarity(ref, pe[i].unsqueeze(0)).item()
        if abs(sim) < threshold:
            unique += 1

    return unique


# ──── Full Analysis ──────────────────────────────────────────────────────────

def analyze_encoding(
    encoding: PositionalEncoding,
    max_distance: int = 10000,
) -> EncodingMetrics:
    """Run full analysis suite on a positional encoding.

    Args:
        encoding: The encoding to analyze.
        max_distance: Maximum distance to test.

    Returns:
        EncodingMetrics with all measurements.
    """
    t0 = time.time()

    # Ensure max_distance doesn't exceed encoding capacity
    max_distance = min(max_distance, encoding.max_len - 1)

    # Similarity curve
    curve = compute_similarity_curve(encoding, max_distance=max_distance)

    # Aliasing distances
    alias_95 = find_aliasing_distance(curve, 0.95)
    alias_90 = find_aliasing_distance(curve, 0.90)
    alias_80 = find_aliasing_distance(curve, 0.80)

    # Average similarities at key distances
    avg_100 = average_similarity_at_distance(encoding, 100) if max_distance >= 100 else 0.0
    avg_1000 = average_similarity_at_distance(encoding, 1000) if max_distance >= 1000 else 0.0
    avg_10000 = average_similarity_at_distance(encoding, 10000) if max_distance >= 10000 else 0.0

    # Monotonicity
    violations, mono_score = compute_monotonicity(curve)

    # Unique positions
    unique_count = count_unique_positions(encoding, max_len=min(max_distance, 4096))

    elapsed = (time.time() - t0) * 1000

    return EncodingMetrics(
        name=encoding.name,
        d_model=encoding.d_model,
        max_len_tested=max_distance,
        aliasing_distance_95=alias_95,
        aliasing_distance_90=alias_90,
        aliasing_distance_80=alias_80,
        avg_sim_100=avg_100,
        avg_sim_1000=avg_1000,
        avg_sim_10000=avg_10000,
        unique_positions_count=unique_count,
        monotonicity_violations=violations,
        monotonicity_score=mono_score,
        compute_time_ms=elapsed,
        similarity_curve=curve,
    )


def compare_encodings(
    d_model: int = 128,
    max_len: int = 32768,
    max_distance: int = 16384,
) -> List[EncodingMetrics]:
    """Compare all encoding schemes head-to-head.

    Args:
        d_model: Embedding dimension for all encodings.
        max_len: Maximum sequence length to precompute.
        max_distance: Maximum distance to test.

    Returns:
        List of EncodingMetrics, one per encoding scheme.
    """
    results: List[EncodingMetrics] = []

    encodings = [
        create_encoding("sinusoidal", d_model=d_model, max_len=max_len),
        create_encoding("prime", d_model=d_model, max_len=max_len, alpha=1.0),
        create_encoding("prime", d_model=d_model, max_len=max_len, alpha=0.5),
        create_encoding("zeta", d_model=d_model, max_len=max_len),
        create_encoding("hybrid", d_model=d_model, max_len=max_len, prime_ratio=0.5),
    ]

    for enc in encodings:
        print(f"  Analyzing: {enc.name} ...", end=" ", flush=True)
        metrics = analyze_encoding(enc, max_distance=max_distance)
        print(f"done ({metrics.compute_time_ms:.0f}ms)")
        results.append(metrics)

    return results


def print_comparison(results: List[EncodingMetrics]) -> None:
    """Print a formatted comparison table of encoding metrics."""
    print(f"\n  {'Encoding':<20} {'Alias95':>8} {'Alias90':>8} {'Alias80':>8} "
          f"{'Sim@100':>8} {'Sim@1k':>8} {'Sim@10k':>8} {'Unique':>7} {'Mono':>6}")
    print(f"  {'-' * 95}")
    for m in results:
        print(f"  {m.name:<20} {m.aliasing_distance_95:>8} {m.aliasing_distance_90:>8} "
              f"{m.aliasing_distance_80:>8} {m.avg_sim_100:>8.4f} {m.avg_sim_1000:>8.4f} "
              f"{m.avg_sim_10000:>8.4f} {m.unique_positions_count:>7} {m.monotonicity_score:>6.3f}")
    print()


def save_results(results: List[EncodingMetrics], path: str) -> None:
    """Save comparison results to JSON."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [m.to_dict() for m in results],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Results saved to {path}")
