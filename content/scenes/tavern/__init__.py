"""The Dragon's Flagon — Fantasy tavern showcase scene."""
from .tavern_scene import TavernScene
from . import tavern_skills as _tavern_skills  # noqa: F401 — register @skill decorators

__all__ = ["TavernScene"]
