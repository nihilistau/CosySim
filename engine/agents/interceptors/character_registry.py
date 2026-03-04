"""Interceptor: CharacterRegistryInterceptor.

Split from engine/agents/interceptors.py by scripts/hindsight/split_interceptors.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)
from engine.agents.interceptors.cache import INTERCEPTOR_CACHE  # noqa: F401

logger = logging.getLogger(__name__)

class CharacterRegistryInterceptor(InterceptorBase):
    """
    Runs BEFORE all scene interceptors (priority 8).

    pre_call
    --------
    1. Ensures the active character has a registry entry (auto-creates a stub
       if not found).
    2. Injects a compact character-summary block into the system prompt so the
       LLM always knows its own name, mood, personality, and active skills.
    3. Loads the full personality profile from the simulation DB for rich
       backstory, speech patterns, and behavioral traits.
    4. Checks the DialogSystem for a ``force_response`` directive — if one is
       active it short-circuits the LLM call by writing the forced reply
       directly into ctx["reply"] and setting ctx["skip_llm"] = True.

    This makes the registry the authoritative first step for every agent turn.
    """
    name     = "character_registry"
    priority = 8

    @staticmethod
    def _load_personality_profile(agent_id: str) -> str:
        """Load full personality profile from simulation DB."""
        try:
            from content.simulation.database.db import Database
            db = Database()
            # Try to find character in DB
            char = db.get_character(agent_id)
            if not char:
                return ""

            parts = []
            personality_id = char.get("personality_id") or char.get("personality")
            if personality_id:
                profile = db.get_personality(personality_id)
                if profile:
                    if profile.get("backstory"):
                        parts.append(f"Backstory: {profile['backstory'][:300]}")
                    if profile.get("speech_patterns"):
                        parts.append(f"Speech style: {profile['speech_patterns']}")
                    if profile.get("traits"):
                        traits = profile["traits"] if isinstance(profile["traits"], str) else ", ".join(profile["traits"])
                        parts.append(f"Core traits: {traits}")
                    if profile.get("quirks"):
                        parts.append(f"Quirks: {profile['quirks']}")
                    if profile.get("interests"):
                        parts.append(f"Interests: {profile['interests']}")

            # Character-level overrides
            if char.get("backstory") and not any("Backstory" in p for p in parts):
                parts.append(f"Backstory: {char['backstory'][:300]}")
            if char.get("description"):
                parts.append(f"Description: {char['description'][:200]}")

            if parts:
                return "--- Personality Profile ---\n" + "\n".join(parts)
        except Exception as exc:
            logger.debug("_load_personality_profile failed for %s: %s", agent_id, exc)
        return ""

    def pre_call(self, ctx: ResponseContext) -> None:
        agent_id = ctx.get("agent_id", "")
        if not agent_id:
            return

        try:
            from engine.mcp.character_registry import get_character_registry, apply_default_skills
            reg = get_character_registry()
            reg.ensure(agent_id)

            # One-time: apply default skills if the character has none yet
            existing = reg.get_skills(agent_id, enabled_only=False)
            if not existing:
                apply_default_skills(agent_id)

            summary = reg.get_character_summary(agent_id)
            if summary:
                mood       = summary.get("mood", "neutral")
                intensity  = float(summary.get("mood_intensity", 0.5))
                lines = [
                    "[CHARACTER IDENTITY]",
                    f"Name: {summary.get('name', agent_id)}",
                ]
                if mood:
                    lines.append(f"Current mood: {mood} (intensity {intensity:.0%})")
                if summary.get("top_traits"):
                    lines.append(f"Personality: {summary['top_traits']}")
                voice = summary.get("voice_style")
                if voice:
                    lines.append(f"Voice style: {voice}")
                if summary.get("restrictions"):
                    lines.append(f"Current restrictions: {', '.join(summary['restrictions'])}")
                auto_skills = summary.get("active_skills", [])
                if auto_skills:
                    lines.append(f"Active skills: {', '.join(auto_skills)}")

                # Load full personality profile from simulation DB (cached)
                cached_profile = INTERCEPTOR_CACHE.get(agent_id, "personality_profile")
                if cached_profile is None:
                    cached_profile = self._load_personality_profile(agent_id)
                    if cached_profile:
                        INTERCEPTOR_CACHE.set(agent_id, "personality_profile", cached_profile, ttl=300.0)
                if cached_profile:
                    lines.append(cached_profile)

                # Inject behavioral tags from StateCoordinator
                try:
                    from engine.mcp.state_coordinator import get_coordinator
                    coord = get_coordinator()
                    tags = coord.get_top_tags(agent_id, n=5)
                    perms = coord.get_permanent_tags(agent_id)
                    if tags:
                        perm_set = set(perms)
                        labeled = []
                        for t in tags:
                            labeled.append(f"{t} (core)" if t in perm_set else t)
                        lines.append(f"Behavioral tags: {', '.join(labeled)}")
                except Exception:
                    logger.debug("Suppressed exception", exc_info=True)

                lines.append("[/CHARACTER IDENTITY]")
                block = "\n".join(lines)
                ctx["system_prompt"] = block + "\n\n" + ctx.get("system_prompt", "")

        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor pre_call failed: %s", exc)
            return

        # ── Register character with MCPFramework + scene tracking ────
        try:
            scene = ctx.get("scene", "")
            from engine.mcp.framework import get_framework
            fw   = get_framework()
            char_node = fw.get_character(agent_id)
            if scene and char_node.current_scene != scene:
                char_node.enter_scene(scene)
        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor framework enter_scene failed: %s", exc)

        # ── Check for force_response directive ──────────────────────
        try:
            scene = ctx.get("scene", "")
            from engine.mcp.dialog_system import get_dialog_system
            ds = get_dialog_system()
            directive = ds.get_active_directive(agent_id, scene)
            if directive and directive.get("directive_type") == "force_response":
                forced = directive.get("value", "")
                if forced:
                    ctx["reply"]     = forced
                    ctx["skip_llm"]  = True
                    ds.consume_directive(agent_id, scene)
                    logger.debug("CharacterRegistryInterceptor: force_response applied for %s", agent_id)
        except Exception as exc:
            logger.debug("CharacterRegistryInterceptor directive check failed: %s", exc)
