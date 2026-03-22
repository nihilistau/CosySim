"""Video Generator — AnimateDiff-backed video clip generation (ComfyUI).

Generates short animated video clips via ComfyUI's AnimateDiff workflow.
Falls back gracefully when AnimateDiff is not installed.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)


class VideoGenerator:
    """Generate short video clips via ComfyUI AnimateDiff.

    When ComfyUI or AnimateDiff is unavailable the generator returns a
    graceful fallback rather than raising an exception.
    """

    def generate(
        self,
        subject: str,
        scene: str = "",
        mood: str = "neutral",
        motion: str = "subtle",
        preset_id: str = "dark_renaissance",
        frames: int = 16,
        fps: int = 8,
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a short animated video clip.

        Args:
            subject: Scene/subject description.
            scene: Scene slug for context.
            mood: Mood modifier.
            motion: Motion style (subtle|moderate|dynamic).
            preset_id: Style preset.
            frames: Number of frames to generate.
            fps: Output frame rate.
            width: Frame width.
            height: Frame height.
            steps: KSampler steps.
            cfg_scale: CFG guidance scale.
            seed: RNG seed.

        Returns:
            Dict with ``url``, ``prompt``, ``duration_ms``.
        """
        from engine.asset_studio.prompt_builder import get_prompt_builder  # noqa: PLC0415
        from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415

        preset_mgr = get_preset_manager()
        preset = preset_mgr.get(preset_id) or preset_mgr.get_default()
        builder = get_prompt_builder()

        positive, negative = builder.build_video_prompt(
            subject=subject,
            scene=scene,
            mood=mood,
            motion=motion,
            preset_tags=preset.style_tags,
        )

        t_start = time.monotonic()

        # ── Try WorkflowManager (Wan 2.2) first ───────────────────────────
        try:
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            image_path = _kwargs.get("image_path") or _kwargs.get("image")
            workflow_name = "video_wan_i2v" if image_path else "video_wan_t2v"
            if wm.is_available() and wm.has_node("WanVideoModelLoader") and wm.has_node("WanVideoSampler"):
                from pathlib import Path as _Path  # noqa: PLC0415
                from engine.config import get_config as _get_config  # noqa: PLC0415
                _cfg2 = _get_config()
                # v1.49.1 [2026-03-22] — Use comfyui.output_dir (was stale art.output_dir)
                save_dir = _Path(_cfg2.get("comfyui.output_dir", "data/art/output"))
                save_dir.mkdir(parents=True, exist_ok=True)
                wan_params: Dict[str, Any] = {
                    "positive": positive,
                    "negative": negative,
                    "seed": seed,
                    "width": width,
                    "height": height,
                    "frames": frames,
                    "fps": fps,
                    "steps": steps,
                }
                if image_path:
                    wan_params["image_path"] = image_path
                result_wm = wm.generate(
                    workflow_name,
                    wan_params,
                    save_dir=save_dir,
                    filename_prefix="video",
                    timeout=600.0,
                )
                if not result_wm.get("error"):
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    return {
                        "url": result_wm["url"],
                        "prompt": positive,
                        "negative": negative,
                        "cached": False,
                        "duration_ms": duration_ms,
                        "frames": frames,
                        "fps": fps,
                        "preset_id": preset_id,
                    }
        except Exception as _wm_exc:
            logger.debug("WorkflowManager not available for video, falling back: %s", _wm_exc)

        # ── Fallback: AnimateDiff ──────────────────────────────────────────
        try:
            result = self._submit_animatediff(
                positive=positive,
                negative=negative,
                frames=frames,
                fps=fps,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
            )
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": result,
                "prompt": positive,
                "negative": negative,
                "cached": False,
                "duration_ms": duration_ms,
                "frames": frames,
                "fps": fps,
                "preset_id": preset_id,
            }
        except Exception as exc:
            logger.warning("Video generation failed: %s", exc)
            duration_ms = int((time.monotonic() - t_start) * 1000)
            return {
                "url": "",
                "prompt": positive,
                "negative": negative,
                "cached": False,
                "duration_ms": duration_ms,
                "error": str(exc),
                "note": "AnimateDiff may not be installed in ComfyUI",
            }

    def _submit_animatediff(
        self,
        positive: str,
        negative: str,
        frames: int,
        fps: int,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
    ) -> str:
        """Submit an AnimateDiff workflow to ComfyUI and return the output URL."""
        import random  # noqa: PLC0415
        import requests  # noqa: PLC0415
        from engine.config import get_config  # noqa: PLC0415

        cfg = get_config()
        # v1.49.1 [2026-03-22] — Use comfyui.base_url (was stale art.comfyui_url)
        comfyui_url = cfg.get("comfyui.base_url", "http://localhost:8188").rstrip("/")
        checkpoint = cfg.get("comfyui.checkpoint", "v1-5-pruned-emaonly.ckpt")

        if seed < 0:
            seed = random.randint(0, 2 ** 32)

        request_id = uuid.uuid4().hex

        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "2": {"class_type": "ADE_AnimateDiffLoaderWithContext",
                  "inputs": {"model_name": "mm_sd_v15_v2.ckpt", "beta_schedule": "autoselect",
                             "model": ["1", 0]}},
            "3": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": positive, "clip": ["1", 1]}},
            "4": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": negative, "clip": ["1", 1]}},
            "5": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": frames}},
            "6": {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": steps, "cfg": cfg_scale,
                             "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                             "model": ["2", 0], "positive": ["3", 0],
                             "negative": ["4", 0], "latent_image": ["5", 0]}},
            "7": {"class_type": "VAEDecode",
                  "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
            "8": {"class_type": "ADE_UpscaleAndSaveAsGif",
                  "inputs": {"filename_prefix": f"studio_{request_id[:8]}",
                             "fps": fps, "images": ["7", 0]}},
        }

        resp = requests.post(
            f"{comfyui_url}/prompt",
            json={"prompt": workflow, "client_id": "cosysim_studio"},
            timeout=30,
        )
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]

        # Poll for the GIF output.
        import time as _time  # noqa: PLC0415
        deadline = _time.monotonic() + 120.0
        while _time.monotonic() < deadline:
            hist = requests.get(f"{comfyui_url}/history/{prompt_id}", timeout=10).json()
            if prompt_id in hist:
                for _nid, node_out in hist[prompt_id].get("outputs", {}).items():
                    gifs = node_out.get("gifs", [])
                    if gifs:
                        g = gifs[0]
                        return (
                            f"{comfyui_url}/view"
                            f"?filename={g['filename']}&subfolder={g.get('subfolder','')}&type=output"
                        )
                    images = node_out.get("images", [])
                    if images:
                        img = images[0]
                        return (
                            f"{comfyui_url}/view"
                            f"?filename={img['filename']}&subfolder={img.get('subfolder','')}&type=output"
                        )
            _time.sleep(2)

        raise TimeoutError(f"AnimateDiff job {prompt_id} did not complete in 120s")
