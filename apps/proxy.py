#!/usr/bin/env python3
"""
Proxy CLI - Multi-Protocol AI Gateway
========================================

Serves OpenAI, Anthropic, and Gemini protocols simultaneously on one port.
Routes to GitHub Copilot (38 models), local LMStudio, or NotebookLM.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/proxy.py                              # All protocols on :5800
    python apps/proxy.py --default opus               # Default to Claude Opus
    python apps/proxy.py --port 8080                  # Custom port
    python apps/proxy.py --account <account>        # Copilot account
    python apps/proxy.py --lmstudio-url http://X:1234/v1
    python apps/proxy.py --list-models                # Print model catalog
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "model_proxy.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
