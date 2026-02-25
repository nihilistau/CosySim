"""The Velvet Lounge — scene package."""
from .lounge_scene import LoungeScene
from . import lounge_skills as _lounge_skills  # noqa: F401 — register @skill decorators

__all__ = ["LoungeScene"]
