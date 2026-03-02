from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from engine.mcp.decorators import mcp_tool, ToolExecutionError

class SystemStatusResponse(BaseModel):
    version: str
    services: Dict[str, Any]
    scenes: Dict[str, Any]
    skills: Dict[str, Any]
    config: Dict[str, Any]

@mcp_tool
def system_status_impl(nexus_getter: Any, config_getter: Any) -> SystemStatusResponse:
    status = {"version": "0.72", "services": {}, "scenes": {}, "skills": {}, "config": {}}

    try:
        cfg = config_getter()
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

    nx = nexus_getter()
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

    return SystemStatusResponse(**status)


class SkillInfoResponse(BaseModel):
    name: str
    description: str
    pack: str
    cooldown: int
    parameters: Dict[str, Any]

@mcp_tool
def get_skill_info_impl(skill_name: str) -> SkillInfoResponse:
    from engine.skills.registry import SKILL_REGISTRY
    desc = SKILL_REGISTRY.describe()
    if skill_name not in desc:
        raise ToolExecutionError(f"Skill '{skill_name}' not found")
    meta = desc[skill_name]
    return SkillInfoResponse(
        name=skill_name,
        description=meta.get("description", ""),
        pack=meta.get("pack", "unknown"),
        cooldown=meta.get("cooldown", 0),
        parameters=meta.get("parameters", {})
    )

class ListSkillsResponse(BaseModel):
    packs: Dict[str, List[Dict[str, Any]]]
    total_skills: int
    total_packs: int

@mcp_tool
def list_all_skills_impl() -> ListSkillsResponse:
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
    return ListSkillsResponse(
        packs=packs_map,
        total_skills=sum(len(v) for v in packs_map.values()),
        total_packs=len(packs_map)
    )
