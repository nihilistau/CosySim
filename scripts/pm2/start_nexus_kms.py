"""PM2 wrapper: start Nexus KMS API server.

Launches the Nexus Knowledge Management System from its own project
directory (C:\\Files\\Nexus) so PM2 can manage it alongside CosySim services.
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
