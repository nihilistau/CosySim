"""Image Generator — ComfyUI-backed scene/ambient image generation.

Wraps SceneArtManager for non-portrait image generation with full
preset and prompt-builder integration.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ImageGenerator:
    """Generate general-purpose images via ComfyUI.

    Uses :class:`~engine.art.scene_art.SceneArtManager` for the actual
    ComfyUI submission, but builds prompts via :class:`~engine.asset_studio.prompt_builder.PromptBuilder`
    and applies a :class:`~engine.asset_studio.preset_manager.StylePreset`.
    """

    def generate(
        self,
        subject: str,
        scene: str = "",
        mood: str = "neutral",
        preset_id: str = "dark_renaissance",
        extra_positive: str = "",
        extra_negative: str = "",
        width: int = 0,
        height: int = 0,
        steps: int = 0,
        cfg_scale: float = 0.0,
        seed: int = -1,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate an image.

        Args:
            subject: Core subject description.
            scene: Scene slug for contextual prompting.
            mood: Mood modifier key.
            preset_id: Style preset to apply.
            extra_positive: Additional positive prompt keywords.
            extra_negative: Additional negative prompt keywords.
            width: Override preset width (0 = use preset).
            height: Override preset height (0 = use preset).
            steps: Override preset steps (0 = use preset).
            cfg_scale: Override preset CFG (0.0 = use preset).
            seed: RNG seed (-1 = random).

        Returns:
            Dict with ``url``, ``prompt``, ``negative``, ``cached``,
            ``duration_ms``, ``request_id``.
        """
        from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
        from engine.asset_studio.prompt_builder import get_prompt_builder  # noqa: PLC0415
        from engine.art.scene_art import get_scene_art_manager  # noqa: PLC0415

        preset_mgr = get_preset_manager()
        preset = preset_mgr.get(preset_id) or preset_mgr.get_default()
        builder = get_prompt_builder()

        positive, negative = builder.build_image_prompt(
            subject=subject,
            scene=scene,
            mood=mood,
            preset_tags=preset.style_tags,
            preset_neg_tags=preset.negative_tags,
            extra_positive=extra_positive,
            extra_negative=extra_negative,
        )

        # Resolve dimensions from preset unless overridden.
        w = width or preset.width
        h = height or preset.height
        st = steps or preset.steps
        cfg = cfg_scale or preset.cfg_scale

        t_start = time.monotonic()

        # ── Try WorkflowManager first ──────────────────────────────────────
        try:
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            if wm.is_available():
                from pathlib import Path as _Path  # noqa: PLC0415
                from engine.config import get_config as _get_config  # noqa: PLC0415
                _cfg = _get_config()
                # v1.49.1 [2026-03-22] — Use comfyui.output_dir (was stale art.output_dir)
                save_dir = _Path(_cfg.get("comfyui.output_dir", "data/art/output"))
                save_dir.mkdir(parents=True, exist_ok=True)
                _model = wm.select_model([model]) if "model" in locals() else None
                wf_params: Dict[str, Any] = {
                    "positive": positive,
                    "negative": negative,
                    "seed": seed,
                    "width": w,
                    "height": h,
                    "steps": st,
                    "cfg": cfg,
                }
                if _model:
                    wf_params["model"] = _model
                result_wm = wm.generate(
                    "scene_background",
                    wf_params,
                    save_dir=save_dir,
                    filename_prefix="scene_bg",
                )
                if not result_wm.get("error"):
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    return {
                        "url": result_wm["url"],
                        "prompt": positive,
                        "negative": negative,
                        "cached": False,
                        "duration_ms": duration_ms,
                        "request_id": result_wm.get("prompt_id", uuid.uuid4().hex),
                        "preset_id": preset_id,
                        "width": w,
                        "height": h,
                    }
        except Exception as _wm_exc:
            logger.debug("WorkflowManager not available, falling back: %s", _wm_exc)

        # ── Fallback: SceneArtManager ──────────────────────────────────────
        try:
            mgr = get_scene_art_manager()
            # Override config dimensions by patching a minimal ArtRequest through _generate.
            import random as _random  # noqa: PLC0415
            import uuid as _uuid  # noqa: PLC0415
            from engine.art.scene_art import ArtRequest, ArtStyle  # noqa: PLC0415

            req = ArtRequest(
                id=_uuid.uuid4().hex,
                style=ArtStyle.SCENE_BG,
                prompt=positive,
                negative_prompt=negative,
                width=w,
                height=h,
                steps=st,
                cfg_scale=cfg,
                seed=seed,
                scene=scene,
                mood=mood,
            )
            result = mgr._generate(req)
            duration_ms = int((time.monotonic() - t_start) * 1000)

            return {
                "url": result.url,
                "prompt": positive,
                "negative": negative,
                "cached": result.cached,
                "duration_ms": duration_ms,
                "request_id": result.request_id,
                "preset_id": preset.id,
                "width": w,
                "height": h,
            }
        except Exception as exc:
            logger.warning("Image generation failed: %s", exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": "/static/img/placeholder.png",
                "prompt": positive,
                "negative": negative,
                "cached": False,
                "duration_ms": duration_ms,
                "request_id": uuid.uuid4().hex,
                "preset_id": preset_id,
                "error": str(exc),
                "width": w,
                "height": h,
            }
