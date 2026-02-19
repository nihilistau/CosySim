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

from engine.skills.skill import skill


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
                pass

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
