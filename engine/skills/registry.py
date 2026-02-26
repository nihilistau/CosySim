"""
registry.py — Global skill registry and pack discovery helpers

The ``SKILL_REGISTRY`` singleton is the single source of truth for all
registered skills.  Skills are registered at import time via the ``@skill``
decorator.  Callers query the registry to retrieve tools for a given pack,
all tools, or tools filtered by tag.

Module-level helpers (``get_skills``, ``get_pack_tools``, ``mcp_skill_pack``)
delegate to the singleton so callers do not need to import the class directly.

MCP integration
---------------
``mcp_skill_pack(server_url, allowed_tools)`` returns an ``integrations``
payload dict compatible with the LMStudio Python SDK v1 ``act()`` call::

    from engine.skills import mcp_skill_pack, get_pack_tools

    # Mix local skills with an MCP server
    tools = get_pack_tools("comfyui")         # local callables
    mcp   = mcp_skill_pack("ws://...", [])    # all MCP tools

    prediction = llm.act(prompt, tools, integrations=[mcp])
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, List, Optional

from .skill import SkillMeta, SkillCategory, COOLDOWN_TRACKER

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Thread-safe registry that maps pack names → lists of SkillMeta.

    Usage::

        from engine.skills.registry import SKILL_REGISTRY

        SKILL_REGISTRY.register(meta)           # done by @skill decorator
        tools = SKILL_REGISTRY.get_pack_tools("comfyui")
        all   = SKILL_REGISTRY.all_tools()
    """

    def __init__(self) -> None:
        self._lock:   threading.Lock                  = threading.Lock()
        self._skills: Dict[str, List[SkillMeta]]      = {}  # pack → [SkillMeta]
        self._by_name: Dict[str, SkillMeta]           = {}  # name → SkillMeta

    # ──────────────────────────────────────────────────── write ──

    def register(self, meta: SkillMeta) -> None:
        """
        Register a SkillMeta instance.

        Called automatically by the ``@skill`` decorator.  Re-registering with
        the same name replaces the previous entry and logs a warning.
        """
        with self._lock:
            if meta.name in self._by_name:
                logger.warning(
                    "Skill %r registered twice — overwriting previous entry from pack %r",
                    meta.name,
                    self._by_name[meta.name].pack,
                )
            self._by_name[meta.name] = meta
            self._skills.setdefault(meta.pack, [])
            # Replace if already registered under same pack+name
            self._skills[meta.pack] = [
                m for m in self._skills[meta.pack] if m.name != meta.name
            ]
            self._skills[meta.pack].append(meta)
            logger.debug("Registered skill: %r in pack %r", meta.name, meta.pack)
        # Publish to ActivityBus (best-effort — may be called before bus is ready)
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type="skill_registered",
                description=f"Skill '{meta.name}' registered in pack '{meta.pack}'",
                agent_id="skill_registry",
                scene="system",
                data={"skill": meta.name, "pack": meta.pack, "tags": meta.tags},
            )
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    # ──────────────────────────────────────────────────── read ──

    def get_pack_tools(self, pack: str) -> List[Callable]:
        """Return a list of raw callables for all skills in *pack*."""
        with self._lock:
            return [m.func for m in self._skills.get(pack, [])]

    def get_pack_metas(self, pack: str) -> List[SkillMeta]:
        """Return a list of SkillMeta for all skills in *pack*."""
        with self._lock:
            return list(self._skills.get(pack, []))

    def get_pack_meta(self, pack: str) -> List[SkillMeta]:
        """Alias for get_pack_metas (backward compat)."""
        return self.get_pack_metas(pack)

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """Return SkillMeta by skill *name*, or None."""
        with self._lock:
            return self._by_name.get(name)

    def all_tools(self, *, tags: Optional[List[str]] = None) -> List[Callable]:
        """
        Return all registered skill callables.

        Args:
            tags: If provided, filter to skills that have *all* specified tags.
        """
        with self._lock:
            metas = [m for metas in self._skills.values() for m in metas]
        if tags:
            metas = [m for m in metas if all(t in m.tags for t in tags)]
        return [m.func for m in metas]

    def all_packs(self) -> List[str]:
        """Return a sorted list of registered pack names."""
        with self._lock:
            return sorted(self._skills.keys())

    def describe(self) -> Dict[str, List[Dict]]:
        """
        Return a nested dict suitable for admin / diagnostic display::

            {
                "comfyui": [{"name": "generate_image", "description": "..."}],
                ...
            }
        """
        with self._lock:
            return {
                pack: [{"name": m.name, "description": m.description, "tags": m.tags}
                       for m in metas]
                for pack, metas in self._skills.items()
            }

    def mcp_manifest(self) -> List[Dict]:
        """Flat list of all skills for MCP admin / tool discovery panels."""
        with self._lock:
            return [
                {
                    "name":        m.name,
                    "pack":        m.pack,
                    "description": m.description,
                    "tags":        m.tags,
                    "category":    m.category,
                    "cooldown":    m.cooldown_secs,
                    "cost":        m.cost,
                    "prerequisites": m.prerequisites,
                }
                for metas in self._skills.values()
                for m in metas
            ]

    def get_by_category(self, category: str) -> List[SkillMeta]:
        """Return all skills matching a category."""
        with self._lock:
            return [
                m for metas in self._skills.values()
                for m in metas if m.category == category
            ]

    def get_available(self, *, tags: Optional[List[str]] = None, category: str = "") -> List[SkillMeta]:
        """Return skills that are off cooldown and match filters."""
        with self._lock:
            metas = [m for metas_list in self._skills.values() for m in metas_list]
        if tags:
            metas = [m for m in metas if all(t in m.tags for t in tags)]
        if category:
            metas = [m for m in metas if m.category == category]
        # Filter by cooldown
        return [m for m in metas if COOLDOWN_TRACKER.can_use(m.name, m.cooldown_secs)]

    def execute_skill(self, name: str, *args, **kwargs) -> Any:
        """
        Execute a skill by name with cooldown enforcement.

        Raises ValueError if skill not found, RuntimeError if on cooldown.
        """
        meta = self.get_skill(name)
        if not meta:
            raise ValueError(f"Skill '{name}' not found")
        if not COOLDOWN_TRACKER.can_use(meta.name, meta.cooldown_secs):
            remaining = COOLDOWN_TRACKER.get_remaining(meta.name, meta.cooldown_secs)
            raise RuntimeError(f"Skill '{name}' on cooldown ({remaining:.1f}s remaining)")
        result = meta.func(*args, **kwargs)
        COOLDOWN_TRACKER.mark_used(meta.name)
        return result

    def __len__(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._skills.values())

    def __repr__(self) -> str:
        return f"<SkillRegistry {len(self)} skills across {len(self.all_packs())} packs>"


# ──────────────────────────────────────────────── global instance ──

SKILL_REGISTRY = SkillRegistry()

# ────────────────────────────────────────────── module-level API ──


def get_skills(pack: Optional[str] = None, *, tags: Optional[List[str]] = None) -> List[Callable]:
    """
    Retrieve skill callables from the global registry.

    Args:
        pack: If provided, return only skills from this pack.
        tags: If provided, filter to skills that have all specified tags.

    Returns:
        List of callables ready for ``lmstudio.llm().act()``.
    """
    if pack is not None:
        tools = SKILL_REGISTRY.get_pack_tools(pack)
        if tags:
            metas = SKILL_REGISTRY.get_pack_meta(pack)
            tools = [m.func for m in metas if all(t in m.tags for t in tags)]
        return tools
    return SKILL_REGISTRY.all_tools(tags=tags)


def get_pack_tools(pack: str) -> List[Callable]:
    """Convenience alias for ``SKILL_REGISTRY.get_pack_tools(pack)``."""
    return SKILL_REGISTRY.get_pack_tools(pack)


def mcp_skill_pack(
    server_url: str,
    allowed_tools: Optional[List[str]] = None,
    *,
    name: Optional[str] = None,
) -> Dict:
    """
    Build an MCP server payload for ``lmstudio.llm().act(integrations=...)``.

    The LMStudio Python SDK v1 accepts an ``integrations`` list where each
    entry describes an MCP (Model Context Protocol) server.  This helper
    constructs the correct payload dict.

    Args:
        server_url:     WebSocket URL of the MCP server (e.g. ``"ws://127.0.0.1:3001"``).
        allowed_tools:  If provided, only expose these tool names from the server.
                        Pass an empty list ``[]`` to allow all tools.
        name:           Optional human-readable label for the server.

    Returns:
        Dict payload suitable for inclusion in ``integrations`` list.

    Example::

        from engine.skills import mcp_skill_pack, get_pack_tools

        tools = get_pack_tools("comfyui")
        mcp   = mcp_skill_pack("ws://127.0.0.1:3001", [])
        reply = llm.act("Draw a sunset", tools, integrations=[mcp])
    """
    payload: Dict = {"type": "mcp", "url": server_url}
    if name:
        payload["name"] = name
    if allowed_tools is not None:
        payload["allowed_tools"] = allowed_tools
    return payload
