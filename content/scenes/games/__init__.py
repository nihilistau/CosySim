"""CosySim game scene modules."""
from .truth_or_dare import truth_or_dare_bp, TruthOrDareGame
from .mystery_investigation import mystery_bp, MysteryGame
from . import games_skills as _games_skills  # noqa: F401 — register @skill decorators

__all__ = ["truth_or_dare_bp", "TruthOrDareGame", "mystery_bp", "MysteryGame"]
