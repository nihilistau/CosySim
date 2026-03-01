"""CosySim Scene Art Manager — ComfyUI-backed image generation with Nexus caching.

Manages three art categories for the Dark Renaissance v0.68 release:

* **Character portraits** — per-character, per-mood, per-scene stills generated
  from the character's Nexus profile and cached to avoid redundant API calls.
* **Scene backgrounds** — widescreen establishing shots keyed by scene slug,
  time-of-day, and dramatic mood.
* **Action cards** — one-shot cinematic illustrations for dramatic moments;
  never cached because each description is unique.

Adult content additions are gated by :class:`~engine.content.content_gate.ContentGate`
intensity levels so the system respects per-player content profiles.

Example usage::

    from engine.art.scene_art import get_scene_art_manager

    mgr = get_scene_art_manager()
    result = mgr.get_character_portrait("aria", mood="seductive", scene="bedroom")
    print(result.url)
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

import requests

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Lazy Nexus / ContentGate imports (avoid hard import cycles) ───────────────

def _get_nexus():
    """Return the Nexus singleton (lazy import)."""
    from engine.nexus.client import get_nexus_client  # noqa: PLC0415
    return get_nexus_client()


def _get_content_gate():
    """Return the ContentGate singleton (lazy import)."""
    from engine.content.content_gate import get_content_gate  # noqa: PLC0415
    return get_content_gate()


# ── Scene prompt defaults ─────────────────────────────────────────────────────

_SCENE_PROMPTS: Dict[str, str] = {
    "bedroom":  "luxurious penthouse bedroom, neon city through window, dark glamour",
    "lounge":   "underground lounge bar, velvet seating, amber lighting",
    "tavern":   "rustic fantasy tavern interior, fireplace, medieval",
    "casino":   "noir casino floor, card tables, dramatic shadows",
    "gallery":  "dark art gallery, spotlight on canvas, mysterious",
    "heist":    "rooftop at night, city skyline, criminal planning",
    "realm":    "dark fantasy throne room, shattered stone, candlelight",
    "neoncity": "cyberpunk city street, neon signs, rain, holographic ads",
    "arena":    "colosseum arena, blood sand floor, crowd silhouettes",
    "phone":    "hacker apartment, multiple monitors, green terminal glow",
}

_SCENE_DEFAULT = "dark atmospheric room, cinematic lighting"

# Time-of-day modifiers appended to base scene prompts.
_TIME_SUFFIX: Dict[str, str] = {
    "dawn":      "early morning light, golden haze",
    "morning":   "soft daylight, fresh atmosphere",
    "afternoon": "bright natural lighting, clear shadows",
    "dusk":      "orange and purple sunset glow",
    "night":     "night-time, deep shadows, artificial lighting",
    "midnight":  "midnight darkness, moonlight, stark contrasts",
}

# Mood modifiers blended into all prompts.
_MOOD_SUFFIX: Dict[str, str] = {
    "neutral":   "calm atmosphere",
    "tense":     "tense mood, dramatic tension",
    "romantic":  "romantic atmosphere, soft glow",
    "dangerous": "dangerous, menacing, high-stakes",
    "mysterious": "mysterious, shadowy, unknown",
    "joyful":    "joyful, bright, celebratory",
    "melancholy": "melancholy, somber, wistful",
    "seductive": "seductive, alluring, intimate",
}

# Negative prompt shared across all generation requests.
_DEFAULT_NEGATIVE = "nsfw, bad quality, blurry, watermark, text, logo, extra limbs, mutated"

# ComfyUI base workflow checkpoint.
_CHECKPOINT = "v1-5-pruned-emaonly.ckpt"


# ── Enumerations ──────────────────────────────────────────────────────────────


class ArtStyle(str, Enum):
    """Supported art generation styles."""

    PORTRAIT = "portrait"
    SCENE_BG = "scene_bg"
    ACTION_CARD = "action_card"
    CHARACTER_CARD = "character_card"
    FACTION_BANNER = "faction_banner"


# ── Data-classes ──────────────────────────────────────────────────────────────


@dataclass
class ArtRequest:
    """Parameters for a single ComfyUI generation request.

    Attributes:
        id: Unique request ID (UUID4 hex).
        style: Art category / workflow to use.
        prompt: Positive conditioning text.
        negative_prompt: Negative conditioning text.
        width: Image width in pixels.
        height: Image height in pixels.
        steps: KSampler denoising steps.
        cfg_scale: Classifier-free guidance scale.
        seed: RNG seed; ``-1`` means random.
        scene: Scene slug this art belongs to.
        character_id: Character ID for portrait styles.
        mood: Dramatic mood string.
        intensity: ContentGate intensity level (0-3).
        created_at: ISO-8601 UTC timestamp of request creation.
    """

    id: str
    style: ArtStyle
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 768
    steps: int = 20
    cfg_scale: float = 7.0
    seed: int = -1
    scene: str = ""
    character_id: str = ""
    mood: str = "neutral"
    intensity: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ArtResult:
    """Result of a completed (or cached) art generation request.

    Attributes:
        request_id: Matches the originating ``ArtRequest.id``.
        url: Filesystem path or HTTP URL to the generated image.
        base64_data: Inline base64-encoded image data for small images.
        cached: ``True`` when the result was served from the Nexus cache.
        generation_ms: Wall-clock milliseconds for the generation (0 if cached).
        nexus_key: Cache key used in Nexus storage.
        created_at: ISO-8601 UTC timestamp of result creation.
    """

    request_id: str
    url: str
    base64_data: Optional[str]
    cached: bool
    generation_ms: int
    nexus_key: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        """Serialise to a plain dictionary for Nexus storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ArtResult":
        """Deserialise from a Nexus-stored dictionary."""
        return cls(**data)


# ── Manager ───────────────────────────────────────────────────────────────────


class SceneArtManager:
    """Orchestrates ComfyUI art generation for CosySim scenes and characters.

    All generated results are cached in Nexus under ``category="scene_art"`` to
    avoid redundant API calls to ComfyUI.  Cache entries expire after
    ``art.cache_ttl_hours`` (default 24 h).

    Adult content additions are injected only when the active ContentGate
    profile permits ``["adult:sexual", "intensity:2"]``.
    """

    def __init__(self) -> None:
        """Initialise manager, loading config and lazy references."""
        cfg = get_config()
        self._comfyui_url: str = cfg.get("art.comfyui_url", "http://localhost:8188").rstrip("/")
        self._enabled: bool = bool(cfg.get("art.enabled", True))
        self._cache_ttl_hours: float = float(cfg.get("art.cache_ttl_hours", 24))
        self._adult_enabled: bool = bool(cfg.get("art.adult_enabled", True))
        self._timeout: int = int(cfg.get("art.timeout", 30))

        # Lazily resolved on first use to avoid import-time side effects.
        self._nexus = None
        self._gate = None

    # ── Public helpers ────────────────────────────────────────────────────────

    @property
    def nexus_client(self):
        """Lazily resolved Nexus client."""
        if self._nexus is None:
            self._nexus = _get_nexus()
        return self._nexus

    @property
    def content_gate(self):
        """Lazily resolved ContentGate singleton."""
        if self._gate is None:
            self._gate = _get_content_gate()
        return self._gate

    # ── Public API ────────────────────────────────────────────────────────────

    def get_character_portrait(
        self,
        char_id: str,
        mood: str = "neutral",
        scene: str = "",
    ) -> ArtResult:
        """Return a portrait for *char_id* in *mood*, optionally contextualised to *scene*.

        Results are cached in Nexus.  A cache miss triggers a new ComfyUI
        generation using the character's appearance description from the Nexus
        knowledge base.

        Args:
            char_id: Unique character identifier (e.g. ``"aria"``).
            mood: Dramatic mood string (e.g. ``"seductive"``).
            scene: Scene slug the portrait is used in (empty = global).

        Returns:
            :class:`ArtResult` populated with the image URL and cache metadata.
        """
        cache_key = f"portrait:{char_id}:{mood}:{scene}"

        cached = self._check_cache(cache_key)
        if cached is not None:
            return cached

        # Ask Nexus for the character's appearance to build a precise prompt.
        appearance_reply = self.nexus_client.ask(
            f"Describe {char_id}'s appearance for an AI portrait in {mood} mood"
        )
        appearance: str = ""
        if isinstance(appearance_reply, dict):
            appearance = appearance_reply.get("answer", "") or appearance_reply.get("content", "")
        elif isinstance(appearance_reply, str):
            appearance = appearance_reply

        mood_mod = _MOOD_SUFFIX.get(mood, mood)
        base_prompt = (
            f"portrait of {char_id}, {appearance}, {mood_mod}, "
            f"digital painting, highly detailed, dramatic lighting, dark glamour"
        )
        if scene:
            base_prompt += f", {_SCENE_PROMPTS.get(scene, _SCENE_DEFAULT)}"

        negative = _DEFAULT_NEGATIVE
        if self._is_adult_allowed():
            base_prompt += ", sensual pose, elegant, alluring"
            negative = "bad quality, blurry, watermark, text, extra limbs, mutated"

        req = ArtRequest(
            id=uuid.uuid4().hex,
            style=ArtStyle.PORTRAIT,
            prompt=base_prompt,
            negative_prompt=negative,
            width=512,
            height=768,
            scene=scene,
            character_id=char_id,
            mood=mood,
            intensity=2 if self._is_adult_allowed() else 1,
        )
        result = self._generate(req)
        self._store_cache(cache_key, result)
        return result

    def get_scene_bg(
        self,
        scene: str,
        time_of_day: str = "night",
        mood: str = "neutral",
    ) -> ArtResult:
        """Return a widescreen background image for *scene*.

        Args:
            scene: Scene slug from the scene prompt map (e.g. ``"bedroom"``).
            time_of_day: Time-of-day label (e.g. ``"night"``, ``"dawn"``).
            mood: Dramatic mood (e.g. ``"tense"``).

        Returns:
            :class:`ArtResult` with the background image URL.
        """
        cache_key = f"bg:{scene}:{time_of_day}:{mood}"

        cached = self._check_cache(cache_key)
        if cached is not None:
            return cached

        base = _SCENE_PROMPTS.get(scene, _SCENE_DEFAULT)
        time_mod = _TIME_SUFFIX.get(time_of_day, time_of_day)
        mood_mod = _MOOD_SUFFIX.get(mood, mood)
        prompt = (
            f"{base}, {time_mod}, {mood_mod}, "
            f"cinematic wide angle, photorealistic, ultra detailed, 8k"
        )

        req = ArtRequest(
            id=uuid.uuid4().hex,
            style=ArtStyle.SCENE_BG,
            prompt=prompt,
            negative_prompt=_DEFAULT_NEGATIVE,
            width=1024,
            height=576,
            scene=scene,
            mood=mood,
        )
        result = self._generate(req)
        self._store_cache(cache_key, result)
        return result

    def get_action_card(
        self,
        description: str,
        scene: str = "",
        intensity: int = 1,
    ) -> ArtResult:
        """Generate a one-shot action card illustration for a dramatic moment.

        Action cards are **not** cached because each description is unique.

        Args:
            description: Plain-language description of the dramatic moment.
            scene: Optional scene slug for contextual background elements.
            intensity: ContentGate intensity level for adult additions.

        Returns:
            :class:`ArtResult` with the action card image URL.
        """
        prompt = (
            f"dramatic action scene: {description}, cinematic illustration, "
            f"dynamic composition, high contrast, dark fantasy art"
        )
        if scene:
            prompt += f", {_SCENE_PROMPTS.get(scene, _SCENE_DEFAULT)}"

        negative = _DEFAULT_NEGATIVE
        if intensity >= 2 and self._adult_enabled and self._is_adult_allowed():
            prompt += ", intense, graphic, uncensored, explicit detail"
            negative = "bad quality, blurry, watermark, text, extra limbs, mutated"

        req = ArtRequest(
            id=uuid.uuid4().hex,
            style=ArtStyle.ACTION_CARD,
            prompt=prompt,
            negative_prompt=negative,
            width=512,
            height=512,
            scene=scene,
            intensity=intensity,
        )
        return self._generate(req)

    # ── Generation ────────────────────────────────────────────────────────────

    def _generate(self, request: ArtRequest) -> ArtResult:
        """Submit *request* to ComfyUI and wait for the output image.

        When ``art.enabled`` is ``False``, immediately returns a placeholder
        without contacting ComfyUI.

        Args:
            request: Fully-populated :class:`ArtRequest`.

        Returns:
            :class:`ArtResult` with the image URL.

        Raises:
            requests.RequestException: On network errors (not caught here;
                callers should handle).
        """
        if not self._enabled:
            logger.debug("Art generation disabled — returning placeholder for %s", request.id)
            return ArtResult(
                request_id=request.id,
                url="/static/img/placeholder.png",
                base64_data=None,
                cached=False,
                generation_ms=0,
                nexus_key="",
            )

        seed = request.seed if request.seed >= 0 else random.randint(0, 2**32)

        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": request.steps,
                    "cfg": request.cfg_scale,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": _CHECKPOINT},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": request.width,
                    "height": request.height,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": request.prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": request.negative_prompt or _DEFAULT_NEGATIVE,
                    "clip": ["4", 1],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": f"cosysim_{request.id[:8]}",
                    "images": ["8", 0],
                },
            },
        }

        t_start = time.monotonic()

        # ── Submit prompt ──────────────────────────────────────────────────
        resp = requests.post(
            f"{self._comfyui_url}/prompt",
            json={"prompt": workflow, "client_id": "cosysim"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        prompt_id: str = resp.json()["prompt_id"]

        # ── Poll history ───────────────────────────────────────────────────
        image_path = self._poll_history(prompt_id, request.id)

        generation_ms = int((time.monotonic() - t_start) * 1000)

        return ArtResult(
            request_id=request.id,
            url=image_path,
            base64_data=None,
            cached=False,
            generation_ms=generation_ms,
            nexus_key="",
        )

    def _poll_history(self, prompt_id: str, request_id: str, max_wait: float = 60.0) -> str:
        """Poll ``/history/{prompt_id}`` until the job completes.

        Args:
            prompt_id: The ComfyUI prompt ID returned by ``/prompt``.
            request_id: Original request ID used to build fallback paths.
            max_wait: Maximum seconds to wait before giving up.

        Returns:
            Absolute path or URL to the saved image file.

        Raises:
            TimeoutError: If the job does not complete within *max_wait*.
        """
        deadline = time.monotonic() + max_wait
        poll_interval = 1.0

        while time.monotonic() < deadline:
            hist_resp = requests.get(
                f"{self._comfyui_url}/history/{prompt_id}",
                timeout=self._timeout,
            )
            hist_resp.raise_for_status()
            history = hist_resp.json()

            if prompt_id in history:
                job = history[prompt_id]
                outputs = job.get("outputs", {})

                # Walk all node outputs to find the first image.
                for _node_id, node_out in outputs.items():
                    images = node_out.get("images", [])
                    if images:
                        img = images[0]
                        filename: str = img.get("filename", "")
                        subfolder: str = img.get("subfolder", "")
                        path = (
                            f"{self._comfyui_url}/view"
                            f"?filename={filename}&subfolder={subfolder}&type=output"
                        )
                        return path

                # Job present in history but no images yet → still processing.
                status = job.get("status", {})
                if status.get("status_str") in ("error", "failed"):
                    logger.error("ComfyUI job %s failed: %s", prompt_id, status)
                    return f"/static/img/error_{request_id[:8]}.png"

            time.sleep(poll_interval)

        raise TimeoutError(
            f"ComfyUI job {prompt_id} did not complete within {max_wait}s"
        )

    # ── Nexus cache ───────────────────────────────────────────────────────────

    def _cache_title(self, cache_key: str) -> str:
        """Return the Nexus entry title for *cache_key*."""
        return f"art:{cache_key}"

    def _check_cache(self, cache_key: str) -> Optional[ArtResult]:
        """Search Nexus for a valid cached :class:`ArtResult`.

        Args:
            cache_key: Opaque string key for the art item.

        Returns:
            A decoded :class:`ArtResult` if the entry exists and has not
            expired, otherwise ``None``.
        """
        title = self._cache_title(cache_key)
        try:
            results = self.nexus_client.search(title, limit=1)
        except Exception:
            logger.warning("Nexus cache lookup failed for %s", cache_key, exc_info=True)
            return None

        if not results:
            return None

        entry = results[0]
        # Verify the title matches exactly (search may return fuzzy results).
        if entry.get("title") != title:
            return None

        content_raw = entry.get("content", "")
        try:
            data: Dict = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            return None

        # TTL check against the result's own created_at timestamp.
        created_str: str = data.get("created_at", "")
        if created_str and self._cache_ttl_hours > 0:
            try:
                created_dt = datetime.fromisoformat(created_str)
                # Ensure timezone-aware comparison.
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age_hours = (
                    datetime.now(timezone.utc) - created_dt
                ).total_seconds() / 3600
                if age_hours > self._cache_ttl_hours:
                    logger.debug("Cache expired for %s (age=%.1fh)", cache_key, age_hours)
                    return None
            except (ValueError, OverflowError):
                pass  # Malformed timestamp — treat as valid to avoid crash.

        try:
            result = ArtResult.from_dict(data)
            result.cached = True
            return result
        except (TypeError, KeyError):
            return None

    def _store_cache(self, cache_key: str, result: ArtResult) -> None:
        """Persist *result* in the Nexus cache under *cache_key*.

        Args:
            cache_key: Opaque string key for the art item.
            result: The :class:`ArtResult` to persist.
        """
        title = self._cache_title(cache_key)
        result.nexus_key = cache_key
        content = json.dumps(result.to_dict())
        try:
            self.nexus_client.add_entry(
                title=title,
                content=content,
                content_type="memory",
                category="scene_art",
            )
        except Exception:
            logger.warning("Failed to store art cache for %s", cache_key, exc_info=True)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_adult_allowed(self) -> bool:
        """Return ``True`` when adult content is both config-enabled and permitted by ContentGate."""
        if not self._adult_enabled:
            return False
        try:
            return self.content_gate.can_show(["adult:sexual", "intensity:2"])
        except Exception:
            logger.warning("ContentGate check failed; defaulting to adult=False", exc_info=True)
            return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager_instance: Optional[SceneArtManager] = None
_manager_lock = threading.Lock()


def get_scene_art_manager() -> SceneArtManager:
    """Return the process-wide :class:`SceneArtManager` singleton.

    Thread-safe; creates the instance on first call.

    Returns:
        The singleton :class:`SceneArtManager`.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SceneArtManager()
    return _manager_instance
