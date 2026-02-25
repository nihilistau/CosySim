"""
Gallery Skills — MCP skill functions for the Art Gallery scene.

Exposes art creation, critique, exhibition management, and room navigation
as @skill-decorated functions callable by LMS agents via tool use.
"""
from __future__ import annotations

import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_gallery_scene():
    """Look up the running Gallery scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("gallery")


# ── Exhibition Management ──────────────────────────────────────

@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.GAME,
    description="Get the current exhibition status and displayed artworks.",
)
def gallery_exhibition_status() -> str:
    """Return current exhibition theme, art count, and room status."""
    scene = _get_gallery_scene()
    if not scene:
        return "Gallery not active."
    state = getattr(scene, "_scene_state", {})
    if callable(getattr(state, "to_dict", None)):
        state = state.to_dict()
    theme = state.get("current_theme", "Free expression")
    art_count = len(state.get("artworks", []))
    room = state.get("current_room", "main_hall")
    return f"Exhibition: '{theme}' | Artworks: {art_count} | Room: {room}"


@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.GAME,
    description="Create a new artwork for the exhibition.",
    cooldown=20,
)
def gallery_create_art(title: str = "Untitled", style: str = "abstract", description: str = "") -> str:
    """Submit a new artwork to the gallery exhibition."""
    scene = _get_gallery_scene()
    if not scene:
        return "Gallery not active."
    if not title or title == "Untitled":
        return "Give your artwork a title!"
    return f"Artwork '{title}' ({style}) submitted to the exhibition. {description}"


@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.SOCIAL,
    description="Critique an artwork in the gallery.",
    cooldown=10,
)
def gallery_critique(artwork_title: str = "", rating: int = 5) -> str:
    """Give an art critique with a rating (1-10)."""
    rating = max(1, min(10, rating))
    if not artwork_title:
        return "Specify which artwork to critique."
    verdicts = {
        range(1, 4): "A bold failure, but failure nonetheless.",
        range(4, 7): "Shows promise. The technique needs refinement.",
        range(7, 9): "Impressive work. The composition speaks volumes.",
        range(9, 11): "A masterpiece. This belongs in the permanent collection.",
    }
    verdict = next((v for r, v in verdicts.items() if rating in r), "Interesting.")
    return f"Critique of '{artwork_title}' ({rating}/10): {verdict}"


@skill(
    pack="gallery",
    tags=["game", "gallery"],
    category=SkillCategory.GAME,
    description="Move to a different room in the gallery.",
)
def gallery_change_room(room: str = "main_hall") -> str:
    """Navigate to a gallery room: main_hall, modern_wing, sculpture_garden, private_collection."""
    valid = ["main_hall", "modern_wing", "sculpture_garden", "private_collection"]
    if room not in valid:
        return f"Unknown room. Available: {', '.join(valid)}"
    scene = _get_gallery_scene()
    if not scene:
        return "Gallery not active."
    if room == "private_collection":
        return "The private collection is locked. You need curator access."
    return f"Moved to {room.replace('_', ' ').title()}."


@skill(
    pack="gallery",
    tags=["game", "gallery", "art"],
    category=SkillCategory.SOCIAL,
    description="Challenge another critic to an art debate.",
    cooldown=30,
)
def gallery_art_debate(topic: str = "modern art", opponent: str = "") -> str:
    """Start an art debate on a topic."""
    if not opponent:
        return "Who do you want to debate?"
    return f"Art debate initiated: '{topic}' — you vs {opponent}. Make your opening argument!"
