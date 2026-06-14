#!/usr/bin/env python3
"""
Ask CLI - Unified AI Query Router
====================================

Route prompts to GitHub Copilot (38 frontier models), NotebookLM
(grounded research), or local LMStudio inference.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/ask.py "your prompt"                      # Default: gpt-5.4
    python apps/ask.py "your prompt" --model claude-opus-4.6
    python apps/ask.py "your prompt" --model gemini-3.1-pro
    python apps/ask.py "your prompt" --nlm                # NotebookLM
    python apps/ask.py "your prompt" --local               # LMStudio
    python apps/ask.py --models                            # List all models
    python apps/ask.py --models --vendor anthropic         # Filter by vendor
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "ask.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
