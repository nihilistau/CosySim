"""THE OBSCURA — Dark Gallery Scene package (v0.68 Dark Renaissance)."""
from content.scenes.gallery.gallery_scene import GalleryScene, create_app
from . import gallery_skills as _gallery_skills  # noqa: F401 — register @skill decorators

# Module-level SCENE_METADATA for scene registry discoverability (no import needed)
SCENE_METADATA = {
    "name": "gallery",
    "display_name": "THE OBSCURA",
    "port": 5560,
    "type": "narrative",
    "accent_color": "#7c3aed",
    "accent_rgb": "124 58 237",
    "description": "Art is violence. The exhibit changes you. You cannot unsee it.",
}

__all__ = ["GalleryScene", "create_app", "SCENE_METADATA"]
