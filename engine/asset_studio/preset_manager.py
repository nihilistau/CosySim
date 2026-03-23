"""Preset Manager — style presets for consistent asset generation.

A preset bundles style keywords, model settings, and default parameters so
that repeated generation tasks produce visually coherent results.

Built-in presets (8):
    dark_renaissance   — default CosySim dark glamour
    cyberpunk          — neon-soaked digital grime
    fantasy            — high-fantasy painterly
    noir               — black-and-white cinematic
    anime              — flat-colour manga style
    photorealistic     — hyperrealistic photography
    pixel_art          — retro 16-bit sprite style
    minimal            — clean, icon-ready SVG/item style

Users may add custom presets via the Settings tab.  Custom presets are stored
in Nexus under category="studio_preset".
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StylePreset:
    """A named bundle of generation parameters and style keywords.

    Attributes:
        id:            Unique slug identifier.
        name:          Human-readable display name.
        description:   Short description shown in the UI.
        style_tags:    List of positive prompt style keywords.
        negative_tags: List of negative prompt keywords.
        width:         Default image width.
        height:        Default image height.
        steps:         Default KSampler steps.
        cfg_scale:     Default CFG guidance scale.
        checkpoint:    ComfyUI checkpoint to use (empty = system default).
        sampler:       ComfyUI sampler name.
        builtin:       ``True`` for built-in presets; ``False`` for custom.
    """

    id: str
    name: str
    description: str = ""
    style_tags: List[str] = field(default_factory=list)
    negative_tags: List[str] = field(default_factory=list)
    width: int = 512
    height: int = 768
    steps: int = 20
    cfg_scale: float = 7.0
    checkpoint: str = ""
    sampler: str = "euler"
    builtin: bool = True

    def to_dict(self) -> Dict:
        """Serialise to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "StylePreset":
        """Deserialise from a dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            style_tags=data.get("style_tags", []),
            negative_tags=data.get("negative_tags", []),
            width=int(data.get("width", 512)),
            height=int(data.get("height", 768)),
            steps=int(data.get("steps", 20)),
            cfg_scale=float(data.get("cfg_scale", 7.0)),
            checkpoint=data.get("checkpoint", ""),
            sampler=data.get("sampler", "euler"),
            builtin=bool(data.get("builtin", True)),
        )


# ── Built-in presets ──────────────────────────────────────────────────────────

_BUILTIN_PRESETS: List[StylePreset] = [
    StylePreset(
        id="dark_renaissance",
        name="Dark Renaissance",
        description="Default CosySim dark glamour — cinematic, moody, lush",
        style_tags=[
            "digital painting", "highly detailed", "dramatic lighting",
            "dark glamour", "cinematic", "dark background", "rich textures",
        ],
        negative_tags=[
            "bad quality", "blurry", "watermark", "text", "logo",
            "extra limbs", "mutated", "deformed",
        ],
        width=512, height=768, steps=25, cfg_scale=7.5,
    ),
    StylePreset(
        id="cyberpunk",
        name="Cyberpunk",
        description="Neon-soaked digital grime, holographic rain",
        style_tags=[
            "cyberpunk", "neon lights", "rain-slicked streets", "holographic",
            "digital distortion", "ultra-detailed", "cinematic atmosphere",
        ],
        negative_tags=[
            "blurry", "watermark", "text", "bad anatomy", "extra limbs",
        ],
        width=512, height=512, steps=25, cfg_scale=8.0,
    ),
    StylePreset(
        id="fantasy",
        name="High Fantasy",
        description="Painterly high-fantasy with dramatic magic",
        style_tags=[
            "fantasy art", "epic", "painterly", "magical atmosphere",
            "dramatic composition", "artstation", "concept art",
        ],
        negative_tags=[
            "modern", "photorealistic", "watermark", "text", "ugly",
        ],
        width=512, height=768, steps=28, cfg_scale=7.0,
    ),
    StylePreset(
        id="noir",
        name="Noir",
        description="Black-and-white cinematic shadows",
        style_tags=[
            "noir", "black and white", "cinematic", "dramatic shadows",
            "film grain", "high contrast", "1940s", "detective atmosphere",
        ],
        negative_tags=[
            "color", "bright", "cartoon", "watermark", "text",
        ],
        width=512, height=512, steps=20, cfg_scale=7.0,
    ),
    StylePreset(
        id="anime",
        name="Anime",
        description="Flat-colour manga and anime style",
        style_tags=[
            "anime style", "manga", "flat colours", "clean lines",
            "japanese animation", "vibrant", "expressive",
        ],
        negative_tags=[
            "photorealistic", "3d render", "watermark", "text",
            "bad proportions",
        ],
        width=512, height=768, steps=20, cfg_scale=7.0,
    ),
    StylePreset(
        id="photorealistic",
        name="Photorealistic",
        description="Hyperrealistic photography-grade output",
        style_tags=[
            "photorealistic", "RAW photo", "8k", "hyperrealistic",
            "dslr", "sharp focus", "natural lighting",
        ],
        negative_tags=[
            "cartoon", "anime", "painting", "watermark", "text",
            "bad quality", "soft focus",
        ],
        width=512, height=512, steps=30, cfg_scale=7.0,
    ),
    StylePreset(
        id="pixel_art",
        name="Pixel Art",
        description="Retro 16-bit sprite and scene style",
        style_tags=[
            "pixel art", "16-bit", "retro game sprite", "crisp pixels",
            "limited colour palette", "isometric optional",
        ],
        negative_tags=[
            "blurry", "anti-aliased", "photorealistic", "watermark",
        ],
        width=256, height=256, steps=15, cfg_scale=6.0,
    ),
    StylePreset(
        id="minimal",
        name="Minimal",
        description="Clean icon-ready flat design for items and SVG",
        style_tags=[
            "minimal", "flat design", "clean", "icon", "simple shapes",
            "vector style", "white background",
        ],
        negative_tags=[
            "complex", "detailed textures", "photorealistic", "dark",
        ],
        width=512, height=512, steps=15, cfg_scale=6.5,
    ),
]

_PRESET_INDEX: Dict[str, StylePreset] = {p.id: p for p in _BUILTIN_PRESETS}


class PresetManager:
    """Manages built-in and custom style presets.

    Custom presets are persisted in Nexus so they survive restarts.
    """

    def __init__(self) -> None:
        """Initialise, loading any custom presets from Nexus."""
        self._lock = threading.Lock()
        self._presets: Dict[str, StylePreset] = dict(_PRESET_INDEX)
        self._load_custom_from_nexus()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, preset_id: str) -> Optional[StylePreset]:
        """Return a preset by ID, or ``None`` if not found."""
        return self._presets.get(preset_id)

    def get_default(self) -> StylePreset:
        """Return the default preset (dark_renaissance)."""
        return self._presets["dark_renaissance"]

    def list_all(self) -> List[Dict]:
        """Return all presets as a list of dicts, builtins first."""
        with self._lock:
            builtins = [p.to_dict() for p in self._presets.values() if p.builtin]
            customs = [p.to_dict() for p in self._presets.values() if not p.builtin]
        return builtins + customs

    def save_custom(self, preset_data: Dict) -> StylePreset:
        """Save a custom preset and persist it to Nexus.

        Args:
            preset_data: Dict with all preset fields; ``builtin`` is forced to
                ``False``.

        Returns:
            The created/updated :class:`StylePreset`.
        """
        preset_data["builtin"] = False
        preset = StylePreset.from_dict(preset_data)

        with self._lock:
            self._presets[preset.id] = preset

        self._save_custom_to_nexus(preset)
        logger.info("Saved custom preset: %s", preset.id)
        return preset

    def delete_custom(self, preset_id: str) -> bool:
        """Delete a custom preset.  Built-in presets cannot be deleted.

        Args:
            preset_id: Preset ID to delete.

        Returns:
            ``True`` if deleted, ``False`` if not found or builtin.
        """
        with self._lock:
            p = self._presets.get(preset_id)
            if p is None or p.builtin:
                return False
            del self._presets[preset_id]

        self._delete_from_nexus(preset_id)
        return True

    # ── Nexus persistence ─────────────────────────────────────────────────────

    def _load_custom_from_nexus(self) -> None:
        """Load any custom presets previously saved to Nexus."""
        try:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            client = get_nexus_client()
            results = client.search("studio_preset", limit=50)
            for entry in results:
                if entry.get("category") != "studio_preset":
                    continue
                try:
                    data = json.loads(entry.get("content", "{}"))
                    p = StylePreset.from_dict(data)
                    p.builtin = False
                    with self._lock:
                        self._presets[p.id] = p
                except Exception as e:
                    logger.debug("[PresetManager] Failed to parse custom preset (operation=load_custom): %s", e)
        except Exception:
            logger.debug("Could not load custom presets from Nexus", exc_info=True)

    def _save_custom_to_nexus(self, preset: StylePreset) -> None:
        """Persist a custom preset to Nexus."""
        try:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            client = get_nexus_client()
            client.add_entry(
                title=f"studio_preset:{preset.id}",
                content=json.dumps(preset.to_dict()),
                content_type="note",
                category="studio_preset",
            )
        except Exception:
            logger.debug("Could not save preset to Nexus", exc_info=True)

    def _delete_from_nexus(self, preset_id: str) -> None:
        """Remove a custom preset from Nexus (best-effort)."""
        try:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            client = get_nexus_client()
            results = client.search(f"studio_preset:{preset_id}", limit=1)
            for entry in results:
                if entry.get("title") == f"studio_preset:{preset_id}":
                    entry_id = entry.get("id")
                    if entry_id:
                        client.delete_entry(entry_id)
        except Exception:
            logger.debug("Could not delete preset from Nexus", exc_info=True)


# ── Singleton ─────────────────────────────────────────────────────────────────

_preset_manager_instance: Optional[PresetManager] = None
_preset_lock = threading.Lock()


def get_preset_manager() -> PresetManager:
    """Return the process-wide :class:`PresetManager` singleton."""
    global _preset_manager_instance
    if _preset_manager_instance is None:
        with _preset_lock:
            if _preset_manager_instance is None:
                _preset_manager_instance = PresetManager()
    return _preset_manager_instance
