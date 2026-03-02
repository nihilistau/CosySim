"""
comfyui_skills.py — ComfyUI image generation skills

These skills call the ComfyUI API to generate images.  They are designed to
be passed to ``lmstudio.llm().act()`` so the LLM can autonomously choose to
generate images during a conversation.

All network calls are lazy — if ComfyUI is not running the skill returns an
error string rather than raising an exception, so the LLM can gracefully
handle the failure in its next turn.
"""
from __future__ import annotations

from typing import List, Optional

from engine.skills.skill import skill
import logging

logger = logging.getLogger(__name__)


@skill(
    pack="comfyui",
    description=(
        "Generate an image from a text prompt using ComfyUI. "
        "Returns the URL of the generated image, or an error message."
    ),
    tags=["image", "generation"],
)
def generate_image(
    prompt: str,
    negative_prompt: str = "",
    width: int = 0,
    height: int = 0,
    steps: int = 20,
    cfg_scale: float = 7.0,
    style: str = "realistic",
) -> str:
    """
    Generate an image using ComfyUI and return its URL.

    Args:
        prompt:          Text description of the desired image.
        negative_prompt: Things to exclude from the image.
        width:           Image width (0 = use MediaConfig default).
        height:          Image height (0 = use MediaConfig default).
        steps:           Diffusion steps (higher = better quality, slower).
        cfg_scale:       Prompt guidance strength (7–12 typical).
        style:           Style hint: "realistic", "anime", "portrait", "fantasy".

    Returns:
        URL string on success; error message string on failure.
    """
    try:
        from engine.config import get_config
        from engine.skills.chain_context import get_chain_context
        from content.simulation.services.comfyui_client import ComfyUIClient

        # Read standard dimensions from MediaConfig
        if width == 0 or height == 0:
            try:
                from engine.media.media_config import get_media_config
                width, height = get_media_config().image_dims("selfie")
            except Exception:
                width, height = 512, 768

        ctx      = get_chain_context()
        config   = get_config()
        base_url = config.get("comfyui.base_url", "http://localhost:8188")
        client   = ComfyUIClient(base_url=base_url)

        save_dir = "content/simulation/media/images"
        result_path = client.generate_image(
            positive_prompt=prompt,
            negative_prompt=negative_prompt,
            save_dir=save_dir,
            filename_prefix=f"skill_{style}",
        )

        if result_path:
            from pathlib import Path
            fname = Path(result_path).name

            # Log to EventChain via chain context
            try:
                from content.simulation.database.events import EventChain
                chain_id = ctx.get("chain_id")
                if chain_id:
                    ec = EventChain()
                    ec.log(
                        'media_generated', actor='skill:generate_image',
                        payload={'type': 'image', 'prompt': prompt[:200],
                                 'path': str(result_path)},
                        summary=f'Image generated: {prompt[:60]}',
                        chain_id=chain_id,
                        scene_id=ctx.get("scene_id", "unknown"),
                        character_id=ctx.get("character_id"),
                    )
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)

            return f"/api/media/download/{fname}"
        return "Image generation returned no result. Check ComfyUI output folder."

    except ImportError:
        return "ComfyUI client not available.  Install requirements and check config."
    except Exception as exc:
        return f"Failed to generate image: {exc}"


@skill(
    pack="comfyui",
    description=(
        "Generate a portrait-style headshot for a character using ComfyUI. "
        "Returns the image URL or an error message."
    ),
    tags=["image", "portrait", "character"],
)
def generate_character_portrait(
    character_name: str,
    physical_description: str,
    mood: str = "neutral",
    style: str = "realistic portrait",
) -> str:
    """
    Generate a character portrait image.

    Args:
        character_name:        Name of the character (used in prompt).
        physical_description:  Physical appearance details.
        mood:                  Facial expression / mood hint (e.g. "smiling", "serious").
        style:                 Art style hint (e.g. "realistic portrait", "anime").

    Returns:
        Image URL on success; error message on failure.
    """
    prompt = (
        f"{style} of {character_name}, {physical_description}, "
        f"{mood} expression, high quality, detailed face, soft lighting"
    )
    return generate_image(
        prompt=prompt,
        negative_prompt="blurry, deformed, extra limbs, watermark",
        width=512,
        height=768,
        steps=25,
        cfg_scale=7.5,
        style=style,
    )


@skill(
    pack="comfyui",
    description=(
        "List the ComfyUI workflows available on the server. "
        "Returns a JSON-formatted list of workflow names."
    ),
    tags=["comfyui", "workflows"],
)
def list_comfyui_workflows() -> str:
    """
    Return a list of available ComfyUI workflow names.

    Returns:
        JSON string listing workflow names, or an error message.
    """
    try:
        import json
        from engine.config import get_config
        from content.simulation.services.comfyui_client import ComfyUIClient

        config   = get_config()
        base_url = config.get("comfyui.base_url", "http://localhost:8188")
        client   = ComfyUIClient(base_url=base_url)
        workflows = client.list_workflows() if hasattr(client, 'list_workflows') else []
        return json.dumps(workflows)
    except Exception as exc:
        return f"Could not list workflows: {exc}"


@skill(
    pack="comfyui",
    description=(
        "Generate an image for a specific scene (background, atmosphere, or item) using "
        "ComfyUI and inject it into the scene's static assets.  Returns the static URL "
        "path the scene can use immediately, or an error message."
    ),
    tags=["image", "scene", "background", "generation"],
)
def generate_scene_image(
    scene: str,
    image_type: str = "background",
    prompt: str = "",
    width: int = 1920,
    height: int = 1080,
    steps: int = 6,
    cfg: float = 1.0,
    filename: str = "",
) -> str:
    """Generate and inject an image directly into a scene's static asset folder.

    Args:
        scene:       Target scene name (e.g. 'bedroom', 'casino', 'arena').
        image_type:  Asset category: 'background', 'item', 'atmosphere', 'portrait'.
        prompt:      Image prompt.  If empty, a default is built from scene + type.
        width:       Output width in pixels (default 1920 for backgrounds).
        height:      Output height in pixels (default 1080 for backgrounds).
        steps:       Diffusion steps (default 6 — proven fast-quality balance).
        cfg:         Guidance scale (default 1.0 — proven profile).
        filename:    Output filename stem (default: scene_imagetype_timestamp.png).

    Returns:
        Static URL string (e.g. '/scenes/bedroom/static/img/bg_generated.png')
        on success, or an error message.
    """
    import time
    from pathlib import Path

    try:
        from engine.config import get_config
        from engine.asset_studio.workflow_manager import get_workflow_manager

        config = get_config()

        # Build prompt from scene context if not supplied
        if not prompt:
            scene_prompts = {
                "bedroom":  "luxury penthouse bedroom at night, purple neon ambient lighting, moody atmosphere",
                "casino":   "high-end casino floor, golden chandeliers, roulette tables, noir atmosphere",
                "lounge":   "velvet underground lounge bar, deep red lighting, jazz atmosphere",
                "tavern":   "rustic fantasy tavern interior, warm firelight, wooden beams",
                "gallery":  "modern art gallery, white walls, dramatic spotlights, abstract art",
                "arena":    "gladiatorial arena, stone walls, torches, crowd shadows",
                "realm":    "shattered fantasy throne room, magical energy, fractured stone",
                "neoncity": "cyberpunk neon city street at night, rain, holographic signs",
                "heist":    "corporate vault corridor, red laser grid, security panels",
                "phone":    "signal tower at night, digital interference patterns, cyan glow",
            }
            base = scene_prompts.get(scene, f"{scene} environment, cinematic")
            prompt = f"{base}, {image_type}, high quality, 8k, photorealistic"

        # Resolve output path inside scene's static/img folder
        stem = filename or f"{scene}_{image_type}_{int(time.time())}"
        static_img_dir = Path("content/scenes") / scene / "static" / "img"
        static_img_dir.mkdir(parents=True, exist_ok=True)
        out_path = static_img_dir / f"{stem}.png"

        # Use workflow manager to generate via ComfyUI (portrait_fast profile for speed)
        wm = get_workflow_manager()
        result = wm.generate(
            workflow_name="portrait_hires",
            params={
                "prompt": prompt,
                "negative_prompt": "blurry, watermark, text, deformed, low quality",
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
                "output_prefix": stem,
            },
        )

        if isinstance(result, dict) and result.get("status") == "ok":
            src = result.get("output_path", "")
            if src:
                # Copy/move to scene static folder
                import shutil
                shutil.copy2(src, out_path)
                # Return the Flask static URL
                static_url = f"/scenes/{scene}/static/img/{stem}.png"
                logger.info("generate_scene_image: %s → %s", scene, static_url)
                return static_url

        return f"Image generation queued. Check {out_path} when ComfyUI finishes."

    except Exception as exc:
        logger.debug("generate_scene_image failed: %s", exc)
        return f"Failed to generate scene image: {exc}"


@skill(
    pack="comfyui",
    description=(
        "Batch-generate scene background images for all active scenes and store them "
        "in each scene's static/img folder.  Intended for nightly scheduler use."
    ),
    tags=["image", "scene", "background", "batch"],
    cooldown=3600.0,
)
def generate_all_scene_backgrounds(
    scenes: Optional[List[str]] = None,
    force: bool = False,
) -> str:
    """Generate background images for all active scenes.

    Args:
        scenes:  List of scene names to generate for.  Defaults to all 9 game scenes.
        force:   If True, regenerate even if a background already exists.

    Returns:
        Summary string with counts of generated/skipped scenes.
    """
    from pathlib import Path

    default_scenes = [
        "bedroom", "phone", "lounge", "tavern", "casino",
        "gallery", "arena", "realm", "neoncity",
    ]
    target_scenes: List[str] = scenes or default_scenes

    generated, skipped, errors = 0, 0, 0
    for scene_name in target_scenes:
        bg_path = Path("content/scenes") / scene_name / "static" / "img" / f"{scene_name}_background_latest.png"
        if bg_path.exists() and not force:
            skipped += 1
            continue
        result = generate_scene_image(
            scene=scene_name,
            image_type="background",
            filename=f"{scene_name}_background_latest",
            width=1920,
            height=1080,
        )
        if result.startswith("/") or "static" in result:
            generated += 1
        else:
            errors += 1

    return (
        f"Background generation complete: "
        f"{generated} generated, {skipped} skipped (existing), {errors} errors."
    )
