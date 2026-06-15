"""Emergent engine package — persistent, self-evolving world simulation.

The emergent engine gives CosySim a living, persistent substrate: factions that
gain and lose power, territory that changes hands, NPCs that pursue durable
goals, and world events that accumulate over time. Everything is backed by a
single SQLite store (:mod:`engine.world.emergent.store`) so state survives
restarts and is queryable by every downstream system.

Version: v1.63.0 [2026-06-15]
Author:  CosySim Team

Change Log:
    v1.63.0 [2026-06-15] — Package created for the v1.63 Emergent Engine
                            (A1: persistent sim store).
"""
from __future__ import annotations
