#!/usr/bin/env python3
"""
Multi Proxy CLI - Zero-Conversion Multi-Protocol AI Gateway
==============================================================

Direct-path proxy: each protocol serializes straight to/from the
backend with no intermediate format conversion. ~7x faster.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/multi_proxy.py                              # All protocols on :5801
    python apps/multi_proxy.py --default opus               # Default to Claude Opus
    python apps/multi_proxy.py --port 5800                  # Custom port
    python apps/multi_proxy.py --account <account>        # Copilot account
    python apps/multi_proxy.py --lmstudio-url http://X:1234/v1
    python apps/multi_proxy.py --list-models                # Print model catalog
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "model_proxy_direct.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
