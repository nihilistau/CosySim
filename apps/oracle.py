#!/usr/bin/env python3
"""
Oracle CLI - CosySim System Diagnostics
=========================================

The All-Seeing Eye. Health checks, error aggregation, performance
metrics, trace waterfall, and log analysis.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/oracle.py                   # Full diagnostic report
    python apps/oracle.py --health          # Service health only
    python apps/oracle.py --errors          # Top errors by count
    python apps/oracle.py --perf            # LLM latency, benchmarks
    python apps/oracle.py --trace <ID>      # Trace waterfall
    python apps/oracle.py --logs 20         # Last 20 error-level logs
    python apps/oracle.py -v                # Verbose mode
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "oracle.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
