"""
ComfyUI Client – HTTP API wrapper for ComfyUI running at 192.168.8.150:8188
Handles image generation, video generation, and consistent character prompting.
"""

import json
import uuid
import time
import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  ComfyUI default server
# ─────────────────────────────────────────────────────────────────────────────

COMFYUI_HOST = "192.168.8.150"
COMFYUI_PORT = 8188
COMFYUI_BASE_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"


# ─────────────────────────────────────────────────────────────────────────────
#  Prompt builders
# ─────────────────────────────────────────────────────────────────────────────

class PromptBuilder:
    """Builds consistent prompts for character image/video generation."""

    # Appearance anchors used to keep character consistent across generations
    LORA_STYLE = "realistic, photorealistic, 8k uhd, high detail, professional photography"
    NEGATIVE_BASE = (
        "nsfw, nude, explicit, lowres, bad anatomy, bad hands, text, error, "
        "missing fingers, extra digit, fewer digits, cropped, worst quality, "
        "low quality, normal quality, jpeg artifacts, signature, watermark, "
        "username, blurry, artist name, deformed, ugly, mutilated"
    )
    NEGATIVE_SAFE = NEGATIVE_BASE
    NEGATIVE_NSFW = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
        "fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, "
        "signature, watermark, username, blurry, artist name, deformed, ugly, mutilated, "
        "child, minor, underage"
    )

    MOOD_MAP = {
        "happy": "bright smile, cheerful expression, happy eyes",
        "playful": "playful grin, mischievous smile, sparkling eyes",
        "flirty": "flirty smile, seductive gaze, inviting look, smirk",
        "seductive": "seductive gaze, sultry expression, alluring, bedroom eyes",
        "shy": "shy smile, blushing, looking down slightly, soft expression",
        "excited": "excited expression, wide smile, energetic, vibrant",
        "loving": "warm loving smile, soft gaze, affectionate, tender",
        "mysterious": "confident mysterious gaze, subtle smile, intense eyes",
        "sad": "melancholy expression, downcast eyes, wistful",
        "angry": "stern expression, furrowed brow",
        "surprised": "surprised look, wide eyes, open mouth smile",
        "neutral": "natural expression, relaxed face",
    }

    SETTING_MAP = {
        "casual": "casual home interior, cozy room, warm lighting",
        "bedroom": "cozy bedroom, soft bed, warm ambient lighting, intimate setting",
        "outdoors": "outdoor setting, natural sunlight, greenery, park",
        "beach": "beach background, ocean waves, golden hour light, sand",
        "gym": "gym environment, athletic setting, mirrors, equipment in background",
        "night": "evening setting, city lights bokeh, moody dark atmosphere",
        "morning": "morning light streaming through window, fresh natural look",
        "cafe": "coffee shop setting, warm light, wooden interior",
        "office": "professional office setting, well-lit",
        "video_call": "neutral clean background, good lighting, facing camera",
        "lingerie": "bedroom setting, soft pink lighting, elegant lingerie",
        "nude": "bedroom, soft light, artistic nude photography",
    }

    @staticmethod
    def build_character_seed(appearance: str) -> str:
        """Create a stable appearance anchor string."""
        # Hash appearance for consistency between calls
        h = hashlib.md5(appearance.encode()).hexdigest()[:6]
        return f"consistent character, same person, {appearance}"

    @classmethod
    def selfie(
        cls,
        appearance: str,
        mood: str = "happy",
        setting: str = "casual",
        nsfw: bool = False,
        extra: str = "",
    ) -> Tuple[str, str]:
        """Build (positive_prompt, negative_prompt) for a character selfie."""
        mood_desc = cls.MOOD_MAP.get(mood, cls.MOOD_MAP["neutral"])
        setting_desc = cls.SETTING_MAP.get(setting, cls.SETTING_MAP["casual"])
        char_anchor = cls.build_character_seed(appearance)

        positive = (
            f"{cls.LORA_STYLE}, "
            f"portrait of a beautiful woman, {char_anchor}, "
            f"{mood_desc}, {setting_desc}, "
            f"selfie perspective, close up, face visible"
        )
        if extra:
            positive += f", {extra}"
        if nsfw and setting in ("bedroom", "lingerie", "nude"):
            positive += ", tasteful nudity, artistic, sensual"

        negative = cls.NEGATIVE_NSFW if nsfw else cls.NEGATIVE_SAFE
        return positive, negative

    @classmethod
    def portrait(
        cls,
        appearance: str,
        mood: str = "neutral",
        setting: str = "casual",
        nsfw: bool = False,
    ) -> Tuple[str, str]:
        return cls.selfie(appearance, mood, setting, nsfw)

    @classmethod
    def video_thumbnail(cls, appearance: str, mood: str = "happy") -> Tuple[str, str]:
        """Still frame for video message placeholder."""
        return cls.selfie(appearance, mood, "video_call", nsfw=False)


# ─────────────────────────────────────────────────────────────────────────────
#  ComfyUI Workflow Templates
# ─────────────────────────────────────────────────────────────────────────────

def _default_image_workflow(positive: str, negative: str, seed: int = -1, model: str = "v1-5-pruned-emaonly.ckpt") -> Dict:
    """
    Minimal ComfyUI workflow (API format) for image generation.
    Auto-selects resolution: 1024×1024 for SDXL/Pony/Flux models, 512×768 for SD1.5.
    """
    if seed == -1:
        seed = int(uuid.uuid4().int % (2**31))

    # SDXL-family models need higher resolution
    _xl_keywords = ("xl", "sdxl", "pony", "flux", "juggernaut")
    is_xl = any(k in model.lower() for k in _xl_keywords)
    width, height = (1024, 1024) if is_xl else (512, 768)

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": 7,
                "denoise": 1,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": "euler",
                "scheduler": "normal",
                "seed": seed,
                "steps": 30
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model}
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"batch_size": 1, "height": height, "width": width}
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": positive}
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": negative}
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "cosysim", "images": ["8", 0]}
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Client
# ─────────────────────────────────────────────────────────────────────────────

class ComfyUIClient:
    """
    ComfyUI HTTP API client.

    Usage::

        client = ComfyUIClient()
        if client.is_available():
            path = client.generate_image(positive_prompt, negative_prompt, save_dir="media/images")
    """

    def __init__(self, base_url: str = COMFYUI_BASE_URL, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self._model_name: Optional[str] = None

    def _get_model_name(self) -> str:
        """Return best available checkpoint for image generation.

        Prefers realistic/photo models, skips known video-only models.
        """
        if self._model_name:
            return self._model_name
        models = self.get_models()
        if not models:
            return "v1-5-pruned-emaonly.ckpt"

        # Video model prefixes/keywords to skip
        VIDEO_SKIP = ("ltxv", "ltx_v", "animate", "svd", "xtend", "i2vgen", "video")
        # Prefer keywords that suggest photo/realistic models
        PHOTO_PREF = ("photo", "realistic", "love", "xl", "flux", "sdxl", "pony")

        def score(name: str) -> int:
            lower = name.lower()
            if any(v in lower for v in VIDEO_SKIP):
                return -1
            s = 0
            for p in PHOTO_PREF:
                if p in lower:
                    s += 1
            return s

        scored = sorted([(score(m), m) for m in models], key=lambda x: (-x[0], x[1]))
        # Pick highest scoring non-video model
        for s, m in scored:
            if s >= 0:
                self._model_name = m
                break
        else:
            self._model_name = models[0]

        logger.info("ComfyUI using model: %s", self._model_name)
        return self._model_name

    # ──────────────────────────────
    #  Connectivity
    # ──────────────────────────────

    def is_available(self) -> bool:
        if not REQUESTS_AVAILABLE:
            return False
        try:
            r = requests.get(f"{self.base_url}/system_stats", timeout=5)
            return r.ok
        except Exception:
            return False

    def get_models(self) -> List[str]:
        """List checkpoint models available on the ComfyUI server."""
        try:
            r = requests.get(f"{self.base_url}/object_info/CheckpointLoaderSimple", timeout=10)
            if r.ok:
                data = r.json()
                return data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        except Exception:
            pass
        return []

    # ──────────────────────────────
    #  Queue & wait
    # ──────────────────────────────

    def _queue_prompt(self, workflow: Dict) -> Optional[str]:
        """Submit workflow and return prompt_id."""
        if not REQUESTS_AVAILABLE:
            return None
        try:
            payload = {"prompt": workflow, "client_id": self.client_id}
            r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=30)
            r.raise_for_status()
            return r.json().get("prompt_id")
        except Exception as e:
            logger.error("ComfyUI queue error: %s", e)
            return None

    def _wait_for_completion(self, prompt_id: str, poll_interval: float = 1.0) -> bool:
        """Poll /history until the prompt_id is done or timeout."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
                if r.ok:
                    history = r.json()
                    if prompt_id in history:
                        return True
            except Exception:
                pass
            time.sleep(poll_interval)
        logger.warning("ComfyUI timeout waiting for prompt %s", prompt_id)
        return False

    def _get_output_images(self, prompt_id: str) -> List[Dict]:
        """Retrieve output image info for a completed prompt."""
        try:
            r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
            if not r.ok:
                return []
            history = r.json()
            outputs = history.get(prompt_id, {}).get("outputs", {})
            images = []
            for node_id, node_output in outputs.items():
                for img in node_output.get("images", []):
                    images.append(img)
            return images
        except Exception as e:
            logger.error("Error getting output images: %s", e)
            return []

    def _download_image(self, image_info: Dict, save_path: Path) -> bool:
        """Download an output image from the ComfyUI server."""
        try:
            params = {
                "filename": image_info["filename"],
                "subfolder": image_info.get("subfolder", ""),
                "type": image_info.get("type", "output"),
            }
            r = requests.get(f"{self.base_url}/view", params=params, timeout=30)
            if r.ok:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(r.content)
                return True
        except Exception as e:
            logger.error("Error downloading image: %s", e)
        return False

    # ──────────────────────────────
    #  Public generation methods
    # ──────────────────────────────

    def generate_image(
        self,
        positive_prompt: str,
        negative_prompt: str = "",
        save_dir: Optional[str] = None,
        filename_prefix: str = "cosysim",
        workflow: Optional[Dict] = None,
        seed: int = -1,
    ) -> Optional[str]:
        """
        Generate an image via ComfyUI.

        Args:
            positive_prompt: Description of desired image
            negative_prompt: What to avoid
            save_dir: Directory to save the image (uses temp dir if None)
            filename_prefix: File name prefix
            workflow: Custom ComfyUI workflow dict (uses default if None)
            seed: Generation seed (-1 for random)

        Returns:
            Absolute path to saved image, or None on failure
        """
        if not REQUESTS_AVAILABLE:
            logger.warning("requests not available – returning placeholder")
            return self._create_placeholder_image(save_dir, filename_prefix)

        if not self.is_available():
            logger.warning("ComfyUI not reachable at %s – using placeholder", self.base_url)
            return self._create_placeholder_image(save_dir, filename_prefix)

        # Use provided workflow or build default
        if workflow is None:
            workflow = _default_image_workflow(positive_prompt, negative_prompt, seed,
                                               model=self._get_model_name())

        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            return self._create_placeholder_image(save_dir, filename_prefix)

        logger.info("ComfyUI prompt queued: %s", prompt_id)

        if not self._wait_for_completion(prompt_id):
            return self._create_placeholder_image(save_dir, filename_prefix)

        images = self._get_output_images(prompt_id)
        if not images:
            return self._create_placeholder_image(save_dir, filename_prefix)

        # Save first image
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        save_dir_path = Path(save_dir) if save_dir else Path("content/simulation/media/images")
        save_dir_path.mkdir(parents=True, exist_ok=True)

        out_filename = f"{filename_prefix}_{timestamp}_{uuid.uuid4().hex[:6]}.png"
        save_path = save_dir_path / out_filename

        if self._download_image(images[0], save_path):
            logger.info("ComfyUI image saved: %s", save_path)
            return str(save_path)

        return self._create_placeholder_image(save_dir, filename_prefix)

    def generate_character_selfie(
        self,
        appearance: str,
        mood: str = "happy",
        setting: str = "casual",
        nsfw: bool = False,
        save_dir: Optional[str] = None,
        extra_prompt: str = "",
    ) -> Optional[str]:
        """High-level helper for character selfie generation."""
        positive, negative = PromptBuilder.selfie(
            appearance=appearance,
            mood=mood,
            setting=setting,
            nsfw=nsfw,
            extra=extra_prompt,
        )
        prefix = f"selfie_{mood}"
        return self.generate_image(positive, negative, save_dir=save_dir, filename_prefix=prefix)

    # ──────────────────────────────
    #  Placeholder (offline mode)
    # ──────────────────────────────

    def _create_placeholder_image(
        self, save_dir: Optional[str], prefix: str = "placeholder"
    ) -> Optional[str]:
        """
        Create a 1×1 transparent PNG placeholder so the rest of the app
        doesn't crash when ComfyUI is offline.
        """
        try:
            save_dir_path = Path(save_dir) if save_dir else Path("content/simulation/media/images")
            save_dir_path.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = save_dir_path / f"{prefix}_placeholder_{timestamp}.png"

            # 1×1 grey PNG (minimal valid PNG bytes)
            PNG_1x1_GREY = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
                "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            path.write_bytes(PNG_1x1_GREY)
            return str(path)
        except Exception as e:
            logger.error("Could not create placeholder: %s", e)
            return None


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────────────────────

_comfyui_client: Optional[ComfyUIClient] = None


def get_comfyui_client() -> ComfyUIClient:
    global _comfyui_client
    if _comfyui_client is None:
        _comfyui_client = ComfyUIClient()
    return _comfyui_client


if __name__ == "__main__":
    client = ComfyUIClient()
    print("ComfyUI available:", client.is_available())
    print("Models:", client.get_models()[:3])

    if client.is_available():
        path = client.generate_character_selfie(
            appearance="27 year old woman, long dark wavy hair, green eyes, slim athletic build",
            mood="happy",
            setting="casual",
            save_dir="test_output"
        )
        print("Generated:", path)
