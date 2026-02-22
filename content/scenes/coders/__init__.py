"""The Coders Room — AI Agent Idle Code Simulation scene."""
from .coders_scene import CodersRoomScene
from . import coders_skills as _coders_skills  # noqa: F401 — register @skill decorators

__all__ = ["CodersRoomScene"]
