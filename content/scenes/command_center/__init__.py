"""Command Center — Real-time system observatory scene."""
from .command_center_scene import CommandCenterScene, SCENE_ID, DEFAULT_PORT
from . import command_center_skills  # noqa: F401 — register skills

__all__ = ["CommandCenterScene", "SCENE_ID", "DEFAULT_PORT"]
