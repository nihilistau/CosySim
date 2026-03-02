"""Centralised port registry for all CosySim services.

Provides a single source of truth for port assignments, conflict detection,
and lookup by service name.  Config values from ``default.yaml`` override the
built-in defaults when ``get_config()`` is available.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Built-in defaults (fallback when config is unavailable) ──────
_DEFAULT_PORTS: Dict[str, int] = {
    # Flask scenes (5555–5570)
    "phone": 5555,
    "bedroom": 5556,
    "lounge": 5557,
    "tavern": 5558,
    "casino": 5559,
    "gallery": 5560,
    "realm": 5562,
    "neoncity": 5563,
    "coders": 5564,
    "heist": 5565,
    "command_center": 5566,
    "games": 5567,
    "asset_studio": 5568,
    "nexus_panel": 5570,
    # Streamlit apps (8500–8504)
    "hub": 8500,
    "dashboard": 8501,
    "admin": 8502,
    "assets": 8503,
    "creator": 8504,
    # TTS / voice (5005, 5050–5051, 8600)
    "qwen3_tts": 8600,
    "orpheus_tts": 5005,
    "cosyvoice_tts": 5050,
    "whisper_stt": 5051,
    # Infrastructure
    "web_bridge": 8601,
    "lmstudio": 1234,
    "comfyui": 8188,
    "nexus": 8700,
    "notebooklm_proxy": 8800,
}

# Logical groupings for display / conflict detection
SERVICE_GROUPS: Dict[str, List[str]] = {
    "scenes": [
        "phone", "bedroom", "lounge", "tavern", "casino", "gallery",
        "arena", "realm", "neoncity", "coders", "heist",
        "command_center", "games", "asset_studio", "nexus_panel",
    ],
    "streamlit": ["hub", "dashboard", "admin", "assets", "creator"],
    "tts": ["qwen3_tts", "orpheus_tts", "cosyvoice_tts", "whisper_stt"],
    "infrastructure": ["web_bridge", "lmstudio", "comfyui", "nexus", "notebooklm_proxy"],
}


class PortRegistry:
    """Central registry of service→port mappings with conflict detection."""

    def __init__(self) -> None:
        self._ports: Dict[str, int] = dict(_DEFAULT_PORTS)
        self._load_from_config()

    # ── Public API ───────────────────────────────────────────────

    def get(self, service: str, default: Optional[int] = None) -> int:
        """Return the port for *service*, falling back to *default*."""
        port = self._ports.get(service)
        if port is not None:
            return port
        if default is not None:
            return default
        raise KeyError(f"Unknown service: {service!r}")

    def get_url(self, service: str, scheme: str = "http", path: str = "") -> str:
        """Return ``scheme://localhost:{port}{path}`` for *service*."""
        port = self.get(service)
        return f"{scheme}://localhost:{port}{path}"

    def register(self, service: str, port: int) -> None:
        """Register (or override) a service→port mapping at runtime."""
        self._ports[service] = port

    def all_ports(self) -> Dict[str, int]:
        """Return a copy of the full service→port mapping."""
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
        return {name: self._ports[name] for name in names if name in self._ports}

    def summary(self) -> str:
        """Human-readable summary table."""
        lines = ["Service Port Registry", "=" * 40]
        for group_name, members in SERVICE_GROUPS.items():
            lines.append(f"\n  {group_name.upper()}")
            for svc in members:
                port = self._ports.get(svc, "?")
                lines.append(f"    {svc:<20s} :{port}")
        return "\n".join(lines)

    # ── Config integration ───────────────────────────────────────

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
            port = cfg.get(f"scenes.{scene_name}.port")
            if port is not None:
                self._ports[scene_name] = int(port)

        # Streamlit ports
        for app_name in SERVICE_GROUPS["streamlit"]:
            port = cfg.get(f"scenes.{app_name}.port")
            if port is not None:
                self._ports[app_name] = int(port)

        # TTS
        tts_url = cfg.get("tts.server_url", "")
        if tts_url and ":" in tts_url.rsplit(":", 1)[-1]:
            try:
                self._ports["qwen3_tts"] = int(tts_url.rsplit(":", 1)[-1].rstrip("/"))
            except ValueError:
                logger.debug(f"Failed to parse qwen3_tts port from URL: {tts_url}", exc_info=True)
        orpheus_url = cfg.get("tts.orpheus.server_url", "")
        if orpheus_url and ":" in orpheus_url.rsplit(":", 1)[-1]:
            try:
                self._ports["orpheus_tts"] = int(orpheus_url.rsplit(":", 1)[-1].rstrip("/"))
            except ValueError:
                logger.debug(f"Failed to parse orpheus_tts port from URL: {orpheus_url}", exc_info=True)

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


# ── Singleton ────────────────────────────────────────────────────

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
