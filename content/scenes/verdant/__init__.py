"""
Verdant Realms — Dual-Agent LitRPG Scene Package
================================================

A Director-and-Companion guided interactive-fiction scene set in the living
Verdant Realms. Showcases dual-agent orchestration, d20 skill checks, turn-based
combat, faction standings, and a quest tracker — all rendered over the premium
v1.64 "Neon Glow-Up" composited scene art.

Version: v1.64.0 [2026-06-27]
Author:  CosySim Team

Change Log:
    v1.64.0 [2026-06-27] — Initial scene package: VerdantRealmsScene registered
                            as a launchable game scene (port 5599).
"""
from __future__ import annotations

from content.scenes.verdant.verdant_scene import VerdantRealmsScene

__all__ = ["VerdantRealmsScene"]
