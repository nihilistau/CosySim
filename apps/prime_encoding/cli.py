#!/usr/bin/env python3
"""
PrimePE CLI — Interactive research runner for prime-harmonic positional encoding.
==================================================================================

One command to run any experiment, compare results, tune parameters, and probe
trained models. All Phase 1-3 experiments accessible from a single interface.

Version: v1.5.1 [2026-03-27]
Author:  CosySim Research

Usage:
    python apps/prime_encoding/cli.py demo                    # Quick visual demo
    python apps/prime_encoding/cli.py analyze                 # Phase 1 math comparison
    python apps/prime_encoding/cli.py train --pe zeta         # Train single variant
    python apps/prime_encoding/cli.py train --pe all          # Train all variants
    python apps/prime_encoding/cli.py compare                 # Compare saved results
    python apps/prime_encoding/cli.py sweep --param alpha     # Parameter sweep
    python apps/prime_encoding/cli.py probe --pe hybrid_90z   # Attention distance probe
    python apps/prime_encoding/cli.py test                    # Run test suite
    python apps/prime_encoding/cli.py primorial               # Show primorial growth
    python apps/prime_encoding/cli.py freqs --pe zeta --dim 256  # Show frequency values
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "apps" / "prime_encoding" / "results"

ALL_PE = ["sinusoidal", "prime_05", "prime_10", "zeta", "hybrid",
          "hybrid_70z", "hybrid_90z"]


# ──── Helpers ────────────────────────────────────────────────────────────────

def _load_results() -> Dict[str, Any]:
    """Load saved Phase 3 results if they exist."""
    p3 = RESULTS_DIR / "phase3" / "phase3_results.json"
    if p3.exists():
        with open(p3) as f:
            return json.load(f)
    return {}


def _device_info() -> str:
    import torch
    if torch.cuda.is_available():
        return f"cuda ({torch.cuda.get_device_name(0)})"
    return "cpu"


# ──── Commands ───────────────────────────────────────────────────────────────

def cmd_demo(args: argparse.Namespace) -> int:
    """Quick visual demo of key properties."""
    from prime_encoding.run import cmd_demo as _demo
    return _demo(args)


def cmd_primorial(args: argparse.Namespace) -> int:
    """Show primorial growth table."""
    from prime_encoding.run import cmd_primorial as _primorial
    return _primorial(args)


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run Phase 1 mathematical analysis."""
    from prime_encoding.analysis import compare_encodings, print_comparison, save_results
    print(f"\n  Phase 1 Analysis — d_model={args.dim}, max_distance={args.distance}")
    print(f"  Device: {_device_info()}\n")
    results = compare_encodings(d_model=args.dim, max_len=args.distance + 1024,
                                 max_distance=args.distance)
    print_comparison(results)
    save_results(results, str(RESULTS_DIR / "comparison.json"))
    return 0


def cmd_freqs(args: argparse.Namespace) -> int:
    """Show the actual frequency values for a PE scheme."""
    from prime_encoding.phase3_local import make_frequencies

    pe = args.pe
    dim = args.dim
    freqs = make_frequencies(pe, dim)

    print(f"\n  Frequencies for {pe} (d_model={dim}, {len(freqs)} values)")
    print(f"  {'-' * 55}")
    print(f"  min={freqs.min():.6f}  max={freqs.max():.6f}  range={freqs.max()/freqs.min():.1f}x")
    print(f"\n  Values:")
    for i, f in enumerate(freqs.tolist()):
        marker = ""
        if i < 10 or i >= len(freqs) - 5 or i % (len(freqs) // 10) == 0:
            print(f"    [{i:>3}] {f:.6f}{marker}")
        elif i == 10:
            print(f"    ...")
    print()
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    """Train one or all PE variants on WikiText-103."""
    from prime_encoding.phase3_local import get_config, train_variant

    cfg = get_config(quick=args.quick, steps=args.steps)

    # Override config from CLI args
    if args.dim:
        cfg["d_model"] = args.dim
        cfg["ffn_dim"] = args.dim * 4
    if args.heads:
        cfg["n_heads"] = args.heads
    if args.layers:
        cfg["n_layers"] = args.layers
    if args.lr:
        cfg["lr"] = args.lr
    if args.batch:
        cfg["batch_size"] = args.batch
    if args.ctx:
        cfg["train_seq_len"] = args.ctx
    if args.eval_ctx:
        cfg["eval_seq_lens"] = [int(x) for x in args.eval_ctx.split(",")]

    pe_list = ALL_PE if args.pe == "all" else [args.pe]
    RESULTS_DIR.joinpath("phase3").mkdir(parents=True, exist_ok=True)

    print(f"\n  PrimePE Training — {_device_info()}")
    print(f"  Model: {cfg['n_layers']}L, d={cfg['d_model']}, {cfg['n_heads']}H")
    print(f"  Steps: {cfg['max_steps']}, lr={cfg['lr']}, batch={cfg['batch_size']}x{cfg['grad_accum']}")
    print(f"  Train ctx: {cfg['train_seq_len']}, Eval ctx: {cfg['eval_seq_lens']}")
    print(f"  PE variants: {pe_list}\n")

    all_results = _load_results()

    for pe in pe_list:
        result = train_variant(pe, cfg)
        all_results[pe] = result
        out = RESULTS_DIR / "phase3" / "phase3_results.json"
        with open(out, "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    # Print summary
    _print_comparison(all_results, cfg["eval_seq_lens"])
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare all saved results."""
    results = _load_results()
    if not results:
        print("  No saved results. Run 'train' first.")
        return 1

    # Determine eval lengths from data
    lengths = set()
    for r in results.values():
        for k in r.get("ppl_by_ctx", {}).keys():
            lengths.add(int(k))
    lengths = sorted(lengths)

    _print_comparison(results, lengths)

    # Attention probe results
    has_probe = any(r.get("attention_probe") for r in results.values())
    if has_probe:
        print(f"  Attention Distance Probe:")
        print(f"  {'-' * 50}")
        for pe, r in results.items():
            probe = r.get("attention_probe", {})
            if probe:
                bands = ", ".join(f"{k}={v:.1f}" for k, v in sorted(probe.items()))
                print(f"  {pe:<18} {bands}")
        print()

    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    """Sweep a parameter to find the optimal value."""
    from prime_encoding.phase3_local import get_config, train_variant

    cfg = get_config(quick=True, steps=args.steps or 500)
    if args.ctx:
        cfg["train_seq_len"] = args.ctx

    if args.param == "alpha":
        values = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]
        print(f"\n  Sweeping alpha for PrimePE (d={cfg['d_model']}, {cfg['max_steps']} steps)")
        print(f"  {'-' * 50}")
        sweep_results = {}
        for alpha in values:
            pe_name = f"prime_a{alpha}"
            # Monkey-patch the frequency generator for this alpha
            from prime_encoding import phase3_local as p3
            original_fn = p3.make_frequencies

            def patched(pe_type, d_model, _alpha=alpha):
                if pe_type == pe_name:
                    from prime_encoding.primes import first_n_primes
                    import torch
                    half = d_model // 2
                    primes = first_n_primes(half)
                    return torch.tensor([1.0 / (p ** _alpha) for p in primes], dtype=torch.float)
                return original_fn(pe_type, d_model)

            p3.make_frequencies = patched
            try:
                r = train_variant(pe_name, cfg)
                ppl_512 = r["ppl_by_ctx"].get(512, r["ppl_by_ctx"].get("512"))
                ppl_max = None
                for k in sorted(r["ppl_by_ctx"].keys(), key=lambda x: int(x), reverse=True):
                    v = r["ppl_by_ctx"][k]
                    if v is not None:
                        ppl_max = v
                        break
                sweep_results[alpha] = {"ppl_512": ppl_512, "ppl_max": ppl_max}
                deg = ((ppl_max - ppl_512) / ppl_512 * 100) if ppl_512 and ppl_max else 0
                print(f"    alpha={alpha:.1f}: ppl@512={ppl_512:.1f}, ppl@max={ppl_max:.1f}, deg={deg:+.1f}%")
            finally:
                p3.make_frequencies = original_fn

        print()
        best = min(sweep_results, key=lambda a: abs(sweep_results[a].get("ppl_max", 9999) -
                                                     sweep_results[a].get("ppl_512", 9999)))
        print(f"  Best alpha: {best} (least degradation)")

    elif args.param == "zeta_ratio":
        ratios = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]
        print(f"\n  Sweeping zeta ratio for HybridPE (d={cfg['d_model']}, {cfg['max_steps']} steps)")
        print(f"  {'-' * 50}")
        for ratio in ratios:
            if ratio == 1.0:
                pe = "zeta"
            elif ratio == 0.5:
                pe = "hybrid"
            else:
                pe = f"hybrid_{int(ratio*100)}z"
            r = train_variant(pe, cfg)
            ppl_512 = r["ppl_by_ctx"].get(512, r["ppl_by_ctx"].get("512"))
            ppl_max = None
            for k in sorted(r["ppl_by_ctx"].keys(), key=lambda x: int(x), reverse=True):
                v = r["ppl_by_ctx"][k]
                if v is not None:
                    ppl_max = v
                    break
            deg = ((ppl_max - ppl_512) / ppl_512 * 100) if ppl_512 and ppl_max else 0
            print(f"    zeta={ratio:.0%}: ppl@512={ppl_512:.1f}, ppl@max={ppl_max:.1f}, deg={deg:+.1f}%")

    else:
        print(f"  Unknown param: {args.param}. Available: alpha, zeta_ratio")
        return 1

    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Run attention distance probe on a freshly trained model."""
    from prime_encoding.phase3_local import get_config, train_variant

    cfg = get_config(quick=True, steps=args.steps or 500)
    if args.ctx:
        cfg["train_seq_len"] = args.ctx

    pe = args.pe
    print(f"\n  Training {pe} then probing attention distances...")
    r = train_variant(pe, cfg)

    probe = r.get("attention_probe", {})
    if probe:
        print(f"\n  Attention Distance Probe for {pe}:")
        print(f"  {'-' * 40}")
        for band, dist in sorted(probe.items()):
            print(f"    {band}: {dist:.1f} tokens")
        if len(probe) == 2:
            vals = list(probe.values())
            gap = abs(vals[0] - vals[1]) / min(vals) * 100
            print(f"\n    Gap: {gap:.1f}%")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run the test suite."""
    import subprocess
    test_dir = ROOT / "apps" / "prime_encoding" / "tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        cwd=str(ROOT),
    )
    return result.returncode


# ──── Output Helpers ─────────────────────────────────────────────────────────

def _print_comparison(results: Dict[str, Any], lengths: List[int]) -> None:
    """Print formatted results comparison table."""
    print(f"\n  {'PE':<18}", end="")
    for l in lengths:
        print(f"  ctx={l:<5}", end="")
    print(f"  {'Degrad':>8}")
    print(f"  {'-' * (18 + 9 * len(lengths) + 10)}")

    for pe, r in results.items():
        ppls = r.get("ppl_by_ctx", {})
        row = f"  {pe:<18}"
        first_ppl = None
        last_ppl = None
        for l in lengths:
            ppl = ppls.get(l) or ppls.get(str(l))
            if ppl is not None:
                row += f"  {ppl:>7.1f}"
                if first_ppl is None:
                    first_ppl = ppl
                last_ppl = ppl
            else:
                row += f"  {'---':>7}"
        if first_ppl and last_ppl:
            deg = (last_ppl - first_ppl) / first_ppl * 100
            sign = "+" if deg > 0 else ""
            row += f"  {sign}{deg:>6.1f}%"
        print(row)
    print()


# ──── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="primpe",
        description="PrimePE — Prime-Harmonic Positional Encoding Research CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  demo                       Quick visual demo of key properties
  primorial                  Show primorial growth table
  analyze                    Phase 1 mathematical comparison
  freqs --pe TYPE --dim N    Show frequency values for a PE scheme
  train --pe TYPE            Train on WikiText-103 (use --pe all for all variants)
  compare                    Compare all saved results
  sweep --param NAME         Sweep alpha or zeta_ratio
  probe --pe TYPE            Train + run attention distance probe
  test                       Run test suite (84 tests)

PE types: sinusoidal, prime_05, prime_10, zeta, hybrid,
          hybrid_70z, hybrid_90z, all

Examples:
  primpe train --pe zeta --steps 2000 --ctx 512
  primpe train --pe all --quick
  primpe sweep --param zeta_ratio --steps 500
  primpe probe --pe hybrid_90z --steps 1000
  primpe compare
  primpe freqs --pe zeta --dim 512
""",
    )

    sub = parser.add_subparsers(dest="command")

    # demo
    sub.add_parser("demo", help="Quick demo of key properties")

    # primorial
    sub.add_parser("primorial", help="Show primorial growth")

    # analyze
    ap = sub.add_parser("analyze", help="Phase 1 math comparison")
    ap.add_argument("--dim", type=int, default=128, help="d_model (default: 128)")
    ap.add_argument("--distance", type=int, default=16384, help="Max distance")

    # freqs
    fp = sub.add_parser("freqs", help="Show frequency values")
    fp.add_argument("--pe", required=True, help="PE type")
    fp.add_argument("--dim", type=int, default=256, help="d_model")

    # train
    tp = sub.add_parser("train", help="Train on WikiText-103")
    tp.add_argument("--pe", default="zeta", help="PE type or 'all'")
    tp.add_argument("--steps", type=int, default=0, help="Training steps (0=default)")
    tp.add_argument("--quick", action="store_true", help="Quick mode (500 steps)")
    tp.add_argument("--dim", type=int, default=0, help="d_model (0=default 256)")
    tp.add_argument("--heads", type=int, default=0, help="Attention heads")
    tp.add_argument("--layers", type=int, default=0, help="Transformer layers")
    tp.add_argument("--lr", type=float, default=0, help="Learning rate")
    tp.add_argument("--batch", type=int, default=0, help="Batch size")
    tp.add_argument("--ctx", type=int, default=0, help="Training context length")
    tp.add_argument("--eval-ctx", type=str, default="", help="Eval lengths (comma-sep)")

    # compare
    sub.add_parser("compare", help="Compare saved results")

    # sweep
    sp = sub.add_parser("sweep", help="Parameter sweep")
    sp.add_argument("--param", required=True, choices=["alpha", "zeta_ratio"],
                    help="Parameter to sweep")
    sp.add_argument("--steps", type=int, default=500, help="Steps per run")
    sp.add_argument("--ctx", type=int, default=0, help="Training context length")

    # probe
    pp = sub.add_parser("probe", help="Attention distance probe")
    pp.add_argument("--pe", default="hybrid_90z", help="PE type to probe")
    pp.add_argument("--steps", type=int, default=500, help="Training steps before probe")
    pp.add_argument("--ctx", type=int, default=0, help="Training context length")

    # test
    sub.add_parser("test", help="Run test suite")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "demo": cmd_demo,
        "primorial": cmd_primorial,
        "analyze": cmd_analyze,
        "freqs": cmd_freqs,
        "train": cmd_train,
        "compare": cmd_compare,
        "sweep": cmd_sweep,
        "probe": cmd_probe,
        "test": cmd_test,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
