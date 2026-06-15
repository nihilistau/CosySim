"""The Sprawl scene package.

The living city — a real-time map of NEONCITY where territory shifts, NPCs
move and the player's avatar walks the streets. This package ships the
bootable scaffold (B-T1); the live map, territory contests and avatar
movement land in later v1.63 tasks.

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Initial scaffold (B-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start
"""
from content.scenes.the_sprawl.the_sprawl_scene import TheSprawlScene

__all__ = ["TheSprawlScene"]
