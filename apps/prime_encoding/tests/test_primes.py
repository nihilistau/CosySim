"""
Tests for prime number utilities and zeta zero tables.

Version: v0.1.0 [2026-03-27]
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from prime_encoding.primes import (
    first_n_primes,
    geometric_frequencies,
    hybrid_frequencies,
    prime_frequencies,
    primorial,
    sieve_of_eratosthenes,
    zeta_frequencies,
    zeta_zero,
    zeta_zero_gaps,
    zeta_zeros,
    ZETA_ZEROS_IMAGINARY,
)


class TestSieve:
    def test_small(self):
        assert sieve_of_eratosthenes(10) == [2, 3, 5, 7]

    def test_empty(self):
        assert sieve_of_eratosthenes(1) == []

    def test_two(self):
        assert sieve_of_eratosthenes(2) == [2]

    def test_100(self):
        primes = sieve_of_eratosthenes(100)
        assert len(primes) == 25  # there are 25 primes <= 100
        assert primes[0] == 2
        assert primes[-1] == 97


class TestFirstNPrimes:
    def test_first_5(self):
        assert first_n_primes(5) == [2, 3, 5, 7, 11]

    def test_first_10(self):
        p = first_n_primes(10)
        assert len(p) == 10
        assert p == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]

    def test_zero(self):
        assert first_n_primes(0) == []

    def test_large(self):
        p = first_n_primes(100)
        assert len(p) == 100
        assert p[-1] == 541  # the 100th prime


class TestPrimorial:
    def test_small(self):
        assert primorial(1) == 2
        assert primorial(2) == 6
        assert primorial(3) == 30
        assert primorial(4) == 210
        assert primorial(5) == 2310

    def test_ten(self):
        # 2*3*5*7*11*13*17*19*23*29 = 6,469,693,230
        assert primorial(10) == 6_469_693_230

    def test_growth_rate(self):
        """Primorial grows faster than exponential."""
        p5 = primorial(5)
        p10 = primorial(10)
        p15 = primorial(15)
        assert p10 / p5 > 1000      # more than 1000x growth in 5 primes
        assert p15 / p10 > 10000    # even faster growth


class TestZetaZeros:
    def test_first_zero(self):
        assert abs(zeta_zero(1) - 14.1347) < 0.001

    def test_count(self):
        assert len(ZETA_ZEROS_IMAGINARY) == 50

    def test_ascending(self):
        """Zeta zeros must be in ascending order."""
        for i in range(len(ZETA_ZEROS_IMAGINARY) - 1):
            assert ZETA_ZEROS_IMAGINARY[i] < ZETA_ZEROS_IMAGINARY[i + 1]

    def test_gaps_irregular(self):
        """Gaps between zeros are irregular (no simple pattern)."""
        gaps = zeta_zero_gaps(20)
        # Gaps should vary — not all the same
        assert max(gaps) / min(gaps) > 2.0

    def test_zeta_zeros_list(self):
        z = zeta_zeros(10)
        assert len(z) == 10
        assert z[0] == ZETA_ZEROS_IMAGINARY[0]

    def test_out_of_range(self):
        with pytest.raises(IndexError):
            zeta_zero(51)


class TestFrequencies:
    def test_geometric_count(self):
        f = geometric_frequencies(128)
        assert len(f) == 64

    def test_geometric_descending(self):
        f = geometric_frequencies(128)
        # Frequencies should be descending (high freq first)
        for i in range(len(f) - 1):
            assert f[i] > f[i + 1]

    def test_prime_count(self):
        f = prime_frequencies(128)
        assert len(f) == 64

    def test_prime_all_different(self):
        """Prime frequencies must all be unique (key property)."""
        f = prime_frequencies(128)
        assert len(set(f)) == len(f)

    def test_zeta_count(self):
        f = zeta_frequencies(64)
        assert len(f) == 32

    def test_zeta_normalized(self):
        f = zeta_frequencies(64, normalize=True)
        assert max(f) <= 1.0 + 1e-9

    def test_hybrid_count(self):
        f = hybrid_frequencies(128)
        assert len(f) == 64

    def test_alpha_effect(self):
        """Higher alpha should spread frequencies wider."""
        f1 = prime_frequencies(128, alpha=0.5)
        f2 = prime_frequencies(128, alpha=1.0)
        # Higher alpha = smaller frequencies (wider wavelengths)
        assert f2[-1] < f1[-1]
