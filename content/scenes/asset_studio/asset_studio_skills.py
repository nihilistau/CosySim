"""Asset Studio skills — @skill-decorated functions for LLM agent access.

Exposes asset generation, library query, and voice design operations as
first-class CosySim skills that any agent can call.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


@skill(
    pack="asset_studio",
    description="Generate an image using ComfyUI. Provide a subject description and optional scene/mood.",
    category="MEDIA",
    cooldown=5.0,
    cost=2.0,
    tags=["image", "generation", "comfyui"],
)
def generate_image(
    subject: str,
    scene: str = "",
    mood: str = "neutral",
    preset_id: str = "dark_renaissance",
    width: int = 512,
    height: int = 512,
) -> str:
    """Generate a scene image via ComfyUI.

    Args:
        subject: What to depict in the image.
        scene: Scene slug for contextual style.
        mood: Mood modifier (neutral|tense|romantic|dangerous|…).
        preset_id: Style preset ID.
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        Image URL or error message.
    """
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    result = get_studio_core().generate("image", {
        "subject": subject, "scene": scene, "mood": mood,
        "preset_id": preset_id, "width": width, "height": height,
    })
    if result.get("error"):
        return f"Error: {result['error']}"
    return result.get("url", "/static/img/placeholder.png")


@skill(
    pack="asset_studio",
    description="Generate a character portrait. Provide character_id and mood.",
    category="MEDIA",
    cooldown=5.0,
    cost=2.0,
    tags=["portrait", "character", "comfyui"],
)
def generate_portrait(
    character_id: str,
    mood: str = "neutral",
    scene: str = "",
    preset_id: str = "dark_renaissance",
) -> str:
    """Generate a character portrait via ComfyUI.

    Args:
        character_id: Character identifier (e.g. 'aria').
        mood: Mood of the portrait.
        scene: Scene context slug.
        preset_id: Style preset ID.

    Returns:
        Portrait URL or error message.
    """
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    result = get_studio_core().generate("portrait", {
        "character_id": character_id, "mood": mood,
        "scene": scene, "preset_id": preset_id,
    })
    if result.get("error"):
        return f"Error: {result['error']}"
    return result.get("url", "/static/img/placeholder.png")


@skill(
    pack="asset_studio",
    description="Synthesise a voice clip for a given text. Returns URL to WAV file.",
    category="MEDIA",
    cooldown=3.0,
    cost=1.5,
    tags=["voice", "tts", "audio"],
)
def generate_voice(
    text: str,
    character_id: str = "",
    voice: str = "default",
    backend: str = "auto",
) -> str:
    """Synthesise speech for *text*.

    Args:
        text: Text to speak.
        character_id: Use this character's voice design (optional).
        voice: Voice name override.
        backend: TTS backend (auto|piper|orpheus|qwen3).

    Returns:
        URL to WAV file or error message.
    """
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    result = get_studio_core().generate("voice", {
        "text": text, "character_id": character_id,
        "voice": voice, "backend": backend,
    })
    if result.get("error"):
        return f"Error: {result['error']}"
    return result.get("url", "")


@skill(
    pack="asset_studio",
    description="Create a game item with LLM-generated stats and a ComfyUI icon.",
    category="GAME",
    cooldown=8.0,
    cost=3.0,
    tags=["item", "game", "generation"],
)
def create_game_item(
    item_name: str,
    archetype: str = "weapon",
    scene: str = "",
    rarity: str = "common",
    generate_icon: bool = True,
) -> str:
    """Create a game item with stats and icon.

    Args:
        item_name: Item name (e.g. 'Dagger of Shadows').
        archetype: weapon|armor|potion|key|scroll|ring|amulet|book|coin|card|food|plant|tool|tech|clothing.
        scene: Scene context.
        rarity: common|uncommon|rare|epic|legendary.
        generate_icon: Whether to render a ComfyUI icon.

    Returns:
        JSON string of item data or error.
    """
    import json  # noqa: PLC0415
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    result = get_studio_core().generate("item", {
        "item_name": item_name, "archetype": archetype,
        "scene": scene, "rarity": rarity, "generate_icon": generate_icon,
    })
    if result.get("error"):
        return f"Error: {result['error']}"
    return json.dumps(result.get("item_data", {}), indent=2)


@skill(
    pack="asset_studio",
    description="Generate an SVG graphic from a natural-language description.",
    category="MEDIA",
    cooldown=5.0,
    cost=1.5,
    tags=["svg", "graphic", "generation"],
)
def generate_svg(
    subject: str,
    style: str = "minimal",
    scene: str = "",
) -> str:
    """Generate an SVG via LMStudio.

    Args:
        subject: What the SVG depicts.
        style: minimal|detailed|logo|icon|ornate.
        scene: Scene context for colour palette.

    Returns:
        SVG URL or inline SVG content on error.
    """
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    result = get_studio_core().generate("svg", {
        "subject": subject, "style": style, "scene": scene,
    })
    return result.get("url") or result.get("svg_content", "")


@skill(
    pack="asset_studio",
    description="List assets in the library. Filter by type and scene.",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.0,
    tags=["library", "assets"],
)
def list_assets(
    asset_type: str = "",
    scene: str = "",
    limit: int = 20,
) -> str:
    """List assets from the asset library.

    Args:
        asset_type: Filter by type (image|portrait|voice|video|item|svg|audio|'').
        scene: Filter by scene slug ('').
        limit: Max assets to return.

    Returns:
        Formatted summary of assets.
    """
    from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
    lib = get_asset_library()
    assets = lib.list_assets(
        asset_type=asset_type or None,
        scene=scene or None,
        limit=limit,
    )
    if not assets:
        return "No assets found."
    lines = [f"Assets ({len(assets)} results):"]
    for a in assets:
        lines.append(
            f"  [{a['asset_type']}] {a['title']} — {a['url']}"
        )
    stats = lib.stats()
    lines.append(f"\nTotal: {stats['total']} | By type: {stats['by_type']}")
    return "\n".join(lines)


@skill(
    pack="asset_studio",
    description="Check Asset Studio health: backend status and feature flags.",
    category="SYSTEM",
    cooldown=5.0,
    cost=0.0,
    tags=["health", "studio"],
)
def studio_health() -> str:
    """Return Asset Studio health status.

    Returns:
        Formatted health report.
    """
    import json  # noqa: PLC0415
    from engine.asset_studio import get_studio_core  # noqa: PLC0415
    health = get_studio_core().health()
    return json.dumps(health, indent=2)
