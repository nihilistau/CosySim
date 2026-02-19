"""
Media Generator Service
Handles photo and video generation for characters using ComfyUI
"""

import os
import json
import uuid
import random
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Import ComfyUI generators
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from comfyui_generator import ImageGenerator
from engine.assets import AssetManager, ImageAsset


class MediaGenerator:
    """Generate photos and videos for characters"""
    
    def __init__(self, comfyui_url: str = "http://127.0.0.1:8188"):
        self.comfyui_url = comfyui_url
        self.workflow_dir = Path(__file__).parent.parent.parent / "workflows"
        self.media_dir = Path(__file__).parent.parent / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.asset_manager = AssetManager()
        
        # Load image generation workflow
        workflow_path = self.workflow_dir / "generate_Image.json"
        if workflow_path.exists():
            self.image_gen = ImageGenerator(str(workflow_path), comfyui_url)
        else:
            self.image_gen = None
            print(f"Warning: Image workflow not found at {workflow_path}")
    
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
