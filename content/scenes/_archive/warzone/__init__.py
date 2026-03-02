"""Global Strike — Warzone scene package."""
from .warzone_scene import WarzoneScene
from . import warzone_skills as _warzone_skills  # noqa: F401 — register @skill decorators

__all__ = ["WarzoneScene"]
