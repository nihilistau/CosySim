"""The War Room scene package.

Pick a faction, command crews and take the city. The War Room is the player's
faction command center for the v1.63 emergent metagame. This package ships the
bootable scaffold (C-T1); the live command center (faction select, crew orders,
territory ops) lands in later v1.63 tasks.

Version: v1.63.0 [2026-06-16]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-16] — Initial scaffold (C-T1): bootable placeholder scene,
                            registered for launcher/TUI/hub + auto-start
"""
from content.scenes.war_room.war_room_scene import WarRoomScene

__all__ = ["WarRoomScene"]
