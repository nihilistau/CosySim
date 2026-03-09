"""
System Monitor — CPU, RAM, GPU metrics, and service health checks.

Usage::

    from engine.logging.monitor import get_system_monitor
    mon = get_system_monitor()
    snap = mon.snapshot()          # {"cpu_pct": 23.5, "ram_used_gb": 12.1, ...}
    health = mon.check_services()  # {"lmstudio": {"up": True, "latency_ms": 42}, ...}
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: Optional["SystemMonitor"] = None


class SystemMonitor:
    """Singleton that collects system metrics and pings external services."""

    def __init__(self):
        self._last_snapshot: Dict[str, Any] = {}
        self._last_snapshot_time = 0.0
        self._cache_ttl = 5.0  # seconds

    # ── System metrics ──────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        """Return CPU/RAM/GPU metrics (cached for 5s)."""
        now = time.time()
        if now - self._last_snapshot_time < self._cache_ttl and self._last_snapshot:
            return self._last_snapshot

        data: Dict[str, Any] = {}

        # CPU / RAM via psutil (optional)
        try:
            import psutil
            data["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            data["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
            data["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
            data["ram_percent"] = mem.percent
            # Also emit nested "ram" dict that dashboard expects
            data["ram"] = {
                "used_gb":  data["ram_used_gb"],
                "total_gb": data["ram_total_gb"],
                "percent":  data["ram_percent"],
            }
        except ImportError:
            data["cpu_percent"] = None
            data["ram_total_gb"] = None
            data["ram_used_gb"] = None
            data["ram_percent"] = None
            data["ram"] = {}

        # GPU via nvidia-smi
        gpu = self._gpu_metrics()
        data.update(gpu)
        # Nested "gpu" dict that dashboard expects
        data["gpu"] = {
            "available":      (gpu.get("gpu_name") is not None),
            "vram_used_mb":   gpu.get("gpu_vram_used_mb"),
            "vram_total_mb":  gpu.get("gpu_vram_total_mb"),
            "name":           gpu.get("gpu_name"),
            "temp_c":         gpu.get("gpu_temp_c"),
        }

        self._last_snapshot = data
        self._last_snapshot_time = now
        return data

    def _gpu_metrics(self) -> Dict[str, Any]:
        """Query nvidia-smi for VRAM usage."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total,gpu_name,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 4:
                    return {
                        "gpu_vram_used_mb": int(parts[0].strip()),
                        "gpu_vram_total_mb": int(parts[1].strip()),
                        "gpu_name": parts[2].strip(),
                        "gpu_temp_c": int(parts[3].strip()),
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            logger.debug("Suppressed exception", exc_info=True)
        return {
            "gpu_vram_used_mb": None,
            "gpu_vram_total_mb": None,
            "gpu_name": None,
            "gpu_temp_c": None,
        }

    # ── Service health ──────────────────────────────────────────────────
    def check_services(self) -> Dict[str, Dict[str, Any]]:
        """Ping known services and return health status."""
        services = {}

        services["lmstudio"] = self._ping_http(
            self._resolve_base("lmstudio", "lmstudio.base_url", "http://localhost:1234") + "/v1/models"
        )
        services["comfyui"] = self._ping_http(
            self._resolve_base("comfyui", "comfyui.base_url", "http://localhost:8188") + "/system_stats"
        )
        services["tts"] = self._ping_http(
            self._resolve_base("tts", "tts.server_url", "http://localhost:8600") + "/status"
        )
        services["mcp"] = self._ping_http(
            self._resolve_base("nexus", "mcp.base_url", "http://localhost:8700") + "/health"
        )

        return services

    def _ping_http(self, url: str, timeout: float = 3.0) -> Dict[str, Any]:
        """Ping a URL, return ``{up: bool, latency_ms: float, error: str}``."""
        try:
            import requests
            start = time.perf_counter()
            resp = requests.get(url, timeout=timeout)
            latency = (time.perf_counter() - start) * 1000
            return {
                "up": resp.status_code < 500,
                "status_code": resp.status_code,
                "latency_ms": round(latency, 1),
                "error": None,
            }
        except ImportError:
            return {"up": None, "latency_ms": None, "error": "requests not installed"}
        except Exception as e:
            return {"up": False, "latency_ms": None, "error": str(e)}

    def _get_url(self, config_key: str, default: str) -> str:
        try:
            from engine.config import get_config
            return get_config().get(config_key, default) or default
        except Exception:
            return default

    def _resolve_base(self, service: str, config_key: str, fallback: str) -> str:
        """Resolve service base URL via port registry → config → hardcoded fallback."""
        try:
            from engine.port_registry import get_service_url
            return get_service_url(service)
        except Exception:
            return self._get_url(config_key, fallback)

    # ── LMStudio model info ─────────────────────────────────────────────
    def get_loaded_model(self) -> Optional[str]:
        """Ask LMStudio which model is loaded."""
        try:
            import requests
            url = self._resolve_base("lmstudio", "lmstudio.base_url", "http://localhost:1234")
            resp = requests.get(f"{url}/v1/models", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                if models:
                    return models[0].get("id", "unknown")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return None


def get_system_monitor() -> SystemMonitor:
    """Return the singleton SystemMonitor."""
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        _instance = SystemMonitor()
        return _instance
