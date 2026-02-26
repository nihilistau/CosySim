"""
Centralised media dimension / format standards for CosySim.

Every service that produces images, video, or audio MUST read its
target dimensions from :func:`get_media_config` rather than hardcoding
values.  The singleton reads from ``config/default.yaml`` →
``media_standards`` and exposes typed helpers so callers never have to
parse YAML themselves.

Usage::

    from engine.media.media_config import get_media_config
    mc = get_media_config()
    w, h = mc.image_dims("selfie")          # (512, 768)
    spec  = mc.video_spec("message")         # {"width":640,"height":480,...}
    sr    = mc.audio_spec("voice_message")   # {"sample_rate":22050,...}
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: "MediaConfig | None" = None


# ── Default values (used when config YAML has no media_standards) ───────────
_DEFAULTS: Dict[str, Any] = {
    "image": {
        "selfie":    {"width": 512, "height": 768, "format": "png"},
        "portrait":  {"width": 512, "height": 768, "format": "png"},
        "thumbnail": {"width": 200, "height": 200, "format": "jpg"},
    },
    "video": {
        "message": {
            "width": 640, "height": 480, "fps": 24,
            "codec": "h264", "max_duration": 15,
        },
        "call": {
            "width": 640, "height": 480, "fps": 15,
            "codec": "h264",
        },
    },
    "audio": {
        "voice_message": {
            "sample_rate": 22050, "channels": 1,
            "format": "wav", "min_duration": 10, "max_duration": 3600,
        },
        "voice_mail": {
            "sample_rate": 22050, "channels": 1,
            "format": "wav", "min_duration": 10, "max_duration": 3600,
        },
    },
}


class MediaConfig:
    """Read-only accessor for media dimension / format standards."""

    def __init__(self, raw: Dict[str, Any] | None = None):
        self._data = raw or _DEFAULTS

    # ── Images ──────────────────────────────────────────────────────────
    def image_dims(self, kind: str = "selfie") -> Tuple[int, int]:
        """Return ``(width, height)`` for the given image kind."""
        spec = self._data.get("image", {}).get(kind, _DEFAULTS["image"]["selfie"])
        return int(spec["width"]), int(spec["height"])

    def image_format(self, kind: str = "selfie") -> str:
        spec = self._data.get("image", {}).get(kind, _DEFAULTS["image"]["selfie"])
        return spec.get("format", "png")

    # ── Video ───────────────────────────────────────────────────────────
    def video_spec(self, kind: str = "message") -> Dict[str, Any]:
        """Return full video spec dict (width, height, fps, codec, …)."""
        return dict(self._data.get("video", {}).get(kind, _DEFAULTS["video"]["message"]))

    def video_dims(self, kind: str = "message") -> Tuple[int, int]:
        spec = self.video_spec(kind)
        return int(spec["width"]), int(spec["height"])

    def video_fps(self, kind: str = "message") -> int:
        return int(self.video_spec(kind).get("fps", 24))

    def video_max_duration(self, kind: str = "message") -> int:
        return int(self.video_spec(kind).get("max_duration", 15))

    # ── Audio ───────────────────────────────────────────────────────────
    def audio_spec(self, kind: str = "voice_message") -> Dict[str, Any]:
        return dict(self._data.get("audio", {}).get(kind, _DEFAULTS["audio"]["voice_message"]))

    def audio_sample_rate(self, kind: str = "voice_message") -> int:
        return int(self.audio_spec(kind).get("sample_rate", 22050))

    def audio_channels(self, kind: str = "voice_message") -> int:
        return int(self.audio_spec(kind).get("channels", 1))

    def audio_format(self, kind: str = "voice_message") -> str:
        return self.audio_spec(kind).get("format", "wav")

    def audio_max_duration(self, kind: str = "voice_message") -> int:
        return int(self.audio_spec(kind).get("max_duration", 3600))

    # ── Raw access ──────────────────────────────────────────────────────
    def raw(self) -> Dict[str, Any]:
        return dict(self._data)


def get_media_config() -> MediaConfig:
    """Return the global MediaConfig singleton (lazy-init, thread-safe)."""
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        raw = None
        try:
            from engine.config import get_config
            raw = get_config().get("media_standards", None)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        _instance = MediaConfig(raw)
        return _instance
