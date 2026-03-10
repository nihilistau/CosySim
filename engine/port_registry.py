"""Canonical control-plane registry for CosySim ports and target metadata.

This module is the single source of truth for:

* service/scene → port mappings
* compatibility aliases for legacy service names
* curated target lists used by launcher, dashboards, and tooling
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from engine.control_plane_registry import SCENE_IDS, get_target_metadata_catalogue

logger = logging.getLogger(__name__)


# ── Canonical defaults ──────────────────────────────────────────────────────

_DEFAULT_PORTS: Dict[str, int] = {
    # Launcher-managed scenes
    "phone": 5555,
    "penthouse": 5556,
    "lounge": 5557,
    "tavern": 5558,
    "casino": 5559,
    "gallery": 5560,
    "arena": 5561,
    "realm": 5562,
    "neoncity": 5563,
    "coders": 5564,
    "heist": 5565,
    "command_center": 5566,
    "games": 5567,
    "asset_studio": 5568,
    "grid": 5569,
    "lab_break": 5571,
    "intel_hub": 5580,
    # Launcher-managed services
    "hub": 8500,
    "nexus_panel": 5570,
    "dashboard": 8501,
    "admin": 8502,
    "assets": 8503,
    "creator": 8504,
    "tts": 8600,
    "bridge": 8601,
    "canvas": 5590,
    "canvas_api": 5595,
    "nlm_proxy": 8800,
    "system_control": 5575,
    # External / sidecar infrastructure
    "orpheus_tts": 5005,
    "cosyvoice_tts": 5050,
    "whisper_stt": 5051,
    "canvas_sidecar": 5591,
    "lmstudio": 1234,
    "comfyui": 8188,
    "nexus": 8700,
}

_ALIASES: Dict[str, str] = {
    "qwen3_tts": "tts",
    "web_bridge": "bridge",
    "nexus_canvas": "canvas",
    "notebooklm_proxy": "nlm_proxy",
}


# Logical groupings for display / conflict detection.
SERVICE_GROUPS: Dict[str, List[str]] = {
    "scenes": [
        "phone", "penthouse", "lounge", "tavern", "casino", "gallery",
        "arena", "realm", "neoncity", "coders", "heist",
        "command_center", "games", "asset_studio", "grid",
        "lab_break",
        "intel_hub", "nexus_panel", "system_control",
    ],
    "streamlit": ["hub", "dashboard", "admin", "assets", "creator"],
    "tts": ["qwen3_tts", "orpheus_tts", "cosyvoice_tts", "whisper_stt"],
    "infrastructure": [
        "web_bridge", "lmstudio", "comfyui", "nexus", "notebooklm_proxy",
        "nexus_canvas", "canvas_api", "canvas_sidecar",
    ],
}


# Curated control-plane target lists. Keep membership stable, resolve ports here.
ALL_SCENE_TARGETS: Tuple[str, ...] = SCENE_IDS

SCENE_HEALTH_TARGETS: Tuple[str, ...] = (
    "phone",
    "penthouse",
    "lounge",
    "tavern",
    "casino",
    "gallery",
    "arena",
    "realm",
    "neoncity",
    "coders",
    "heist",
    "command_center",
    "games",
    "asset_studio",
    "grid",
    "lab_break",
    "nexus_panel",
    "system_control",
    "intel_hub",
    "hub",
    "dashboard",
    "admin",
)

HUB_CATALOGUE_TARGETS: Tuple[str, ...] = (
    "penthouse",
    "neoncity",
    "grid",
    "lounge",
    "tavern",
    "casino",
    "phone",
    "arena",
    "heist",
    "realm",
    "gallery",
    "coders",
    "games",
    "command_center",
    "lab_break",
    "asset_studio",
    "nexus_panel",
    "canvas",
    "intel_hub",
    "system_control",
)

HUB_HEALTH_TARGETS: Tuple[str, ...] = (
    "lmstudio",
    "nexus",
    "comfyui",
    "tts",
    "bridge",
    "hub",
    "nexus_panel",
    "canvas",
    "system_control",
    "intel_hub",
    "phone",
    "penthouse",
    "lounge",
    "tavern",
    "casino",
    "gallery",
    "arena",
    "realm",
    "neoncity",
    "coders",
    "heist",
    "games",
    "grid",
    "lab_break",
    "asset_studio",
)

TUI_EXTERNAL_TARGETS: Tuple[str, ...] = (
    "lmstudio",
    "nexus",
    "comfyui",
    "tts",
    "nlm_proxy",
    "canvas",
)

SYSTEM_CONTROL_TARGETS: Tuple[str, ...] = (
    "nexus",
    "nlm_proxy",
    "hub",
    "nexus_panel",
    "command_center",
    "penthouse",
    "phone",
    "heist",
    "realm",
    "neoncity",
    "lounge",
    "tavern",
    "casino",
    "arena",
    "games",
    "lmstudio",
    "comfyui",
    "tts",
    "system_control",
)

ASSET_STUDIO_INJECT_SCENES: Tuple[str, ...] = (
    "penthouse",
    "phone",
    "lounge",
    "tavern",
    "casino",
    "gallery",
    "arena",
    "realm",
    "neoncity",
)

_HEALTH_PATH_OVERRIDES: Dict[str, str] = {
    "hub": "/health",
    "lmstudio": "/api/v1/models",
    "comfyui": "/system_stats",
    "tts": "/health",
    "nlm_proxy": "/health",
}

_HEALTH_NAME_OVERRIDES: Dict[str, str] = {
    "nexus": "Nexus KMS",
    "nlm_proxy": "NLM Proxy",
    "hub": "Scene Hub",
    "nexus_panel": "Nexus Panel",
    "tts": "TTS Server",
    "system_control": "System Control",
    "lmstudio": "LMStudio",
    "comfyui": "ComfyUI",
}


def _display_name(service: str) -> str:
    return service.replace("_", " ").title()


@lru_cache(maxsize=1)
def _control_plane_catalogue() -> Dict[str, Dict[str, Any]]:
    """Return shared control-plane metadata for launcher-managed targets."""
    return get_target_metadata_catalogue()


def _canonical_service(service: str) -> str:
    return _ALIASES.get(service, service)


def _health_path_for(service: str) -> str:
    canonical = _canonical_service(service)
    if canonical in _HEALTH_PATH_OVERRIDES:
        return _HEALTH_PATH_OVERRIDES[canonical]
    meta = _control_plane_catalogue().get(canonical, {})
    if meta.get("group") == "scene":
        return "/api/health"
    if meta.get("type") == "flask":
        return "/api/health"
    return "/health"


def get_target_metadata(service: str) -> Dict[str, Any]:
    """Return canonical metadata for a service or scene."""
    canonical = _canonical_service(service)
    meta = dict(_control_plane_catalogue().get(canonical, {}))
    meta.setdefault("id", canonical)
    meta.setdefault("group", "external")
    meta.setdefault("type", None)
    meta.setdefault("label", _HEALTH_NAME_OVERRIDES.get(canonical, _display_name(canonical)))
    meta["port"] = get_port(canonical)
    return meta


def build_target_listing(target_ids: Iterable[str]) -> List[Dict[str, Any]]:
    """Return normalized control-plane target records with health metadata."""
    targets: List[Dict[str, Any]] = []
    for target_id in target_ids:
        meta = get_target_metadata(target_id)
        service_id = meta["id"]
        health_path = _health_path_for(service_id)
        targets.append(
            {
                "id": service_id,
                "name": meta["label"],
                "label": meta["label"],
                "group": meta["group"],
                "type": meta["type"],
                "port": meta["port"],
                "health_name": _HEALTH_NAME_OVERRIDES.get(service_id, meta["label"]),
                "health_path": health_path,
                "health_url": get_service_url(service_id, path=health_path),
            }
        )
    return targets


def build_scene_port_map(target_ids: Iterable[str] = SCENE_HEALTH_TARGETS) -> Dict[int, str]:
    """Return a canonical port→target map for scene tooling."""
    return {get_port(target_id): _canonical_service(target_id) for target_id in target_ids}


def build_scene_listing(scene_ids: Iterable[str] = ASSET_STUDIO_INJECT_SCENES) -> List[Dict[str, Any]]:
    """Return a stable scene listing with labels and canonical ports."""
    scenes: List[Dict[str, Any]] = []
    for scene in build_target_listing(scene_ids):
        scenes.append({"id": scene["id"], "name": scene["label"], "port": scene["port"]})
    return scenes


def build_health_endpoints(target_ids: Iterable[str] = SYSTEM_CONTROL_TARGETS) -> List[Dict[str, Any]]:
    """Return canonical health-check endpoint descriptors."""
    endpoints: List[Dict[str, Any]] = []
    for target in build_target_listing(target_ids):
        endpoints.append(
            {
                "id": target["id"],
                "name": target["health_name"],
                "url": target["health_url"],
                "port": target["port"],
            }
        )
    return endpoints


class PortRegistry:
    """Central registry of service→port mappings with conflict detection."""

    SERVICE_GROUPS = SERVICE_GROUPS

    def __init__(self) -> None:
        self._ports: Dict[str, int] = dict(_DEFAULT_PORTS)
        self._aliases: Dict[str, str] = dict(_ALIASES)
        self._load_from_config()

    # ── Public API ───────────────────────────────────────────────────────

    def get(self, service: str, default: Optional[int] = None) -> int:
        """Return the port for *service*, falling back to *default*."""
        canonical = self._aliases.get(service, service)
        port = self._ports.get(canonical)
        if port is not None:
            return port
        if default is not None:
            return default
        raise KeyError(f"Unknown service: {service!r}")

    def get_port(self, service: str, default: Optional[int] = None) -> int:
        """Compatibility alias for callers that use ``registry.get_port(...)``."""
        return self.get(service, default)

    def get_url(self, service: str, scheme: str = "http", path: str = "") -> str:
        """Return ``scheme://localhost:{port}{path}`` for *service*."""
        port = self.get(service)
        return f"{scheme}://localhost:{port}{path}"

    def register(self, service: str, port: int) -> None:
        """Register (or override) a service→port mapping at runtime."""
        canonical = self._aliases.get(service, service)
        self._ports[canonical] = port

    def all_ports(self) -> Dict[str, int]:
        """Return a copy of the canonical service→port mapping."""
        return dict(self._ports)

    def find_conflicts(self) -> List[Tuple[str, str, int]]:
        """Return list of ``(service_a, service_b, port)`` sharing a port."""
        port_to_services: Dict[int, List[str]] = {}
        for svc, port in self._ports.items():
            port_to_services.setdefault(port, []).append(svc)
        conflicts = []
        for port, services in port_to_services.items():
            if len(services) > 1:
                for i, a in enumerate(services):
                    for b in services[i + 1:]:
                        conflicts.append((a, b, port))
        return conflicts

    def for_group(self, group: str) -> Dict[str, int]:
        """Return ports for a named group (scenes, streamlit, tts, infrastructure)."""
        names = SERVICE_GROUPS.get(group, [])
        return {name: self.get(name) for name in names}

    def summary(self) -> str:
        """Human-readable summary table."""
        lines = ["Service Port Registry", "=" * 40]
        for group_name, members in SERVICE_GROUPS.items():
            lines.append(f"\n  {group_name.upper()}")
            for svc in members:
                port = self.get(svc, "?")
                lines.append(f"    {svc:<20s} :{port}")
        return "\n".join(lines)

    # ── Config integration ───────────────────────────────────────────────

    def _load_from_config(self) -> None:
        """Override defaults with values from ``config/default.yaml``."""
        try:
            from engine.config import get_config

            cfg = get_config()
        except Exception:
            logger.debug("Config unavailable, using default ports", exc_info=True)
            return

        # Scene ports
        for scene_name in SERVICE_GROUPS["scenes"]:
            canonical = self._aliases.get(scene_name, scene_name)
            port = cfg.get(f"scenes.{canonical}.port")
            if port is not None:
                self._ports[canonical] = int(port)

        # Streamlit ports
        for app_name in SERVICE_GROUPS["streamlit"]:
            canonical = self._aliases.get(app_name, app_name)
            port = cfg.get(f"scenes.{canonical}.port")
            if port is not None:
                self._ports[canonical] = int(port)

        # TTS
        tts_url = cfg.get("tts.server_url", "")
        if tts_url:
            try:
                self._ports["tts"] = int(tts_url.rsplit(":", 1)[-1].rstrip("/"))
            except ValueError:
                logger.debug("Failed to parse tts port from URL: %s", tts_url, exc_info=True)
        orpheus_url = cfg.get("tts.orpheus.server_url", "")
        if orpheus_url:
            try:
                self._ports["orpheus_tts"] = int(orpheus_url.rsplit(":", 1)[-1].rstrip("/"))
            except ValueError:
                logger.debug("Failed to parse orpheus_tts port from URL: %s", orpheus_url, exc_info=True)

        # LMStudio
        lms_port = cfg.get("lmstudio.port")
        if lms_port is not None:
            self._ports["lmstudio"] = int(lms_port)

        # ComfyUI
        comfy_port = cfg.get("comfyui.port")
        if comfy_port is not None:
            self._ports["comfyui"] = int(comfy_port)

        conflicts = self.find_conflicts()
        if conflicts:
            for a, b, port in conflicts:
                logger.warning("Port conflict: %s and %s both on :%d", a, b, port)


# ── Singleton ───────────────────────────────────────────────────────────────

_registry: Optional[PortRegistry] = None


def get_port_registry() -> PortRegistry:
    """Return the singleton ``PortRegistry``."""
    global _registry
    if _registry is None:
        _registry = PortRegistry()
    return _registry


def get_port(service: str, default: Optional[int] = None) -> int:
    """Convenience: look up a port by service name."""
    return get_port_registry().get(service, default)


def get_service_url(service: str, path: str = "") -> str:
    """Convenience: get ``http://localhost:{port}{path}`` for a service."""
    return get_port_registry().get_url(service, path=path)
