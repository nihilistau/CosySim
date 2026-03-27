"""
Prime Number Utilities
=======================

Efficient prime generation and Riemann zeta zero tables for use
as frequency bases in positional encodings.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Change Log:
    v0.1.0 [2026-03-27] — Initial implementation: sieve, zeta zeros, primorial
"""
from __future__ import annotations

import math
from typing import List


# ──── Prime Generation ───────────────────────────────────────────────────────

def sieve_of_eratosthenes(limit: int) -> List[int]:
    """Generate all primes up to `limit` using the Sieve of Eratosthenes.

    Args:
        limit: Upper bound (inclusive).

    Returns:
        Sorted list of primes <= limit.
    """
    if limit < 2:
        return []
    is_prime = [True] * (limit + 1)
    is_prime[0] = is_prime[1] = False
    for i in range(2, int(math.isqrt(limit)) + 1):
        if is_prime[i]:
            for j in range(i * i, limit + 1, i):
                is_prime[j] = False
    return [i for i, v in enumerate(is_prime) if v]


def first_n_primes(n: int) -> List[int]:
    """Return the first `n` prime numbers.

    Uses a generous upper bound estimate (p_n ~ n * ln(n) + n * ln(ln(n)))
    and sieves, then truncates.

    Args:
        n: Number of primes to generate.

    Returns:
        List of the first n primes.
    """
    if n <= 0:
        return []
    if n <= 6:
        return [2, 3, 5, 7, 11, 13][:n]
    # Upper bound: p_n < n * (ln(n) + ln(ln(n))) for n >= 6
    ln_n = math.log(n)
    upper = int(n * (ln_n + math.log(ln_n))) + 100
    primes = sieve_of_eratosthenes(upper)
    # If we didn't generate enough (rare for large n), increase bound
    while len(primes) < n:
        upper = int(upper * 1.5)
        primes = sieve_of_eratosthenes(upper)
    return primes[:n]


def primorial(n: int) -> int:
    """Compute the primorial of the first `n` primes (product of first n primes).

    This is the "beat period" — the distance at which prime-harmonic
    encodings first repeat. Grows super-exponentially.

    Args:
        n: Number of primes to multiply.

    Returns:
        Product of the first n primes.

    Examples:
        primorial(5)  = 2 * 3 * 5 * 7 * 11 = 2310
        primorial(10) = 6,469,693,230
        primorial(15) = 614,889,782,588,491,410
    """
    result = 1
    for p in first_n_primes(n):
        result *= p
    return result


# ──── Riemann Zeta Zeros ────────────────────────────────────────────────────
# The imaginary parts of the first non-trivial zeros of the Riemann zeta
# function: zeta(1/2 + i*t) = 0. These are known to high precision.
#
# Source: Andrew Odlyzko's tables (verified to billions of zeros).
# These values encode the "frequencies" at which the prime distribution
# has maximal harmonic energy — nature's optimal quasi-random basis.

ZETA_ZEROS_IMAGINARY: List[float] = [
    14.134725141734693,
    21.022039638771555,
    25.010857580145688,
    30.424876125859513,
    32.935061587739189,
    37.586178158825671,
    40.918719012147495,
    43.327073280914999,
    48.005150881167159,
    49.773832477672302,
    52.970321477714460,
    56.446247697063394,
    59.347044002602353,
    60.831778524609809,
    65.112544048081606,
    67.079810529494173,
    69.546401711173979,
    72.067157674481907,
    75.704690699083933,
    77.144840068874805,
    79.337375020249367,
    82.910380854086030,
    84.735492980517050,
    87.425274613125196,
    88.809111207634465,
    92.491899270558484,
    94.651344040519838,
    95.870634228245309,
    98.831194218193692,
    101.317851005731391,
    103.725538040478334,
    105.446623052326165,
    107.168611184276408,
    111.029535543088076,
    111.874659176711869,
    114.320220915452712,
    116.226680320857573,
    118.790782865976215,
    121.370125002017403,
    122.946829293536752,
    124.256818554345484,
    127.516683879633760,
    129.578704199956808,
    131.087688530934611,
    133.497737203167193,
    134.756509752150560,
    138.116042054667609,
    139.736208952121417,
    141.123707404021858,
    143.111845807505020,
]
"""First 50 imaginary parts of the non-trivial Riemann zeta zeros.

These values are the "natural frequencies" of prime number distribution.
Properties that make them ideal for encoding:
1. Quasi-random spacing (no simple pattern, no aliasing)
2. Structured (encode prime distribution information)
3. Irregularly spaced (gaps range from ~1.2 to ~3.5)
4. Proven to lie on Re(s)=1/2 for these values (RH verified to 10^13)
"""


def zeta_zero(n: int) -> float:
    """Return the imaginary part of the n-th Riemann zeta zero (1-indexed).

    Args:
        n: Zero index (1 = first zero at ~14.13).

    Returns:
        Imaginary part t_n where zeta(1/2 + i*t_n) = 0.

    Raises:
        IndexError: If n > 50 (we only have 50 tabulated).
    """
    if n < 1 or n > len(ZETA_ZEROS_IMAGINARY):
        raise IndexError(f"Only {len(ZETA_ZEROS_IMAGINARY)} zeta zeros tabulated, got n={n}")
    return ZETA_ZEROS_IMAGINARY[n - 1]


def zeta_zeros(count: int) -> List[float]:
    """Return the first `count` Riemann zeta zero imaginary parts.

    Args:
        count: Number of zeros to return.

    Returns:
        List of imaginary parts [t_1, t_2, ..., t_count].
    """
    return ZETA_ZEROS_IMAGINARY[:count]


def zeta_zero_gaps(count: int = 50) -> List[float]:
    """Return the gaps between consecutive zeta zeros.

    The irregular spacing of these gaps is what prevents aliasing
    when used as frequency bases. Compare with the regular spacing
    of geometric progressions.

    Args:
        count: Number of gaps to return (max 49).

    Returns:
        List of gaps [t_2 - t_1, t_3 - t_2, ...].
    """
    zeros = zeta_zeros(min(count + 1, len(ZETA_ZEROS_IMAGINARY)))
    return [zeros[i + 1] - zeros[i] for i in range(len(zeros) - 1)]


# ──── Frequency Basis Functions ─────────────────────────────────────────────

def prime_frequencies(d_model: int, alpha: float = 1.0) -> List[float]:
    """Generate prime-indexed frequency basis for positional encoding.

    Each frequency is 1 / prime(i)^alpha. The alpha parameter controls
    the spread of frequencies (analogous to the 10000 base in standard PE).

    Args:
        d_model: Model dimension (number of frequency pairs = d_model // 2).
        alpha: Scaling exponent. Higher = wider frequency spread.

    Returns:
        List of d_model // 2 frequencies.
    """
    n_freqs = d_model // 2
    primes = first_n_primes(n_freqs)
    return [1.0 / (p ** alpha) for p in primes]


def geometric_frequencies(d_model: int, base: float = 10000.0) -> List[float]:
    """Generate standard geometric frequency basis (Vaswani et al., 2017).

    This is the baseline for comparison.

    Args:
        d_model: Model dimension.
        base: Frequency base (default 10000, as in the original paper).

    Returns:
        List of d_model // 2 frequencies.
    """
    n_freqs = d_model // 2
    return [1.0 / (base ** (2 * i / d_model)) for i in range(n_freqs)]


def zeta_frequencies(d_model: int, normalize: bool = True) -> List[float]:
    """Generate zeta-zero-indexed frequency basis.

    Uses the imaginary parts of the Riemann zeta zeros as frequencies.
    Falls back to prime frequencies if more than 50 are needed.

    Args:
        d_model: Model dimension.
        normalize: If True, normalize so max frequency = 1.0.

    Returns:
        List of d_model // 2 frequencies.
    """
    n_freqs = d_model // 2
    zeros = ZETA_ZEROS_IMAGINARY[:n_freqs]

    # If we need more than 50 frequencies, extend with scaled primes
    if n_freqs > len(ZETA_ZEROS_IMAGINARY):
        extra_primes = first_n_primes(n_freqs - len(ZETA_ZEROS_IMAGINARY))
        # Scale extra primes to continue from where zeta zeros end
        last_zero = ZETA_ZEROS_IMAGINARY[-1]
        zeros = list(ZETA_ZEROS_IMAGINARY) + [last_zero + p for p in extra_primes]
        zeros = zeros[:n_freqs]

    freqs = [1.0 / z for z in zeros]

    if normalize and freqs:
        max_f = max(freqs)
        freqs = [f / max_f for f in freqs]

    return freqs


def hybrid_frequencies(d_model: int, prime_ratio: float = 0.5) -> List[float]:
    """Generate a hybrid frequency basis: mix of prime and zeta-zero frequencies.

    Low-frequency bands use zeta zeros (long-range structure),
    high-frequency bands use primes (local detail).

    Args:
        d_model: Model dimension.
        prime_ratio: Fraction of frequencies from prime basis (0.0 to 1.0).

    Returns:
        List of d_model // 2 frequencies.
    """
    n_freqs = d_model // 2
    n_prime = int(n_freqs * prime_ratio)
    n_zeta = n_freqs - n_prime

    pf = prime_frequencies(d_model=n_prime * 2, alpha=0.8)[:n_prime]
    zf = zeta_frequencies(d_model=n_zeta * 2, normalize=True)[:n_zeta]

    # Sort all frequencies descending (high to low, like standard PE)
    combined = sorted(pf + zf, reverse=True)
    return combined
