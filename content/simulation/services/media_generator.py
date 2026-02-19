"""
Media Generator Service
Handles photo and video generation for characters using ComfyUI (192.168.8.150:8188)
"""

import os
import uuid
import random
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

from content.simulation.services.comfyui_client import ComfyUIClient, PromptBuilder, get_comfyui_client
from engine.assets import AssetManager


class MediaGenerator:
    """Generate photos and videos for characters using ComfyUI."""

    def __init__(self, comfyui_url: str = "http://192.168.8.150:8188"):
        self.comfyui_url = comfyui_url
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
            except Exception:
                pass

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
    print("Generated:", path)



class MediaGenerator:
    """Generate photos and videos for characters"""
    
    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188"):
        self.comfyui_url = comfyui_url
        self.workflow_dir = Path(__file__).parent.parent.parent.parent / "workflows"
        self.media_dir = Path(__file__).parent.parent / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.asset_manager = AssetManager()
        
        # Load image generation workflow (if ComfyUI available)
        if COMFYUI_AVAILABLE:
            workflow_path = self.workflow_dir / "generate_Image.json"
            if workflow_path.exists():
                self.image_gen = ImageGenerator(str(workflow_path), comfyui_url)
            else:
                self.image_gen = None
                print(f"⚠️  Image workflow not found at {workflow_path}")
        else:
            self.image_gen = None
            print("ℹ️  ComfyUI not available - using placeholder images")
    
    def generate_selfie(
        self,
        character_name: str,
        character_description: str,
        mood: str = "happy",
        setting: str = "casual",
        style: str = "realistic",
        nsfw: bool = False
    ) -> Optional[str]:
        """
        Generate a selfie for a character
        
        Args:
            character_name: Name of character
            character_description: Physical description (hair, eyes, etc.)
            mood: happy, playful, seductive, shy, etc.
            setting: casual, bedroom, outdoors, gym, etc.
            style: realistic, artistic, cinematic
            nsfw: Whether to generate NSFW content
        
        Returns:
            Path to generated image file
        """
        if not self.image_gen:
            print("Image generator not available")
            return None
        
        # Build prompt based on character and context
        positive_prompt = self._build_selfie_prompt(
            character_description, mood, setting, style, nsfw
        )
        
        negative_prompt = "low quality, blurry, distorted, ugly, deformed, bad anatomy, extra limbs"
        if not nsfw:
            negative_prompt += ", nude, nsfw, explicit, sexual"
        
        # Generate image
        try:
            result = self.image_gen.generate(
                positive_prompt=positive_prompt,
                negative_prompt=negative_prompt
            )
            
            if result and result.get('images'):
                # Save to media directory
                filename = f"{character_name}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = self.media_dir / filename
                
                saved = self.image_gen.save_images(result, output_dir=str(self.media_dir))
                if saved:
                    # Rename to our format
                    os.rename(saved[0], filepath)
                    
                    # Create ImageAsset
                    from PIL import Image
                    img = Image.open(filepath)
                    image_asset = ImageAsset.create(
                        filepath=str(filepath),
                        width=img.width,
                        height=img.height,
                        format="png",
                        tags=[character_name, mood, setting, "selfie", "generated"]
                    )
                    
                    # Save to asset manager
                    self.asset_manager.save(image_asset)
                    
                    return str(filepath)
            
        except Exception as e:
            print(f"Error generating selfie: {e}")
        
        return None
    
    def _build_selfie_prompt(
        self,
        character_desc: str,
        mood: str,
        setting: str,
        style: str,
        nsfw: bool
    ) -> str:
        """Build detailed prompt for selfie generation"""
        
        # Mood descriptors
        mood_map = {
            "happy": "smiling, cheerful expression, bright eyes",
            "playful": "playful smile, mischievous look, fun expression",
            "seductive": "seductive gaze, alluring expression, sultry look",
            "shy": "shy smile, blushing, gentle expression",
            "confident": "confident gaze, strong presence, assured expression",
            "flirty": "flirty smile, teasing expression, inviting look",
            "loving": "warm smile, loving gaze, affectionate expression",
            "excited": "excited expression, wide smile, energetic"
        }
        
        # Setting descriptors
        setting_map = {
            "casual": "casual clothes, indoor lighting, home environment",
            "bedroom": "bedroom setting, soft lighting, intimate atmosphere",
            "outdoors": "outdoor setting, natural lighting, scenic background",
            "gym": "gym clothes, athletic wear, fitness environment",
            "beach": "beach setting, summer vibes, ocean background",
            "night": "night setting, dim lighting, evening atmosphere",
            "morning": "morning light, fresh look, soft natural lighting",
            "selfie": "selfie angle, close-up, phone camera perspective"
        }
        
        # Style descriptors
        style_map = {
            "realistic": "photorealistic, highly detailed, professional photography",
            "artistic": "artistic style, creative composition, aesthetic",
            "cinematic": "cinematic lighting, dramatic, film-like quality",
            "natural": "natural look, authentic, candid photography"
        }
        
        # Build prompt
        prompt_parts = [
            style_map.get(style, "realistic"),
            f"portrait of beautiful woman, {character_desc}",
            mood_map.get(mood, "natural expression"),
            setting_map.get(setting, "casual setting"),
            "high quality, detailed, 8k, masterpiece"
        ]
        
        if nsfw:
            prompt_parts.append("sensual, intimate, adult content")
        
        return ", ".join(prompt_parts)
    
    def get_random_selfie_context(self, relationship_level: float = 0.5) -> Dict:
        """
        Generate random selfie context based on relationship level
        
        Args:
            relationship_level: 0-1, higher = more intimate
        
        Returns:
            Dict with mood, setting, nsfw flag
        """
        # Innocent contexts
        innocent_contexts = [
            {"mood": "happy", "setting": "casual", "nsfw": False},
            {"mood": "playful", "setting": "outdoors", "nsfw": False},
            {"mood": "excited", "setting": "casual", "nsfw": False},
            {"mood": "shy", "setting": "morning", "nsfw": False},
        ]
        
        # Flirty contexts
        flirty_contexts = [
            {"mood": "flirty", "setting": "bedroom", "nsfw": False},
            {"mood": "seductive", "setting": "night", "nsfw": False},
            {"mood": "playful", "setting": "gym", "nsfw": False},
            {"mood": "confident", "setting": "selfie", "nsfw": False},
        ]
        
        # Intimate contexts (higher relationship required)
        intimate_contexts = [
            {"mood": "seductive", "setting": "bedroom", "nsfw": True},
            {"mood": "playful", "setting": "bedroom", "nsfw": True},
            {"mood": "confident", "setting": "night", "nsfw": True},
        ]
        
        # Choose based on relationship level
        if relationship_level > 0.8 and random.random() > 0.7:
            return random.choice(intimate_contexts)
        elif relationship_level > 0.5:
            return random.choice(flirty_contexts + innocent_contexts)
        else:
            return random.choice(innocent_contexts)
    
    def create_thumbnail(self, image_path: str, size: Tuple[int, int] = (200, 200)) -> Optional[str]:
        """Create thumbnail for an image"""
        try:
            from PIL import Image
            
            img_path = Path(image_path)
            thumb_path = img_path.parent / f"{img_path.stem}_thumb{img_path.suffix}"
            
            with Image.open(image_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(thumb_path, quality=85)
            
            return str(thumb_path)
        
        except Exception as e:
            print(f"Error creating thumbnail: {e}")
            return None
    
    def get_media_info(self, filepath: str) -> Dict:
        """Get information about a media file"""
        path = Path(filepath)
        
        if not path.exists():
            return {}
        
        stat = path.stat()
        
        return {
            "filename": path.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "type": path.suffix.lower(),
            "exists": True
        }


# Quick test
if __name__ == "__main__":
    gen = MediaGenerator()
    
    # Test selfie generation
    character_desc = "long brown hair, green eyes, athletic build, 25 years old"
    
    print("Generating happy casual selfie...")
    result = gen.generate_selfie(
        character_name="Emma",
        character_description=character_desc,
        mood="happy",
        setting="casual"
    )
    
    if result:
        print(f"✅ Generated: {result}")
        
        # Create thumbnail
        thumb = gen.create_thumbnail(result)
        if thumb:
            print(f"✅ Thumbnail: {thumb}")
    else:
        print("❌ Generation failed")
