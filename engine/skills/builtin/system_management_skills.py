"""
System management MCP skills for CosySim agents.

Provides service health monitoring, URL resolution, flywheel control,
configuration access, scene discovery, and a combined system overview.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill, SkillCategory
from engine.utils import port_is_open

logger = logging.getLogger(__name__)


def _port_registry():
    from engine.port_registry import get_port_registry
    return get_port_registry()


def _control_plane():
    from engine.control_plane_registry import SCENE_DEFS, SERVICE_DEFS
    return SCENE_DEFS, SERVICE_DEFS


# ── Service Health ────────────────────────────────────────────────


@skill(
    pack="system",
    description="Check health of all registered services by probing their ports",
    tags=["system", "health", "monitoring"],
    category=SkillCategory.SYSTEM,
)
def service_health_check(timeout: float = 1.0) -> str:
    """Probe every service in the port registry and report online/offline status."""
    registry = _port_registry()
    results: List[Dict[str, Any]] = []
    online_count = 0

    for name in sorted(registry._ports.keys()):
        port = registry.get(name)
        is_up = port_is_open(port, "localhost", timeout=timeout)
        if is_up:
            online_count += 1
        results.append({
            "service": name,
            "port": port,
            "status": "online" if is_up else "offline",
        })

    return json.dumps({
        "total": len(results),
        "online": online_count,
        "offline": len(results) - online_count,
        "services": results,
    })


@skill(
    pack="system",
    description="Resolve the URL for a named service from the port registry",
    tags=["system", "url", "port"],
    category=SkillCategory.SYSTEM,
)
def service_url_resolve(service: str, path: str = "") -> str:
    """Return the canonical http://localhost:{port}{path} URL for a service."""
    try:
        url = _port_registry().get_url(service, path=path)
        return json.dumps({"service": service, "url": url, "ok": True})
    except KeyError:
        return json.dumps({"service": service, "ok": False, "error": f"Unknown service: {service}"})


# ── Flywheel Control ─────────────────────────────────────────────


@skill(
    pack="system",
    description="Query or control the Nexus flywheel components (router, training, scheduler)",
    tags=["system", "flywheel", "scheduler"],
    category=SkillCategory.SYSTEM,
)
def flywheel_control(action: str = "status") -> str:
    """Manage flywheel components. Actions: status, start_scheduler, stop_scheduler."""
    result: Dict[str, Any] = {"action": action}

    if action == "status":
        try:
            from engine.nexus.query_router import get_query_router
            router = get_query_router()
            result["router"] = router.stats.to_dict() if hasattr(router.stats, "to_dict") else {}
        except Exception as exc:
            result["router"] = {"error": str(exc)}

        try:
            from engine.nexus.training_flywheel import get_training_flywheel
            fw = get_training_flywheel()
            result["training"] = fw.stats() if hasattr(fw, "stats") else {}
        except Exception as exc:
            result["training"] = {"error": str(exc)}

        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            result["scheduler"] = daemon.status()
        except Exception as exc:
            result["scheduler"] = {"error": str(exc)}

    elif action == "start_scheduler":
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            daemon.start()
            result["scheduler"] = {"started": True}
        except Exception as exc:
            result["scheduler"] = {"error": str(exc)}

    elif action == "stop_scheduler":
        try:
            from engine.nexus.scheduler_daemon import get_scheduler_daemon
            daemon = get_scheduler_daemon()
            daemon.stop()
            result["scheduler"] = {"stopped": True}
        except Exception as exc:
            result["scheduler"] = {"error": str(exc)}

    else:
        result["error"] = f"Unknown action: {action}. Use status, start_scheduler, or stop_scheduler."

    return json.dumps(result)


# ── Configuration Access ─────────────────────────────────────────


@skill(
    pack="system",
    description="Read a configuration value by dot-path key",
    tags=["system", "config", "read"],
    category=SkillCategory.SYSTEM,
)
def config_get(key: str, default: str = "") -> str:
    """Retrieve a config value. Key uses dot-notation (e.g. 'lmstudio.port')."""
    try:
        from engine.config import get_config
        cfg = get_config()
        value = cfg.get(key, default)
        return json.dumps({"key": key, "value": value, "ok": True})
    except Exception as exc:
        return json.dumps({"key": key, "ok": False, "error": str(exc)})


@skill(
    pack="system",
    description="Set a runtime configuration value by dot-path key (non-persistent)",
    tags=["system", "config", "write"],
    category=SkillCategory.SYSTEM,
)
def config_set(key: str, value: str) -> str:
    """Set a runtime config value. Changes are in-memory only (not written to YAML)."""
    try:
        from engine.config import get_config
        cfg = get_config()
        cfg.set(key, value)
        return json.dumps({"key": key, "value": value, "ok": True})
    except Exception as exc:
        return json.dumps({"key": key, "ok": False, "error": str(exc)})


# ── Scene Discovery ──────────────────────────────────────────────


@skill(
    pack="system",
    description="Discover scene directories and compare against the registered scene catalogue",
    tags=["system", "scenes", "discovery"],
    category=SkillCategory.SYSTEM,
)
def discover_scenes() -> str:
    """Scan content/scenes/ for scene directories and report registered vs unregistered."""
    try:
        from engine.control_plane_registry import scan_scene_directories
        report = scan_scene_directories()
        return json.dumps(report)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── System Overview ──────────────────────────────────────────────


@skill(
    pack="system",
    description="Combined system overview: service health, scene status, flywheel state",
    tags=["system", "overview", "dashboard"],
    category=SkillCategory.SYSTEM,
)
def system_overview(timeout: float = 0.5) -> str:
    """Return a combined system health snapshot across all subsystems."""
    overview: Dict[str, Any] = {}

    # Service health
    registry = _port_registry()
    key_services = ["lmstudio", "nexus", "hub", "tts", "comfyui"]
    svc_health: List[Dict[str, Any]] = []
    for svc in key_services:
        try:
            port = registry.get(svc)
            up = port_is_open(port, "localhost", timeout=timeout)
            svc_health.append({"service": svc, "port": port, "status": "online" if up else "offline"})
        except KeyError:
            svc_health.append({"service": svc, "status": "unknown"})
    overview["key_services"] = svc_health

    # Scene catalogue summary
    scene_defs, service_defs = _control_plane()
    overview["registered_scenes"] = len(scene_defs)
    overview["registered_services"] = len(service_defs)

    # Flywheel summary
    try:
        from engine.nexus.query_router import get_query_router
        stats = get_query_router().stats
        overview["router"] = {
            "total_queries": stats.total_queries,
            "hit_rate": round(stats.hit_rate(), 3) if stats.total_queries else 0,
            "tokens_saved": stats.total_tokens_saved,
        }
    except Exception:
        overview["router"] = {"error": "unavailable"}

    # Nexus entry counts
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        overview["nexus"] = {
            "entries": client.count_entries() if hasattr(client, "count_entries") else "unknown",
        }
    except Exception:
        overview["nexus"] = {"error": "unavailable"}

    # Scheduler status
    try:
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        status = daemon.status()
        overview["scheduler"] = {
            "running": status.get("running", False),
            "task_count": status.get("task_count", 0),
        }
    except Exception:
        overview["scheduler"] = {"error": "unavailable"}

    return json.dumps(overview)


# ── Google Auth Health + Recovery ─────────────────────────────────────────────


@skill(
    pack="system",
    description="Check Google auth health (NLM cookies + Gemini API keys) via CDP. Returns status summary.",
    category=SkillCategory.SYSTEM,
    cooldown=30.0,
    cost=0.5,
    tags=["auth", "google", "health", "nlm", "gemini"],
)
def google_auth_check() -> str:
    """Check whether Google auth (NLM + Gemini keys) is healthy. Run this before reporting auth failures."""
    try:
        from engine.nexus.cdp_auth_recovery import run_check
        status = run_check()
        result = {
            "healthy": status.healthy,
            "cdp": status.cdp_available,
            "nlm": status.nlm_logged_in,
            "aistudio": status.aistudio_logged_in,
            "working_keys": len(status.working_api_keys),
            "dead_keys": len(status.dead_api_keys),
            "summary": status.summary(),
        }
        if status.errors:
            result["errors"] = status.errors
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc), "healthy": False})


@skill(
    pack="system",
    description="Auto-recover Google auth: inject cookies, navigate to NLM + AI Studio, harvest fresh API keys. Run when google_auth_check reports unhealthy.",
    category=SkillCategory.SYSTEM,
    cooldown=120.0,
    cost=2.0,
    tags=["auth", "google", "recovery", "nlm", "gemini", "cookies", "api-keys"],
)
def google_auth_recover(keys_only: bool = False) -> str:
    """Recover Google auth via CDP — no browser window needed. Fixes cookies and dead API keys automatically.

    Args:
        keys_only: If True, only harvest and rotate API keys (skip cookie refresh).
    """
    try:
        from engine.nexus.cdp_auth_recovery import run_recovery
        status = run_recovery(keys_only=keys_only)
        result = {
            "healthy": status.healthy,
            "nlm_logged_in": status.nlm_logged_in,
            "aistudio_logged_in": status.aistudio_logged_in,
            "cookies_saved": status.cookies_saved,
            "working_keys": len(status.working_api_keys),
            "keys_updated": status.keys_updated,
            "harvested": len(status.harvested_keys),
            "duration_s": round(status.duration_s, 1),
            "summary": status.summary(),
        }
        if status.errors:
            result["errors"] = status.errors
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc), "healthy": False})
