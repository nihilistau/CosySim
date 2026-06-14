#!/usr/bin/env python3
"""
Launch CLI - Scene & Service Launcher
========================================

Launch individual scenes, core services, or everything.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/launch.py penthouse     # Single scene
    python apps/launch.py --core        # Core scenes + services
    python apps/launch.py --all         # Everything
    python apps/launch.py --list        # Show targets with port status
    python apps/launch.py --status      # System health check
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, ROOT
bootstrap()


def main() -> int:
    return run(ROOT / "launcher.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
