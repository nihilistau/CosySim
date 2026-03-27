# Prime-Harmonic Positional Encoding — Research Notes

> An exploration of whether prime numbers, Riemann zeta zeros, and number-theoretic
> structures can improve transformer positional encodings, particularly for long contexts.
>
> Status: Active research — v0.1.0 [2026-03-27]

---

## 1. The Hypothesis

Standard transformer positional encodings use frequencies in geometric progression
(sinusoidal PE) or learned rotations at evenly-spaced frequencies (RoPE). These
frequency choices are somewhat arbitrary — they work, but they weren't derived from
any optimality principle.

**Core claim:** Prime-indexed frequencies produce positional encodings where any two
positions remain maximally distinguishable for much longer distances, because primes
share no common factors. This directly addresses the "lost in the middle" problem
in long-context models.

**Secondary claim:** The imaginary parts of the Riemann zeta zeros provide a
quasi-random but structured frequency basis that avoids redundancy between attention
heads while maintaining complete coverage of all attention scales.

---

## 2. Mathematical Background

### 2.1 Standard Sinusoidal PE (Vaswani et al., 2017)

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

Frequencies form a **geometric progression** from 1 to 1/10000. For d_model=512,
there are 256 frequency bands. The wavelengths range from 2*pi to 2*pi*10000.

**Problem:** At positions far apart, the high-frequency components wrap around
(losing uniqueness), while low-frequency components barely change (losing
precision). The geometric spacing means many frequency bands cluster at similar
scales, wasting capacity.

### 2.2 RoPE (Su et al., 2021)

Rotary Position Embedding encodes position as a rotation in complex space:

```
f(x_m, m) = x_m * e^(i * m * theta_j)
theta_j = 10000^(-2j/d)
```

This is equivalent to multiplying by a complex number on the unit circle.
The relative position (m-n) determines the attention score modifier.
RoPE uses the SAME geometric frequency progression as sinusoidal PE.

**Key insight:** RoPE already lives in complex number space. The step from
geometric frequencies to prime/zeta frequencies is a direct substitution.

### 2.3 Why Primes?

Two sinusoids at frequencies f1 and f2 will "beat" (produce identical values)
at intervals of lcm(period1, period2). If the periods are coprime integers,
the beat period equals their product.

For prime frequencies p1, p2, p3, ..., pk:
- **Beat period = p1 * p2 * p3 * ... * pk**
- For the first 10 primes: 2*3*5*7*11*13*17*19*23*29 = 6,469,693,230
- For geometric progression: beats start recurring much sooner

This means prime-encoded positions remain **uniquely distinguishable** over
astronomically larger ranges.

### 2.4 Riemann Zeta Zeros

The non-trivial zeros of the Riemann zeta function lie at s = 1/2 + i*t_n.

First 20 imaginary parts (t_n):
```
14.1347, 21.0220, 25.0109, 30.4249, 32.9351,
37.5862, 40.9187, 43.3271, 48.0052, 49.7738,
52.9703, 56.4462, 59.3470, 60.8318, 65.1125,
67.0798, 69.5464, 72.0672, 75.7047, 77.1448
```

These values are:
1. **Quasi-random** — they don't repeat or follow a simple pattern
2. **Structured** — they encode information about prime distribution
3. **Irregularly spaced** — gaps vary (avoiding resonance/beating)
4. **Proven optimal** in a specific information-theoretic sense: they are the
   frequencies at which the "music of the primes" has maximal energy

**Insight:** Using zeta zeros as attention head frequencies means each head
"listens" at a different scale, with no two heads ever producing the same
pattern — guaranteed by the properties of the zeta function.

### 2.5 Strange Attractor Connection

Chaotic dynamical systems with strange attractors exhibit:
- **Sensitivity to initial conditions** (butterfly effect)
- **Self-similarity at different scales** (fractal structure)
- **Bounded but non-repeating trajectories**

Language has these same properties:
- Small word changes cascade into meaning changes
- Structure repeats at character/word/sentence/paragraph scales
- Conversations are bounded in topic but never exactly repeat

Attention patterns in trained transformers empirically show fractal-like
structure. Prime-harmonic encodings could provide this structure a priori
rather than hoping the model learns it.

---

## 3. What We're Building

### 3.1 Prime-Harmonic Positional Encoding (PrimePE)

Replace the geometric frequency progression with prime-indexed frequencies:

```python
# Standard: freq_i = 1 / 10000^(2i/d)    (geometric)
# PrimePE:  freq_i = 1 / prime(i)^alpha    (prime-indexed)
```

Where alpha controls the spread (analogous to the 10000 base in standard PE).

### 3.2 Zeta-Zero Attention Bias (ZetaBias)

Use the imaginary parts of Riemann zeta zeros as frequency assignments for
attention heads:

```python
# Standard: head frequencies are learned or evenly spaced
# ZetaBias: head_freq[i] = zeta_zero_imaginary[i] / normalization
```

Applied as a multiplicative or additive bias on attention scores.

### 3.3 Prime-Factored Multi-Scale Attention (PrimeScale)

Assign each attention head a prime-indexed attention stride:

```python
# Head 0: attends every 2 tokens  (local detail)
# Head 1: attends every 3 tokens  (slightly wider)
# Head 2: attends every 5 tokens  (medium range)
# Head 3: attends every 7 tokens  (paragraph scale)
# Head 4: attends every 11 tokens (section scale)
# ...
```

By the fundamental theorem of arithmetic, any integer distance can be
represented as a product of primes — so any attention distance is reachable
by combining heads.

### 3.4 Comparison Metrics

For each encoding scheme, we measure:

1. **Position distinguishability** — cosine similarity between PE(pos_i) and
   PE(pos_j) as a function of |i-j|. Lower is better at large distances.

2. **Relative position sensitivity** — how well dot(PE(i), PE(j)) encodes
   the relative distance |i-j|. Should be monotonically decreasing.

3. **Information capacity** — mutual information between position index and
   encoding vector. Higher is better.

4. **Aliasing distance** — the smallest |i-j| where cos_sim(PE(i), PE(j))
   exceeds a threshold (e.g., 0.95). Larger is better.

5. **Practical performance** — perplexity on next-token prediction at various
   context lengths, using a small transformer trained from scratch.

---

## 4. Experimental Plan

### Phase 1: Mathematical Analysis (no ML needed)
- Implement all PE schemes as pure NumPy/PyTorch
- Compute distinguishability curves for positions 0 to 100,000
- Compare aliasing distances
- Visualize frequency spectra
- Plot the "uniqueness horizon" of each scheme

### Phase 2: Synthetic Benchmarks
- Train tiny transformers (2-4 layers, 128-256 dim) on synthetic tasks:
  - **Copy task**: input sequence → output same sequence (tests position memory)
  - **Reversal task**: input → reversed output (tests relative position)
  - **Needle-in-haystack**: find a specific token buried at various depths
  - **Long-range dependency**: predict a value that depends on a token N positions ago

### Phase 3: Real-World Comparison (if Phase 1-2 show promise)
- Swap PE in a small language model and measure perplexity
- Test on the "lost in the middle" benchmark
- Compare with RoPE, ALiBi, and sinusoidal baselines

---

## 5. References

- Vaswani et al. (2017) — "Attention Is All You Need" (sinusoidal PE)
- Su et al. (2021) — "RoFormer: Enhanced Transformer with Rotary Position Embedding"
- Press et al. (2022) — "Train Short, Test Long: Attention with Linear Biases"
- Liu et al. (2023) — "Lost in the Middle: How Language Models Use Long Contexts"
- du Sautoy, Marcus — "The Music of the Primes" (popular mathematics)
- Edwards, H.M. — "Riemann's Zeta Function" (mathematical reference)

---

## Change Log

| Version | Date | Description |
|---------|------|-------------|
| v0.1.0 | 2026-03-27 | Initial research design and mathematical foundations |
