"""
Media Generator Service
Handles photo and video generation for characters using ComfyUI.

The ComfyUI base URL is resolved automatically from env vars / config yaml
via :func:`content.simulation.services.comfyui_client.get_comfyui_base_url`
(defaults to ``http://localhost:8188``).
"""

import os
import uuid
import random
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import sys

from engine.paths import ROOT as project_root
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

from content.simulation.services.comfyui_client import ComfyUIClient, PromptBuilder, get_comfyui_client, _get_comfyui_base_url
from engine.assets import AssetManager


def _get_event_chain():
    """Lazy-load EventChain singleton (avoids circular imports)."""
    try:
        from content.simulation.database.events import EventChain
        return EventChain()
    except Exception as e:
        logger.debug("[MediaGenerator] EventChain unavailable (operation=lazy_load): %s", e)
        return None


class MediaGenerator:
    """Generate photos and videos for characters using ComfyUI."""

    def __init__(self, comfyui_url: Optional[str] = None):
        """Create a MediaGenerator, auto-resolving the ComfyUI URL from config when not given."""
        self.comfyui_url = comfyui_url or _get_comfyui_base_url()
        self.client = ComfyUIClient(base_url=comfyui_url)
        self.media_dir = Path(__file__).parent.parent / "media"
        self.image_dir = self.media_dir / "images"
        self.video_dir = self.media_dir / "video"
        self.voice_dir = self.media_dir / "voice"
        for d in [self.image_dir, self.video_dir, self.voice_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.asset_manager = AssetManager()

    def is_available(self) -> bool:
        """Check if ComfyUI is reachable."""
        return self.client.is_available()

    def generate_selfie(
        self,
        character_name: str,
        character_description: str,
        mood: str = "happy",
        setting: str = "casual",
        style: str = "realistic",
        nsfw: bool = False,
        extra_prompt: str = "",
        chain_id: Optional[str] = None,
        scene_id: str = "unknown",
        character_id: Optional[str] = None,
        **gen_kwargs,
    ) -> Optional[str]:
        """
        Generate a selfie image for a character.

        Args:
            character_name: Name of character
            character_description: Physical description string
            mood: Mood/expression (happy, flirty, seductive, shy, etc.)
            setting: Scene setting (casual, bedroom, beach, gym, etc.)
            style: Photo style (unused – kept for API compat)
            nsfw: Allow NSFW content
            extra_prompt: Additional prompt keywords
            **gen_kwargs: ComfyUI params: steps, cfg, sampler_name, scheduler, denoise, width, height

        Returns:
            Path to generated/placeholder image, or None
        """
        path = self.client.generate_character_selfie(
            appearance=character_description,
            mood=mood,
            setting=setting,
            nsfw=nsfw,
            save_dir=str(self.image_dir),
            extra_prompt=extra_prompt,
            **gen_kwargs,
        )

        if path:
            # Register as asset (best-effort)
            try:
                from engine.assets import ImageAsset
                asset = ImageAsset.create(
                    filepath=path,
                    tags=[character_name, mood, setting, "selfie", "generated"],
                )
                self.asset_manager.save(asset)
            except Exception as e:
                logger.debug("[MediaGenerator] Asset registration failed (operation=generate_selfie): %s", e)

            # Log to EventChain
            try:
                ec = _get_event_chain()
                if ec and chain_id:
                    ec.log(
                        'media_generated', actor='media_generator',
                        payload={'type': 'image', 'path': str(path),
                                 'character': character_name, 'mood': mood,
                                 'setting': setting},
                        summary=f'Selfie generated: {character_name} ({mood})',
                        chain_id=chain_id, scene_id=scene_id,
                        character_id=character_id,
                    )
            except Exception as e:
                logger.debug("[MediaGenerator] EventChain log failed (operation=generate_selfie): %s", e)

            # MCP: publish to ActivityBus
            try:
                from engine.services.activity_bus import get_activity_bus
                get_activity_bus().publish(
                    activity_type="media_generated",
                    description=f"Selfie: {character_name} ({mood}@{setting})",
                    agent_id=character_id or "media_generator",
                    scene=scene_id,
                    data={"path": str(path), "mood": mood, "setting": setting, "chain_id": chain_id},
                )
            except Exception as e:
                logger.debug("[MediaGenerator] ActivityBus publish failed (operation=generate_selfie): %s", e)

        return path

    def generate_portrait(
        self,
        character_name: str,
        appearance: str,
        mood: str = "neutral",
        setting: str = "casual",
        nsfw: bool = False,
    ) -> Optional[str]:
        """Generate a portrait / headshot."""
        return self.generate_selfie(character_name, appearance, mood, setting, nsfw=nsfw)

    def get_random_selfie_context(self, relationship_level: float = 0.5) -> Dict:
        """
        Generate random selfie context based on relationship level.

        Args:
            relationship_level: 0.0–1.0

        Returns:
            Dict with keys: mood, setting, nsfw
        """
        rel = float(relationship_level)  # ensure float

        innocent = [
            {"mood": "happy", "setting": "casual", "nsfw": False},
            {"mood": "playful", "setting": "outdoors", "nsfw": False},
            {"mood": "excited", "setting": "beach", "nsfw": False},
            {"mood": "shy", "setting": "morning", "nsfw": False},
            {"mood": "loving", "setting": "cafe", "nsfw": False},
        ]
        flirty = [
            {"mood": "flirty", "setting": "bedroom", "nsfw": False},
            {"mood": "seductive", "setting": "night", "nsfw": False},
            {"mood": "playful", "setting": "gym", "nsfw": False},
            {"mood": "confident", "setting": "casual", "nsfw": False},
        ]
        intimate = [
            {"mood": "seductive", "setting": "bedroom", "nsfw": True},
            {"mood": "playful", "setting": "lingerie", "nsfw": True},
            {"mood": "confident", "setting": "nude", "nsfw": True},
        ]

        if rel > 0.8 and random.random() > 0.6:
            return random.choice(intimate)
        elif rel > 0.5:
            return random.choice(flirty + innocent)
        else:
            return random.choice(innocent)

    def create_thumbnail(self, image_path: str, size: Tuple[int, int] = (200, 200)) -> Optional[str]:
        """Create thumbnail for an image."""
        try:
            from PIL import Image as _PIL
            p = Path(image_path)
            thumb = p.parent / f"{p.stem}_thumb{p.suffix}"
            with _PIL.open(image_path) as img:
                img.thumbnail(size, _PIL.Resampling.LANCZOS)
                img.save(thumb, quality=85)
            return str(thumb)
        except Exception as e:
            logger.debug("Thumbnail creation failed: %s", e)
            return None

    def get_media_info(self, filepath: str) -> Dict:
        """Get metadata about a media file."""
        p = Path(filepath)
        if not p.exists():
            return {"exists": False}
        stat = p.stat()
        return {
            "filename": p.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "type": p.suffix.lower(),
            "exists": True,
        }


if __name__ == "__main__":
    gen = MediaGenerator()
    print("ComfyUI available:", gen.is_available())
    path = gen.generate_selfie(
        character_name="Emma",
        character_description="25 year old woman, long brown hair, green eyes, slim build",
        mood="happy",
        setting="casual",
    )
    if path:
        print(f"✅ Generated: {path}")
    else:
        print("❌ Generation failed (ComfyUI may be offline)")