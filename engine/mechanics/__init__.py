"""engine.mechanics — Shared game-mechanic helpers for CosySim v0.68 "Dark Renaissance".

Modules
-------
investigation
    Visual investigation board: clues, connections, NLM-powered deductions.
consequences
    Cross-scene consequence engine: scheduled events that fire in other scenes.
"""
from engine.mechanics.investigation import InvestigationBoard, Clue, Connection, get_investigation_board
from engine.mechanics.consequences import ConsequenceStore, Consequence, get_consequence_store

__all__ = [
    "InvestigationBoard",
    "Clue",
    "Connection",
    "get_investigation_board",
    "ConsequenceStore",
    "Consequence",
    "get_consequence_store",
]
