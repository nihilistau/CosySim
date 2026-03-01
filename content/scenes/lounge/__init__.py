"""The Velvet Pit — scene package (v0.68 'Dark Renaissance')."""
from .lounge_scene import LoungeScene
from . import lounge_skills as _lounge_skills  # noqa: F401 — register @skill decorators

SCENE_METADATA = {
    "name": "lounge",
    "display_name": "THE VELVET PIT",
    "port": 5557,
    "type": "social",
    "accent_color": "#f59e0b",
    "accent_rgb": "245 158 11",
    "description": "Below the streets. Above the law. The heat never leaves.",
}

__all__ = ["LoungeScene", "SCENE_METADATA"]
