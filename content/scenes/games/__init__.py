"""THE ARCADE — v0.68 Dark Renaissance game scene package."""
from .games_scene import GamesScene
from .truth_or_dare import truth_or_dare_bp, TruthOrDareGame
from .mystery_investigation import mystery_bp, MysteryGame
from . import games_skills as _games_skills  # noqa: F401 — register @skill decorators

__all__ = ["GamesScene", "truth_or_dare_bp", "TruthOrDareGame", "mystery_bp", "MysteryGame"]
