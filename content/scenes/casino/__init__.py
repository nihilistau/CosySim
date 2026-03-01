"""CLUB NOIR — High-Stakes Underground Casino. v0.68 Dark Renaissance."""
from .casino_scene import CasinoScene
from . import casino_skills as _casino_skills  # noqa: F401 — register @skill decorators

__all__ = ["CasinoScene"]