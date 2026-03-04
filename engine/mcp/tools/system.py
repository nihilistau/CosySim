"""MCP tool domain: system.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── SYSTEM TOOLS ───────────────────────────────────────────────────────


@mcp_tool
def system_status() -> str:
    """Get comprehensive CosySim system status — services, models,
    scenes, skills, orchestrator, and Nexus connectivity."""
    status = {"version": "0.52b", "services": {}, "scenes": {}, "skills": {}}

    try:
        cfg = _get_config()
        status["config"] = {
            "lmstudio_url": cfg.get("lmstudio.base_url", "unknown"),
            "load_mode": cfg.get("lmstudio.load_mode", "unknown"),
        }
    except Exception:
        status["config"] = {"error": "unavailable"}

    try:
        from engine.lmstudio.lms_client import LMSClient
        client = LMSClient()
        models = client.get_models(loaded_only=False)
        loaded = client.get_models(loaded_only=True)
        status["services"]["lmstudio"] = {
            "available": True,
            "models_available": len(models) if models else 0,
            "models_loaded": len(loaded) if loaded else 0,
        }
    except Exception:
        status["services"]["lmstudio"] = {"available": False}

    nx = _get_nexus()
    if nx:
        try:
            status["services"]["nexus"] = {"available": nx.is_available()}
        except Exception:
            status["services"]["nexus"] = {"available": False}
    else:
        status["services"]["nexus"] = {"available": False}

    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        packs = SKILL_REGISTRY.all_packs()
        status["skills"] = {
            "total": len(desc),
            "packs": len(packs),
            "pack_names": sorted(packs),
        }
    except Exception:
        status["skills"] = {"error": "unavailable"}

    try:
        from engine.scenes.base_scene import BaseScene
        active = BaseScene.get_active_scenes() if hasattr(BaseScene, "get_active_scenes") else {}
        status["scenes"]["active"] = list(active.keys()) if active else []
    except Exception:
        status["scenes"]["active"] = []

    return json.dumps(status)


@mcp_tool
def list_all_skills() -> str:
    """List all registered MCP skills grouped by pack."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        packs_map: dict = {}
        for name, meta in desc.items():
            pack = meta.get("pack", "unknown")
            packs_map.setdefault(pack, []).append({
                "name": name,
                "description": meta.get("description", ""),
                "cooldown": meta.get("cooldown", 0),
            })
        return json.dumps({
            "packs": packs_map,
            "total_skills": sum(len(v) for v in packs_map.values()),
            "total_packs": len(packs_map),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_skill_info(skill_name: str) -> str:
    """Get detailed information about a specific MCP skill."""
    try:
        from engine.skills.registry import SKILL_REGISTRY
        desc = SKILL_REGISTRY.describe()
        if skill_name not in desc:
            return json.dumps({"error": f"Skill '{skill_name}' not found"})
        meta = desc[skill_name]
        return json.dumps({
            "name": skill_name,
            "description": meta.get("description", ""),
            "pack": meta.get("pack", "unknown"),
            "cooldown": meta.get("cooldown", 0),
            "parameters": meta.get("parameters", {}),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_benchmark_stats() -> str:
    """Get performance benchmark statistics."""
    try:
        from engine.mcp.tools.utility_tools import get_benchmark_stats_logic as _impl
        return _impl()
    except Exception as e:
        return json.dumps({"error": str(e)})
