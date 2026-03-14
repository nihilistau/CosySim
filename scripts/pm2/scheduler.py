"""PM2 wrapper: start CosySim scheduler daemon.

Replaces the `python -m engine.nexus.scheduler_daemon` pattern that
PM2 on Windows cannot handle (script: '-m' is treated as a filename).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.nexus.scheduler_daemon import main

if __name__ == "__main__":
    main()
