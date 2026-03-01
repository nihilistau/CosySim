"""THE RUSTY ANCHOR — v0.68 'Dark Renaissance' gritty dockside tavern."""
from .tavern_scene import TavernScene
from . import tavern_skills as _tavern_skills  # noqa: F401 — register @skill decorators

SCENE_METADATA = {
    "name": "tavern",
    "display_name": "THE RUSTY ANCHOR",
    "port": 5558,
    "type": "adventure",
    "accent_color": "#92400e",
    "accent_rgb": "146 64 14",
    "description": "Cheap ale. Cheaper lies. The best quests start here.",
}

__all__ = ["TavernScene", "SCENE_METADATA"]