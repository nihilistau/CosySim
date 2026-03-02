"""Item Generator — LLM-assisted game item creation with ComfyUI icon generation.

Generates a complete game item: LLM creates the stats/description, ComfyUI
renders the icon image.  Both are returned and registered in the asset library.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Default item stats template.
_ITEM_TEMPLATE = """\
Generate a game item in JSON with this exact schema:
{
  "name": "{name}",
  "type": "{archetype}",
  "rarity": "common|uncommon|rare|epic|legendary",
  "description": "1-2 sentence flavour text",
  "stats": {{"key": value}},
  "lore": "1 sentence lore",
  "scene": "{scene}"
}
Return only valid JSON, no markdown, no explanation.
"""


class ItemGenerator:
    """Generate game items using LMStudio for stats and ComfyUI for icons."""

    def generate(
        self,
        item_name: str,
        archetype: str = "weapon",
        scene: str = "",
        rarity: str = "common",
        preset_id: str = "dark_renaissance",
        generate_icon: bool = True,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a complete game item with stats and icon.

        Args:
            item_name: Name of the item (e.g. ``"Dagger of Shadows"``).
            archetype: Item archetype key (weapon|armor|potion|key|…).
            scene: Scene context slug.
            rarity: Rarity tier.
            preset_id: Style preset for icon generation.
            generate_icon: Whether to generate an icon image via ComfyUI.

        Returns:
            Dict with ``item_data``, ``icon_url``, ``duration_ms``.
        """
        t_start = time.monotonic()

        # ── Step 1: LLM generates item stats ──────────────────────────────────
        item_data = self._generate_item_data(item_name, archetype, scene, rarity)

        # ── Step 2: ComfyUI generates icon (optional) ─────────────────────────
        icon_url = "/static/img/placeholder.png"
        if generate_icon:
            icon_url = self._generate_icon(item_name, archetype, scene, preset_id)

        duration_ms = int((time.monotonic() - t_start) * 1000)
        item_data["icon_url"] = icon_url

        return {
            "item_data": item_data,
            "icon_url": icon_url,
            "prompt": f"{item_name}, {archetype}, {scene}",
            "cached": False,
            "duration_ms": duration_ms,
            "preset_id": preset_id,
        }

    def _generate_item_data(
        self, name: str, archetype: str, scene: str, rarity: str
    ) -> Dict[str, Any]:
        """Use LMStudio to generate item stats and description."""
        prompt = _ITEM_TEMPLATE.format(
            name=name, archetype=archetype, scene=scene or "global"
        )
        try:
            from engine.lmstudio.client import get_lmstudio_client  # noqa: PLC0415
            client = get_lmstudio_client()
            response = client.complete(prompt, max_tokens=300, temperature=0.7)
            raw = response.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").lstrip("json").strip()
            data = json.loads(raw)
            data.setdefault("rarity", rarity)
            return data
        except Exception as exc:
            logger.warning("LLM item generation failed: %s", exc)
            return {
                "name": name,
                "type": archetype,
                "rarity": rarity,
                "description": f"A {rarity} {archetype} known as {name}.",
                "stats": {},
                "lore": "",
                "scene": scene,
            }

    def _generate_icon(
        self, name: str, archetype: str, scene: str, preset_id: str
    ) -> str:
        """Generate an item icon image via ComfyUI."""
        try:
            from engine.asset_studio.prompt_builder import get_prompt_builder  # noqa: PLC0415
            from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
            from engine.art.scene_art import get_scene_art_manager, ArtRequest, ArtStyle  # noqa: PLC0415
            import uuid as _uuid  # noqa: PLC0415

            preset_mgr = get_preset_manager()
            preset = preset_mgr.get(preset_id) or preset_mgr.get("minimal") or preset_mgr.get_default()
            builder = get_prompt_builder()

            positive, negative = builder.build_item_prompt(
                item_name=name,
                archetype=archetype,
                scene=scene,
                preset_tags=preset.style_tags,
                preset_neg_tags=preset.negative_tags,
            )

            mgr = get_scene_art_manager()
            req = ArtRequest(
                id=_uuid.uuid4().hex,
                style=ArtStyle.CHARACTER_CARD,
                prompt=positive,
                negative_prompt=negative,
                width=512,
                height=512,
                scene=scene,
            )
            result = mgr._generate(req)
            return result.url
        except Exception as exc:
            logger.warning("Item icon generation failed: %s", exc)
            return "/static/img/placeholder.png"
