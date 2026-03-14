"""PM2 wrapper: reseed Copilot rules into Nexus.

Replaces `python -m engine.nexus.seed_copilot_rules`.
"""
from __future__ import annotations

import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.nexus.seed_copilot_rules import seed_all

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    force = "--force" in sys.argv
    check = "--check" in sys.argv
    seed_all(force=force, check_only=check)
