#!/usr/bin/env python3
"""
Cleanup CLI - Disk Space Recovery
====================================

Reclaim disk space from HAR files, Chrome caches, stale backups,
and uncheckpointed SQLite WAL files.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/cleanup.py                  # Dry run (show what would be freed)
    python apps/cleanup.py --execute        # Actually delete + checkpoint WALs
    python apps/cleanup.py --execute --keep-hars 3  # Keep 3 days of HARs
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "disk_cleanup.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
