#!/usr/bin/env python3
"""
Heap CLI - V8 Heap Snapshot Mining
=====================================

Mine V8 heap snapshots for credentials, tokens, API keys, JWTs,
protobuf schemas, conversation history, and application internals.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] - Initial standalone CLI

Usage:
    python apps/heap.py heap snapshot.heapsnapshot     # Parse heap file
    python apps/heap.py cookies --update-pool account  # Decrypt Chrome cookies
    python apps/heap.py live --metamap                 # Scan live Chrome memory
    python apps/heap.py all                            # Run all three
    python apps/heap.py report                         # Summarize previous runs
    python apps/heap.py nexus-push                     # Push findings to Nexus
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, run, SCRIPTS
bootstrap()


def main() -> int:
    return run(SCRIPTS / "heap_toolkit.py", sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
