"""
PM2 Wrapper — Nexus KMS API Server
====================================

Launches the Nexus Knowledge Management System from its own project
directory (C:\\Files\\Nexus) so PM2 can manage it alongside CosySim services.
Nexus KMS must be running before any CosySim scene that queries the knowledge
graph — this wrapper ensures PM2 can restart it on crash.

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — Added module header, version stamp
    v1.42.0 [2026-03-21] — Created as part of managed Nexus KMS integration
"""
from __future__ import annotations

import os
import subprocess
import sys

NEXUS_ROOT = r"C:\Files\Nexus"

if __name__ == "__main__":
    if not os.path.isdir(NEXUS_ROOT):
        print(f"Nexus directory not found: {NEXUS_ROOT}", file=sys.stderr)
        sys.exit(1)
    sys.exit(
        subprocess.call(
            [sys.executable, "-m", "nexus", "api"],
            cwd=NEXUS_ROOT,
        )
    )
