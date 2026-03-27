#!/usr/bin/env python3
"""
Prime-Harmonic Positional Encoding — Runner
=============================================

CLI to run analysis, tests, and visualization for the prime encoding research.

Version: v0.1.0 [2026-03-27]
Author:  CosySim Research

Usage:
    python apps/prime_encoding/run.py analyze              # Run full comparison
    python apps/prime_encoding/run.py analyze --dim 256     # Custom dimension
    python apps/prime_encoding/run.py analyze --distance 50000  # Test longer range
    python apps/prime_encoding/run.py test                  # Run test suite
    python apps/prime_encoding/run.py demo                  # Quick demo of key properties
    python apps/prime_encoding/run.py primorial             # Show primorial growth
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure imports work
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT))


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run full encoding comparison analysis."""
    from prime_encoding.analysis import compare_encodings, print_comparison, save_results

    print(f"\n  Prime-Harmonic Positional Encoding — Analysis")
    print(f"  d_model={args.dim}, max_distance={args.distance}")
    print(f"  {'=' * 55}\n")

    results = compare_encodings(
        d_model=args.dim,
        max_len=args.distance + 1024,
        max_distance=args.distance,
    )

    print_comparison(results)

    # Save results
    out_path = ROOT / "apps" / "prime_encoding" / "results" / "comparison.json"
    save_results(results, str(out_path))

    # Print key findings
    print("  Key Findings:")
    print(f"  {'-' * 55}")

    # Find best aliasing distance
    best_alias = max(results, key=lambda m: m.aliasing_distance_95)
    worst_alias = min(results, key=lambda m: m.aliasing_distance_95)
    print(f"  Best aliasing resistance (95%):  {best_alias.name} ({best_alias.aliasing_distance_95})")
    print(f"  Worst aliasing resistance (95%): {worst_alias.name} ({worst_alias.aliasing_distance_95})")

    # Find best long-range distinguishability
    best_lr = min(results, key=lambda m: abs(m.avg_sim_1000))
    print(f"  Best long-range (sim@1k):        {best_lr.name} ({best_lr.avg_sim_1000:.6f})")

    # Monotonicity winner
    best_mono = max(results, key=lambda m: m.monotonicity_score)
    print(f"  Most monotonic:                  {best_mono.name} ({best_mono.monotonicity_score:.3f})")

    print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Quick demonstration of key properties."""
    import torch
    import torch.nn.functional as F

    from prime_encoding.encodings import create_encoding
    from prime_encoding.primes import first_n_primes, primorial, zeta_zeros

    print(f"\n  Prime-Harmonic Positional Encoding — Demo")
    print(f"  {'=' * 50}\n")

    # 1. Primorial growth
    print("  1. Primorial Growth (beat period of prime harmonics)")
    print(f"     Using N prime frequencies, encoding repeats after primorial(N):")
    for n in [5, 10, 15, 20]:
        p = primorial(n)
        print(f"     {n:>2} primes -> repeat after {p:>25,} positions")
    print(f"     Compare: geometric base 10000 with 10 bands -> repeat after ~10,000\n")

    # 2. Zeta zero spacing
    print("  2. Riemann Zeta Zero Gaps (quasi-random, no aliasing)")
    zeros = zeta_zeros(15)
    gaps = [zeros[i+1] - zeros[i] for i in range(len(zeros)-1)]
    print(f"     First 15 zeros: {', '.join(f'{z:.2f}' for z in zeros)}")
    print(f"     Gaps:           {', '.join(f'{g:.2f}' for g in gaps)}")
    print(f"     Gap range:      {min(gaps):.2f} to {max(gaps):.2f} (irregular = good)\n")

    # 3. Similarity comparison
    print("  3. Similarity at Various Distances (d_model=128)")
    encodings = [
        ("sinusoidal", create_encoding("sinusoidal", d_model=128, max_len=16384)),
        ("prime(a=0.5)", create_encoding("prime", d_model=128, max_len=16384, alpha=0.5)),
        ("prime(a=1.0)", create_encoding("prime", d_model=128, max_len=16384, alpha=1.0)),
        ("zeta", create_encoding("zeta", d_model=128, max_len=16384)),
        ("hybrid", create_encoding("hybrid", d_model=128, max_len=16384)),
    ]

    distances = [10, 100, 500, 1000, 2000, 5000, 10000]
    print(f"     {'Encoding':<16}", end="")
    for d in distances:
        print(f"  d={d:<5}", end="")
    print()
    print(f"     {'-' * 80}")

    for name, enc in encodings:
        pe = enc.forward(max(distances) + 50)
        print(f"     {name:<16}", end="")
        for d in distances:
            sims = []
            for i in range(min(30, pe.shape[0] - d)):
                v1 = pe[i].unsqueeze(0)
                v2 = pe[i + d].unsqueeze(0)
                sims.append(F.cosine_similarity(v1, v2).item())
            avg = sum(sims) / len(sims)
            print(f"  {avg:>6.3f}", end="")
        print()

    print()
    return 0


def cmd_primorial(args: argparse.Namespace) -> int:
    """Show primorial growth — how long until prime harmonics repeat."""
    from prime_encoding.primes import first_n_primes, primorial

    print(f"\n  Primorial Growth — Beat Period of Prime Harmonics")
    print(f"  {'=' * 55}\n")
    print(f"  {'N Primes':>10} {'Primorial':>30} {'Primes Used'}")
    print(f"  {'-' * 70}")

    for n in range(1, 21):
        p = primorial(n)
        primes = first_n_primes(n)
        primes_str = " x ".join(str(x) for x in primes)
        print(f"  {n:>10} {p:>30,} {primes_str}")

    print(f"\n  At just 15 primes, the encoding is unique for 614 quadrillion positions.")
    print(f"  Standard sinusoidal PE with base=10000 aliases at ~10,000 positions.\n")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run Phase 2 training benchmark."""
    import subprocess
    bench = ROOT / "apps" / "prime_encoding" / "benchmark.py"
    cmd = [sys.executable, str(bench)]
    if args.quick:
        cmd.append("--quick")
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def cmd_test(args: argparse.Namespace) -> int:
    """Run the test suite."""
    import subprocess
    test_dir = ROOT / "apps" / "prime_encoding" / "tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        cwd=str(ROOT),
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prime-Harmonic Positional Encoding — Research Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # analyze
    analyze_p = sub.add_parser("analyze", help="Run full encoding comparison")
    analyze_p.add_argument("--dim", type=int, default=128, help="d_model (default: 128)")
    analyze_p.add_argument("--distance", type=int, default=16384, help="Max distance to test")

    # demo
    sub.add_parser("demo", help="Quick demo of key properties")

    # primorial
    sub.add_parser("primorial", help="Show primorial growth table")

    # benchmark
    bench_p = sub.add_parser("benchmark", help="Run Phase 2 training benchmark")
    bench_p.add_argument("--quick", action="store_true", help="Quick mode (500 steps)")

    # test
    sub.add_parser("test", help="Run test suite")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "analyze": cmd_analyze,
        "demo": cmd_demo,
        "primorial": cmd_primorial,
        "benchmark": cmd_benchmark,
        "test": cmd_test,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
