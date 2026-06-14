"""
ComfyUI Client – HTTP API wrapper for ComfyUI image/video generation.

The server URL is read from config (``comfyui.base_url``) so it never needs
to be hardcoded.  Set ``COSYSIM_COMFYUI_URL`` env var or edit
``config/default.yaml`` to point at your ComfyUI instance.
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

from engine.paths import ROOT as project_root

try:
    from engine.logging import timed
except ImportError:
    def timed(name):
        """Fallback no-op if engine.logging not available."""
        def decorator(fn):
            return fn
        return decorator
sys.path.insert(0, str(project_root))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  ComfyUI default server — read from config, NOT hardcoded
# ─────────────────────────────────────────────────────────────────────────────

def _get_comfyui_base_url() -> str:
    """Return the ComfyUI base URL from config or the COSYSIM_COMFYUI_URL env var."""
    import os
    env_url = os.environ.get("COSYSIM_COMFYUI_URL") or os.environ.get("COMFYUI_URL")
    if env_url:
        return env_url.rstrip("/")
    try:
        from engine.config import get_config
        url = get_config().get("comfyui.base_url", "")
        # Ensure we have a valid string, not None
        if url:
            return url.rstrip("/")
        from engine.port_registry import get_service_url
        return get_service_url("comfyui")
    except Exception as e:
        logger.debug("[ComfyUIClient] Config unavailable, using default URL (operation=init): %s", e)
        from engine.port_registry import get_service_url
        return get_service_url("comfyui")


COMFYUI_BASE_URL = _get_comfyui_base_url()


# ─────────────────────────────────────────────────────────────────────────────
#  Prompt builders
# ─────────────────────────────────────────────────────────────────────────────

class PromptBuilder:
    """Builds consistent prompts for character image/video generation.

    Escalation tiers control content intensity:
      0 — innocent (casual clothing, natural pose)
      1 — suggestive (tight/low-cut, inviting pose, bedroom eyes)
      2 — lingerie (boudoir, underwear, intimate setting)
      3 — nude (artistic nude, tasteful nudity)
      4 — explicit (explicit nude, sexual pose — nsfw_enabled only)
    """

    # Quality anchors
    QUALITY_PREFIX = "masterpiece, best quality, realistic, photorealistic, 8k uhd, high detail, professional photography"
    QUALITY_SUFFIX = "sharp focus, detailed skin texture, natural lighting"

    NEGATIVE_BASE = (
        "lowres, bad anatomy, bad hands, text, error, "
        "missing fingers, extra digit, fewer digits, cropped, worst quality, "
        "low quality, normal quality, jpeg artifacts, signature, watermark, "
        "username, blurry, artist name, deformed, ugly, mutilated"
    )
    NEGATIVE_SAFE = "nsfw, nude, explicit, " + NEGATIVE_BASE
    NEGATIVE_NSFW = (
        NEGATIVE_BASE + ", child, minor, underage, "
        "grotesque, gore, scat, extreme"
    )

    MOOD_MAP = {
        "happy": "bright smile, cheerful expression, happy eyes",
        "playful": "playful grin, mischievous smile, sparkling eyes",
        "flirty": "flirty smile, seductive gaze, inviting look, smirk",
        "seductive": "seductive gaze, sultry expression, alluring, bedroom eyes",
        "aroused": "flushed cheeks, parted lips, heavy-lidded eyes, sensual gaze",
        "passionate": "intense gaze, flushed skin, passionate expression, biting lip",
        "teasing": "teasing smirk, playful wink, coy expression, tilted head",
        "needy": "vulnerable expression, pleading eyes, soft pout, yearning look",
        "confident": "confident expression, strong gaze, self-assured smile, power pose",
        "shy": "shy smile, blushing, looking down slightly, soft expression",
        "excited": "excited expression, wide smile, energetic, vibrant",
        "loving": "warm loving smile, soft gaze, affectionate, tender",
        "mysterious": "confident mysterious gaze, subtle smile, intense eyes",
        "vulnerable": "soft vulnerable expression, doe eyes, gentle, exposed",
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
        "bath": "luxurious bathroom, steam, candlelight, bubble bath",
        "shower": "shower setting, wet skin, steam, glass, water droplets",
        "pool": "poolside, sparkling water, sun-kissed skin, summer vibes",
        "couch": "cozy couch, blanket, living room, relaxed setting",
        "kitchen": "modern kitchen, morning coffee, casual domestic setting",
        "balcony": "balcony at night, city skyline, moonlight, wine glass",
        "hotel_room": "luxury hotel room, king bed, ambient lighting, elegant",
        "mirror": "mirror selfie, bathroom mirror, phone in hand, reflection",
    }

    # ── Escalation tier prompt fragments ────────────────────────────────
    TIER_PROMPTS = {
        0: {  # Innocent
            "clothing": "casual everyday clothing, dressed modestly",
            "pose": "natural relaxed pose, standing or sitting casually",
            "extra": "",
        },
        1: {  # Suggestive
            "clothing": "tight fitting clothes, low-cut top, showing curves",
            "pose": "inviting pose, hand on hip, looking over shoulder, confident stance",
            "extra": "attractive, alluring, body-conscious outfit",
        },
        2: {  # Lingerie
            "clothing": "elegant lingerie, lace bra, silk underwear, stockings",
            "pose": "boudoir pose, lying on bed, kneeling, sensual body language",
            "extra": "intimate, boudoir photography, soft pink lighting, sensual",
        },
        3: {  # Nude (artistic)
            "clothing": "nude, artistic nudity, tasteful, implied nudity, covering with hands or sheets",
            "pose": "artistic nude pose, elegant, body curves, tasteful composition",
            "extra": "fine art nude, natural beauty, soft lighting, sensual",
        },
        4: {  # Explicit
            "clothing": "fully nude, naked, no clothing, exposed",
            "pose": "provocative pose, sexual, explicit, spread, inviting",
            "extra": "explicit, sexual, erotic photography, uncensored",
        },
    }

    @staticmethod
    def build_character_seed(appearance: str) -> str:
        """Create a stable appearance anchor string."""
        h = hashlib.md5(appearance.encode()).hexdigest()[:6]
        return f"consistent character, same person, {appearance}"

    @classmethod
    def character_description(
        cls,
        age: int = 25,
        gender: str = "woman",
        ethnicity: str = "",
        hair_color: str = "",
        hair_style: str = "",
        eye_color: str = "",
        body_type: str = "",
        features: str = "",
    ) -> str:
        """Build a structured visual description string for prompt injection.

        Example output: ``"22 year old blonde woman, long wavy hair, blue eyes,
        slim athletic build, freckles"``
        """
        parts = [f"{age} year old"]
        if ethnicity:
            parts.append(ethnicity)
        parts.append(gender)
        if hair_color or hair_style:
            hair = " ".join(filter(None, [hair_color, hair_style, "hair"]))
            parts.append(hair)
        if eye_color:
            parts.append(f"{eye_color} eyes")
        if body_type:
            parts.append(f"{body_type} build")
        if features:
            parts.append(features)
        return ", ".join(parts)

    @classmethod
    def selfie(
        cls,
        appearance: str,
        mood: str = "happy",
        setting: str = "casual",
        nsfw: bool = False,
        extra: str = "",
        tier: int = 0,
    ) -> Tuple[str, str]:
        """Build (positive_prompt, negative_prompt) for a character selfie.

        Args:
            appearance: Character visual description.
            mood: Mood key from MOOD_MAP.
            setting: Setting key from SETTING_MAP.
            nsfw: Master NSFW toggle.
            extra: Additional prompt text appended at end.
            tier: Escalation tier 0–4 (higher = more explicit).
        """
        mood_desc = cls.MOOD_MAP.get(mood, cls.MOOD_MAP["neutral"])
        setting_desc = cls.SETTING_MAP.get(setting, cls.SETTING_MAP["casual"])
        char_anchor = cls.build_character_seed(appearance)

        # Clamp tier: without nsfw, max is 1
        effective_tier = min(tier, 1) if not nsfw else min(tier, 4)
        tier_data = cls.TIER_PROMPTS.get(effective_tier, cls.TIER_PROMPTS[0])

        positive = (
            f"{cls.QUALITY_PREFIX}, "
            f"portrait of a beautiful {appearance}, {char_anchor}, "
            f"{mood_desc}, {setting_desc}, "
            f"{tier_data['clothing']}, {tier_data['pose']}, "
            f"selfie perspective, close up, face visible"
        )
        if tier_data["extra"]:
            positive += f", {tier_data['extra']}"
        if extra:
            positive += f", {extra}"
        positive += f", {cls.QUALITY_SUFFIX}"

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

def _default_image_workflow(
    positive: str,
    negative: str,
    seed: int = -1,
    model: str = "v1-5-pruned-emaonly.ckpt",
    steps: int = 30,
    cfg: float = 7.0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    denoise: float = 1.0,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict:
    """
    Minimal ComfyUI workflow (API format) for image generation.
    All sampler params are overridable; reads resolution from MediaConfig when not given.
    """
    if seed == -1:
        seed = int(uuid.uuid4().int % (2**31))

    # Resolve dimensions: explicit > MediaConfig > model-based auto
    if width is None or height is None:
        try:
            from engine.media.media_config import get_media_config
            width, height = get_media_config().image_dims("selfie")
        except Exception as e:
            logger.debug("[ComfyUIClient] MediaConfig unavailable, using model-based defaults (operation=build_workflow): %s", e)
            _xl_keywords = ("xl", "sdxl", "pony", "flux", "juggernaut")
            is_xl = any(k in model.lower() for k in _xl_keywords)
            width, height = (1024, 1024) if is_xl else (512, 768)

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": cfg,
                "denoise": denoise,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "seed": seed,
                "steps": steps
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
        # Handle None case for base_url
        if base_url is None:
            from engine.port_registry import get_service_url
            base_url = get_service_url("comfyui")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self._model_name: Optional[str] = None

    _force_model: Optional[str] = None  # class-level override set by control panel

    def _get_model_name(self) -> str:
        """Return best available checkpoint for image generation.

        Prefers realistic/photo models, skips known video-only models.
        Class-level _force_model overrides all heuristics.
        """
        if ComfyUIClient._force_model:
            return ComfyUIClient._force_model
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
        except Exception as e:
            logger.debug("[ComfyUIClient] Health check failed (operation=is_available): %s", e)
            return False

    def get_models(self) -> List[str]:
        """List checkpoint models available on the ComfyUI server."""
        try:
            r = requests.get(f"{self.base_url}/object_info/CheckpointLoaderSimple", timeout=10)
            if r.ok:
                data = r.json()
                return data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        except Exception as e:
            logger.debug("[ComfyUIClient] Failed to list models (operation=get_models): %s", e)
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
            except Exception as e:
                logger.debug("[ComfyUIClient] Poll attempt failed (operation=wait_for_prompt): %s", e)
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

    @timed("comfyui.generate_image")
    def generate_image(
        self,
        positive_prompt: str,
        negative_prompt: str = "",
        save_dir: Optional[str] = None,
        filename_prefix: str = "cosysim",
        workflow: Optional[Dict] = None,
        seed: int = -1,
        steps: int = 30,
        cfg: float = 7.0,
        sampler_name: str = "euler",
        scheduler: str = "normal",
        denoise: float = 1.0,
        width: Optional[int] = None,
        height: Optional[int] = None,
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
            steps: Sampling steps (default 30)
            cfg: CFG scale (default 7.0)
            sampler_name: Sampler algorithm (euler, dpmpp_2m, etc.)
            scheduler: Scheduler type (normal, karras, exponential, etc.)
            denoise: Denoising strength 0.0-1.0
            width: Image width (None = auto from MediaConfig)
            height: Image height (None = auto from MediaConfig)

        Returns:
            Absolute path to saved image, or None on failure
        """
        if not REQUESTS_AVAILABLE:
            logger.warning("requests not available – returning placeholder")
            return self._create_placeholder_image(save_dir, filename_prefix)

        if not self.is_available():
            logger.warning("ComfyUI not reachable at %s – using placeholder", self.base_url)
            return self._create_placeholder_image(save_dir, filename_prefix)

        # Use provided workflow or build default with all params
        if workflow is None:
            workflow = _default_image_workflow(
                positive_prompt, negative_prompt, seed,
                model=self._get_model_name(),
                steps=steps, cfg=cfg,
                sampler_name=sampler_name, scheduler=scheduler,
                denoise=denoise, width=width, height=height,
            )

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

    @timed("comfyui.generate_selfie")
    def generate_character_selfie(
        self,
        appearance: str,
        mood: str = "happy",
        setting: str = "casual",
        nsfw: bool = False,
        save_dir: Optional[str] = None,
        extra_prompt: str = "",
        **gen_kwargs,
    ) -> Optional[str]:
        """High-level helper for character selfie generation.

        Extra kwargs (steps, cfg, sampler_name, scheduler, denoise, width, height)
        are forwarded to generate_image.
        """
        positive, negative = PromptBuilder.selfie(
            appearance=appearance,
            mood=mood,
            setting=setting,
            nsfw=nsfw,
            extra=extra_prompt,
        )
        prefix = f"selfie_{mood}"
        return self.generate_image(
            positive, negative, save_dir=save_dir, filename_prefix=prefix,
            **gen_kwargs,
        )

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
