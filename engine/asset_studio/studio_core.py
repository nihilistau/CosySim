"""Asset Studio Core — main orchestrator for all asset generation.

Provides a unified ``generate(asset_type, params)`` entry point, routes
requests to the correct generator, registers results in the asset library,
optionally caches to Nexus, and emits a socket event for CosySim integration.

Feature flags (all toggleable via config or Settings tab):
    asset_studio.comfyui_enabled    — image/portrait/video via ComfyUI
    asset_studio.tts_enabled        — voice via TTS manager
    asset_studio.lms_enabled        — LLM-assisted item/SVG generation
    asset_studio.video_enabled      — AnimateDiff video (subset of comfyui)
    asset_studio.nexus_cache_enabled — persist asset metadata to Nexus
    asset_studio.adult_enabled      — allow adult content in generation
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# Mapping of asset_type → generator class path (lazy-loaded).
_GENERATOR_MAP: Dict[str, str] = {
    "image":    "engine.asset_studio.generators.image_gen.ImageGenerator",
    "portrait": "engine.asset_studio.generators.portrait_gen.PortraitGenerator",
    "voice":    "engine.asset_studio.generators.voice_gen.VoiceGenerator",
    "video":    "engine.asset_studio.generators.video_gen.VideoGenerator",
    "item":     "engine.asset_studio.generators.item_gen.ItemGenerator",
    "svg":      "engine.asset_studio.generators.svg_gen.SvgGenerator",
    "audio":    "engine.asset_studio.generators.audio_gen.AudioGenerator",
}

# Feature flag config keys and their defaults.
_FLAG_DEFAULTS: Dict[str, bool] = {
    "asset_studio.comfyui_enabled":     True,
    "asset_studio.tts_enabled":         True,
    "asset_studio.lms_enabled":         True,
    "asset_studio.video_enabled":       True,
    "asset_studio.nexus_cache_enabled": True,
    "asset_studio.adult_enabled":       False,
}

# Which asset types require which feature flags to be enabled.
_TYPE_FLAGS: Dict[str, List[str]] = {
    "image":    ["asset_studio.comfyui_enabled"],
    "portrait": ["asset_studio.comfyui_enabled"],
    "voice":    ["asset_studio.tts_enabled"],
    "video":    ["asset_studio.comfyui_enabled", "asset_studio.video_enabled"],
    "item":     ["asset_studio.lms_enabled"],
    "svg":      ["asset_studio.lms_enabled"],
    "audio":    [],  # always available (synthesised tones)
}


class AssetStudioCore:
    """Central orchestrator for the Asset Studio.

    Usage::

        from engine.asset_studio import get_studio_core
        core = get_studio_core()
        result = core.generate("portrait", {"character_id": "aria", "mood": "happy"})
    """

    def __init__(self) -> None:
        """Initialise core, loading config flags."""
        self._cfg = get_config()
        self._generators: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ── Feature flags ─────────────────────────────────────────────────────────

    def get_flags(self) -> Dict[str, bool]:
        """Return all feature flags and their current values.

        Returns:
            Dict of ``{flag_key: bool}``.
        """
        return {
            key: bool(self._cfg.get(key, default))
            for key, default in _FLAG_DEFAULTS.items()
        }

    def set_flag(self, flag_key: str, value: bool) -> bool:
        """Set a feature flag at runtime.

        This modifies the in-memory config; changes do not persist to disk
        unless the config manager writes them.

        Args:
            flag_key: One of the recognised flag keys.
            value: New boolean value.

        Returns:
            ``True`` if the flag was recognised and set.
        """
        if flag_key not in _FLAG_DEFAULTS:
            return False
        self._cfg.set(flag_key, value)
        logger.info("Asset Studio flag %s = %s", flag_key, value)
        return True

    def is_type_available(self, asset_type: str) -> bool:
        """Return ``True`` if *asset_type* is available given current flags.

        Args:
            asset_type: image|portrait|voice|video|item|svg|audio.

        Returns:
            ``bool``.
        """
        for flag in _TYPE_FLAGS.get(asset_type, []):
            if not bool(self._cfg.get(flag, _FLAG_DEFAULTS.get(flag, True))):
                return False
        return True

    # ── Generation ────────────────────────────────────────────────────────────

    def generate(self, asset_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an asset of *asset_type* using *params*.

        Routes to the appropriate generator, registers the result in the
        asset library, optionally caches to Nexus, and emits
        ``asset_generated`` on the active SocketIO instance.

        Args:
            asset_type: image|portrait|voice|video|item|svg|audio.
            params: Generator-specific parameters dict.

        Returns:
            Generator result dict with additional ``asset_id`` key.
        """
        if asset_type not in _GENERATOR_MAP:
            return {"error": f"Unknown asset type: {asset_type}"}

        if not self.is_type_available(asset_type):
            return {
                "error": f"Asset type '{asset_type}' is disabled by feature flags",
                "available": False,
            }

        generator = self._get_generator(asset_type)
        params.setdefault(
            "adult_allowed",
            bool(self._cfg.get("asset_studio.adult_enabled", False)),
        )

        try:
            result = generator.generate(**params)
        except Exception as exc:
            logger.exception("Generator %s raised unexpectedly: %s", asset_type, exc)
            result = {"error": str(exc), "url": ""}

        # Register in asset library.
        asset_id = self._register_asset(asset_type, params, result)
        result["asset_id"] = asset_id

        # Optionally cache to Nexus.
        if bool(self._cfg.get("asset_studio.nexus_cache_enabled", True)):
            self._cache_to_nexus(asset_type, asset_id, result)

        # Emit socket event for CosySim integration.
        self._emit_event(asset_type, asset_id, result)

        return result

    # ── Library helpers ────────────────────────────────────────────────────────

    def _register_asset(
        self, asset_type: str, params: Dict[str, Any], result: Dict[str, Any]
    ) -> str:
        """Register the generated asset in the asset library and return its ID."""
        try:
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            lib = get_asset_library()

            url = result.get("url", "")
            if asset_type == "item":
                url = result.get("item_data", {}).get("icon_url", url)
            elif asset_type == "svg":
                url = result.get("url", "")

            # Build title from params.
            character_id = params.get("character_id", "")
            title = params.get("title", "")
            if not title:
                if character_id:
                    title = f"{asset_type}/{character_id}/{params.get('mood', 'neutral')}"
                elif params.get("subject"):
                    title = f"{asset_type}/{params['subject'][:40]}"
                elif params.get("item_name"):
                    title = f"item/{params['item_name']}"
                elif params.get("text"):
                    title = f"voice/{params['text'][:40]}"
                else:
                    title = f"{asset_type}/{params.get('scene', 'global')}"

            meta: Dict[str, Any] = {}
            if asset_type == "item":
                meta["item_data"] = result.get("item_data", {})
            elif asset_type == "svg":
                meta["svg_content"] = result.get("svg_content", "")[:500]
            elif asset_type == "voice":
                meta["backend"] = result.get("backend", "")
                meta["duration"] = result.get("duration", 0)
            elif asset_type == "video":
                meta["frames"] = params.get("frames", 16)
                meta["fps"] = params.get("fps", 8)

            return lib.register(
                asset_type=asset_type,
                url=url,
                title=title,
                scene=params.get("scene", ""),
                character_id=character_id,
                mood=params.get("mood", "neutral"),
                preset_id=params.get("preset_id", ""),
                prompt=result.get("prompt", ""),
                negative=result.get("negative", ""),
                metadata=meta,
                nexus_key=result.get("nexus_key", ""),
                duration_ms=result.get("duration_ms", 0),
                cached=result.get("cached", False),
            )
        except Exception as exc:
            logger.warning("Failed to register asset in library: %s", exc)
            return ""

    def _cache_to_nexus(
        self, asset_type: str, asset_id: str, result: Dict[str, Any]
    ) -> None:
        """Persist asset metadata to Nexus (best-effort)."""
        if not asset_id or result.get("error"):
            return
        try:
            from engine.nexus.client import get_nexus_client  # noqa: PLC0415
            import json  # noqa: PLC0415

            client = get_nexus_client()
            content = json.dumps({
                "asset_id": asset_id,
                "url": result.get("url", ""),
                "duration_ms": result.get("duration_ms", 0),
                "cached": result.get("cached", False),
            })
            client.add_entry(
                title=f"studio_asset:{asset_id}",
                content=content,
                content_type="memory",
                category="asset_studio",
            )
        except Exception:
            logger.debug("Nexus asset cache store failed", exc_info=True)

    def _emit_event(
        self, asset_type: str, asset_id: str, result: Dict[str, Any]
    ) -> None:
        """Emit an ``asset_generated`` socket event if a SocketIO instance exists."""
        try:
            from engine.scenes.base_scene import BaseScene  # noqa: PLC0415
            scene = BaseScene.get_active_scene("asset_studio")
            if scene and hasattr(scene, "socketio"):
                scene.socketio.emit("asset_generated", {
                    "asset_type": asset_type,
                    "asset_id": asset_id,
                    "url": result.get("url", ""),
                    "error": result.get("error", ""),
                })
        except Exception as e:
            logger.debug("[StudioCore] Socket event emission failed (operation=emit_event): %s", e)

    # ── Generator factory ─────────────────────────────────────────────────────

    def _get_generator(self, asset_type: str) -> Any:
        """Return (or create) the generator for *asset_type*."""
        with self._lock:
            if asset_type not in self._generators:
                class_path = _GENERATOR_MAP[asset_type]
                module_path, class_name = class_path.rsplit(".", 1)
                import importlib  # noqa: PLC0415
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                self._generators[asset_type] = cls()
        return self._generators[asset_type]

    # ── Health / status ───────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Return health status of all backends used by the studio.

        Returns:
            Dict with ``flags``, ``backends``, ``library_stats``.
        """
        flags = self.get_flags()

        backends: Dict[str, Any] = {}

        # ComfyUI.
        if flags.get("asset_studio.comfyui_enabled"):
            try:
                import requests  # noqa: PLC0415
                # v1.49.1 [2026-03-22] — Use comfyui.base_url (was stale art.comfyui_url)
                comfyui_url = self._cfg.get("comfyui.base_url", "http://localhost:8188")
                resp = requests.get(f"{comfyui_url}/system_stats", timeout=3)
                backends["comfyui"] = {"status": "online", "code": resp.status_code}
            except Exception as e:
                backends["comfyui"] = {"status": "offline", "error": str(e)}

        # TTS.
        if flags.get("asset_studio.tts_enabled"):
            try:
                from engine.tts.tts_manager import get_tts_manager  # noqa: PLC0415
                mgr = get_tts_manager()
                backends["tts"] = {"status": "online", "backends": list(mgr.available_backends())}
            except Exception as e:
                backends["tts"] = {"status": "offline", "error": str(e)}

        # v1.43.1 [2026-03-21] — LMStudio status via unified client
        if flags.get("asset_studio.lms_enabled"):
            try:
                from engine.lmstudio.chat import is_ready  # noqa: PLC0415
                backends["lmstudio"] = {"status": "online" if is_ready() else "offline"}
            except Exception as e:
                backends["lmstudio"] = {"status": "offline", "error": str(e)}

        # Library stats.
        lib_stats: Dict[str, Any] = {}
        try:
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            lib_stats = get_asset_library().stats()
        except Exception:
            pass

        return {"flags": flags, "backends": backends, "library_stats": lib_stats}


# ── Singleton ─────────────────────────────────────────────────────────────────

_core_instance: Optional[AssetStudioCore] = None
_core_lock = threading.Lock()


def get_studio_core() -> AssetStudioCore:
    """Return the process-wide :class:`AssetStudioCore` singleton.

    Thread-safe; creates the instance on first call.

    Returns:
        The singleton :class:`AssetStudioCore`.
    """
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = AssetStudioCore()
    return _core_instance
