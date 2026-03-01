"""THE SHATTERED THRONE — Dark Renaissance RPG scene (v0.68)."""

from .realm_scene import RealmScene
from . import realm_skills as _realm_skills  # noqa: F401 — register @skill decorators

SCENE_METADATA = {
    "name": "realm",
    "display_name": "THE SHATTERED THRONE",
    "port": 5562,
    "type": "rpg",
    "accent_color": "#059669",
    "accent_rgb": "5 150 105",
    "description": "The throne is broken. The king is dead. Power is yours to take — or lose.",
}

__all__ = ["RealmScene", "SCENE_METADATA"]
