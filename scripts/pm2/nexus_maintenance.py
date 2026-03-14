"""PM2 wrapper: run Nexus maintenance health check.

Replaces `python -m engine.nexus.bridge maintain health`.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.nexus.bridge import main

if __name__ == "__main__":
    sys.argv = ["bridge", "maintain", "health"]
    main()
