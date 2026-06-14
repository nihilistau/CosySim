#!/usr/bin/env python3
"""
Test CLI - CosySim Testing Tools
===================================

Smart test runner (git-diff aware), browser testing, and scene
health checks.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/test.py                              # Tests for uncommitted changes
    python apps/test.py --smoke                      # Quick smoke tests
    python apps/test.py --domain scene_hub           # All tests for a domain
    python apps/test.py --since HEAD~3               # Tests for last 3 commits
    python apps/test.py --list                       # Dry-run (show what would run)
    python apps/test.py browser                      # Browser UI test
    python apps/test.py browser --scene penthouse    # Test specific scene
    python apps/test.py browser --all                # Test all scenes
    python apps/test.py health                       # Scene health check
    python apps/test.py health --port 5569           # Check specific scene
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    if not sys.argv[1:]:
        return run(SCRIPTS / "smart_test.py", [])

    cmd = sys.argv[1]

    if cmd == "browser":
        return run(SCRIPTS / "browser_test.py", sys.argv[2:])
    elif cmd == "health":
        return run(SCRIPTS / "scene_health_check.py", sys.argv[2:])
    else:
        # Pass everything to smart_test.py (--smoke, --domain, --since, etc.)
        return run(SCRIPTS / "smart_test.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
