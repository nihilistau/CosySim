"""Portrait Generator — character portrait generation with PortraitCache integration.

Wraps SceneArtManager for portrait generation.  On success the result URL
is pushed into PortraitCache so live scenes can display it immediately.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PortraitGenerator:
    """Generate character portraits and update the PortraitCache."""

    def generate(
        self,
        character_id: str,
        mood: str = "neutral",
        scene: str = "",
        preset_id: str = "dark_renaissance",
        extra_positive: str = "",
        extra_negative: str = "",
        adult_allowed: bool = False,
        width: int = 512,
        height: int = 768,
        steps: int = 25,
        cfg_scale: float = 7.5,
        seed: int = -1,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a character portrait.

        Args:
            character_id: Character identifier (e.g. ``"aria"``).
            mood: Mood modifier key.
            scene: Scene context slug.
            preset_id: Style preset to apply.
            extra_positive: Additional positive keywords.
            extra_negative: Additional negative keywords.
            adult_allowed: Enable suggestive keywords if permitted.
            width: Image width.
            height: Image height.
            steps: KSampler steps.
            cfg_scale: CFG guidance scale.
            seed: RNG seed.

        Returns:
            Dict with ``url``, ``prompt``, ``cached``, ``duration_ms``.
        """
        from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
        from engine.asset_studio.prompt_builder import get_prompt_builder  # noqa: PLC0415
        from engine.art.scene_art import get_scene_art_manager  # noqa: PLC0415
        from engine.art.portrait_cache import get_portrait_cache  # noqa: PLC0415

        preset_mgr = get_preset_manager()
        preset = preset_mgr.get(preset_id) or preset_mgr.get_default()
        builder = get_prompt_builder()

        # Ask Nexus for character appearance (best-effort).
        appearance = ""
        try:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            reply = get_nexus_client().ask(
                f"Describe {character_id}'s physical appearance briefly"
            )
            if isinstance(reply, dict):
                appearance = reply.get("answer", "") or reply.get("content", "")
            elif isinstance(reply, str):
                appearance = reply
        except Exception:
            pass

        positive, negative = builder.build_portrait_prompt(
            character_id=character_id,
            mood=mood,
            scene=scene,
            appearance=appearance,
            preset_tags=preset.style_tags,
            preset_neg_tags=preset.negative_tags,
            adult_allowed=adult_allowed,
        )

        if extra_positive:
            positive = f"{positive}, {extra_positive}"
        if extra_negative:
            negative = f"{negative}, {extra_negative}"

        t_start = time.monotonic()
        try:
            mgr = get_scene_art_manager()
            import uuid as _uuid  # noqa: PLC0415
            from engine.art.scene_art import ArtRequest, ArtStyle  # noqa: PLC0415

            req = ArtRequest(
                id=_uuid.uuid4().hex,
                style=ArtStyle.PORTRAIT,
                prompt=positive,
                negative_prompt=negative,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
                scene=scene,
                character_id=character_id,
                mood=mood,
                intensity=2 if adult_allowed else 1,
            )
            result = mgr._generate(req)
            duration_ms = int((time.monotonic() - t_start) * 1000)

            # Push into PortraitCache so live scenes get it immediately.
            url = result.url
            if url and "/placeholder" not in url:
                cache = get_portrait_cache()
                cache.set_url(character_id, mood, url)

            return {
                "url": url,
                "prompt": positive,
                "negative": negative,
                "cached": result.cached,
                "duration_ms": duration_ms,
                "request_id": result.request_id,
                "character_id": character_id,
                "mood": mood,
                "scene": scene,
                "preset_id": preset.id,
            }
        except Exception as exc:
            logger.warning("Portrait generation failed for %s/%s: %s", character_id, mood, exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": "/static/img/placeholder.png",
                "prompt": positive,
                "negative": negative,
                "cached": False,
                "duration_ms": duration_ms,
                "request_id": uuid.uuid4().hex,
                "character_id": character_id,
                "mood": mood,
                "error": str(exc),
            }
