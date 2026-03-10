"""The Penthouse — scene package."""
from .penthouse_scene import PenthouseScene
from . import penthouse_skills as _penthouse_skills  # noqa: F401 — register @skill decorators

__all__ = ["PenthouseScene"]