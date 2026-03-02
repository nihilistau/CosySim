"""art_skills.py — ComfyUI character portrait and scene background skills.

Wraps :class:`~engine.art.scene_art.SceneArtManager` as @skill-decorated
functions so LLM agents can generate and retrieve portraits on demand.

All results are Nexus-cached by SceneArtManager; portrait URLs are also
pushed into :class:`~engine.art.portrait_cache.PortraitCache` so the
``character_speaking`` socket event can include them instantly.
"""
from __future__ import annotations

import logging
from typing import List

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _get_art() -> "SceneArtManager":  # noqa: F821
    from engine.art.scene_art import get_scene_art_manager
    return get_scene_art_manager()


def _get_portrait_cache() -> "PortraitCache":  # noqa: F821
    from engine.art.portrait_cache import get_portrait_cache
    return get_portrait_cache()


# ──── Portrait Skills ─────────────────────────────────────────────────────────


@skill(
    pack="art",
    description=(
        "Generate a character portrait using ComfyUI. Returns the image URL. "
        "Mood options: neutral, happy, angry, sad, seductive, fearful, surprised, mysterious."
    ),
    category="MEDIA",
    tags=["portrait", "image", "character", "comfyui"],
    cooldown=5.0,
    cost=2.0,
)
def generate_portrait(
    char_id: str,
    mood: str = "neutral",
    scene: str = "",
) -> str:
    """Generate (or retrieve cached) a portrait for *char_id*.

    Args:
        char_id: Character identifier (e.g. ``"aria"``, ``"lola"``).
        mood: Emotional state for the portrait.
        scene: Optional scene slug for contextual background lighting.

    Returns:
        Image URL string, or an error message on failure.
    """
    try:
        result = _get_art().get_character_portrait(char_id, mood=mood, scene=scene)
        _get_portrait_cache().set_url(char_id, mood, result.url)
        cached_tag = " (cached)" if result.cached else f" ({result.generation_ms}ms)"
        return f"{result.url}{cached_tag}"
    except Exception as exc:
        logger.warning("generate_portrait failed for %s: %s", char_id, exc)
        return f"Portrait generation failed: {exc}"


@skill(
    pack="art",
    description=(
        "Get the portrait URL for a character (from cache, no generation). "
        "Returns the URL or empty string if not yet generated."
    ),
    category="MEDIA",
    tags=["portrait", "cache", "character"],
)
def get_portrait_url(char_id: str, mood: str = "neutral") -> str:
    """Return the cached portrait URL for *char_id* without triggering generation.

    Args:
        char_id: Character identifier.
        mood: Mood key.

    Returns:
        URL string or empty string if not cached.
    """
    return _get_portrait_cache().get_url(char_id, mood) or ""


@skill(
    pack="art",
    description=(
        "Generate portraits for all known NPCs in a scene. "
        "Runs in the background; returns a summary of queued characters."
    ),
    category="MEDIA",
    tags=["portrait", "batch", "scene", "comfyui"],
    cooldown=30.0,
    cost=5.0,
)
def batch_generate_portraits(scene: str, mood: str = "neutral") -> str:
    """Pre-generate portraits for all named NPCs in *scene*.

    Looks up the character registry for the scene and generates one portrait
    per NPC at the specified mood. Results are Nexus-cached and pushed into
    :class:`PortraitCache`.

    Args:
        scene: Scene slug (e.g. ``"bedroom"``, ``"casino"``).
        mood: Mood to generate portraits in.

    Returns:
        Summary string listing which characters were queued.
    """
    try:
        from engine.mcp import get_character_registry

        registry = get_character_registry()
        chars: List[str] = []
        for char in registry.get_all_characters():
            char_id = getattr(char, "char_id", None) or getattr(char, "id", None)
            char_scene = getattr(char, "scene", None) or ""
            if char_id and (not char_scene or char_scene == scene):
                chars.append(char_id)

        if not chars:
            return f"No characters found for scene '{scene}'"

        generated = []
        for char_id in chars[:6]:  # cap at 6 to avoid overloading ComfyUI
            try:
                result = _get_art().get_character_portrait(char_id, mood=mood, scene=scene)
                _get_portrait_cache().set_url(char_id, mood, result.url)
                generated.append(char_id)
            except Exception as exc:
                logger.warning("batch_generate_portraits: failed for %s: %s", char_id, exc)

        return f"Generated portraits for: {', '.join(generated)} (scene={scene}, mood={mood})"
    except Exception as exc:
        logger.warning("batch_generate_portraits failed: %s", exc)
        return f"Batch portrait generation failed: {exc}"


# ──── Scene Background Skills ──────────────────────────────────────────────────


@skill(
    pack="art",
    description=(
        "Generate a widescreen background image for a scene using ComfyUI. "
        "Returns the image URL."
    ),
    category="MEDIA",
    tags=["scene", "background", "image", "comfyui"],
    cooldown=10.0,
    cost=3.0,
)
def generate_scene_background(
    scene: str,
    time_of_day: str = "night",
    mood: str = "neutral",
) -> str:
    """Generate (or retrieve cached) a scene background.

    Args:
        scene: Scene slug (e.g. ``"bedroom"``, ``"casino"``).
        time_of_day: Time of day (dawn/morning/afternoon/dusk/night/midnight).
        mood: Dramatic mood (neutral/tense/romantic/dangerous/mysterious etc.).

    Returns:
        Image URL string, or an error message on failure.
    """
    try:
        result = _get_art().get_scene_bg(scene, time_of_day=time_of_day, mood=mood)
        cached_tag = " (cached)" if result.cached else f" ({result.generation_ms}ms)"
        return f"{result.url}{cached_tag}"
    except Exception as exc:
        logger.warning("generate_scene_background failed for %s: %s", scene, exc)
        return f"Background generation failed: {exc}"


@skill(
    pack="art",
    description=(
        "Generate a dramatic action card illustration for a specific moment in the scene. "
        "Describe the visual moment; returns the image URL."
    ),
    category="MEDIA",
    tags=["action", "card", "image", "comfyui"],
    cooldown=5.0,
    cost=2.0,
)
def generate_action_card(
    description: str,
    scene: str = "",
    intensity: int = 1,
) -> str:
    """Generate a one-shot action card for a dramatic moment.

    Args:
        description: Plain-language description of the visual moment.
        scene: Optional scene slug for contextual elements.
        intensity: ContentGate intensity level (1=mild, 2=adult, 3=explicit).

    Returns:
        Image URL string, or an error message on failure.
    """
    try:
        result = _get_art().get_action_card(description, scene=scene, intensity=intensity)
        return f"{result.url} ({result.generation_ms}ms)"
    except Exception as exc:
        logger.warning("generate_action_card failed: %s", exc)
        return f"Action card generation failed: {exc}"
