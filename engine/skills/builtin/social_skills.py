"""
social_skills.py — Social and environment skills for MCP framework
===================================================================

Skills for mood contagion, relationship management, environment changes,
and scene broadcasting.  These are the "social fabric" skills that make
multi-agent scenes feel alive.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  SOCIAL SKILLS
# ══════════════════════════════════════════════════════════════════════

@skill(
    pack="social",
    description="Spread a mood from one character to nearby characters in the same scene",
    category=SkillCategory.SOCIAL,
    tags=["mood", "contagion", "multi-agent"],
    cooldown=10.0,
)
def mood_contagion(
    source_character_id: str,
    mood: str,
    intensity: float = 0.5,
    scene_id: str = "",
) -> str:
    """
    Apply mood contagion: characters near source_character absorb the mood.

    intensity: 0.0–1.0, how strongly nearby characters are affected.
    """
    try:
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        fw = get_framework()
        ssm = get_scene_state_manager()
        char_node = fw.get_character(source_character_id)
        scene = scene_id or char_node.current_scene or ""
        if not scene:
            return "Character is not in a scene."

        affected = []
        for cid in fw.get_characters_in_scene(scene):
            if cid == source_character_id:
                continue
            delta = int(intensity * 20)
            ssm.update_stats(cid, **{mood: delta})
            affected.append(cid)

        fw.emit_event("mood_contagion", {
            "source": source_character_id, "mood": mood,
            "intensity": intensity, "affected": affected,
        }, source=scene)

        if affected:
            return f"Mood '{mood}' spread from {source_character_id} to {', '.join(affected)} (intensity={intensity})"
        return f"No other characters in scene '{scene}' to affect."
    except Exception as exc:
        return f"Mood contagion failed: {exc}"


@skill(
    pack="social",
    description="Adjust the relationship strength between two characters",
    category=SkillCategory.SOCIAL,
    tags=["relationship", "trust", "bond"],
    cooldown=5.0,
)
def relationship_adjust(
    character_a: str,
    character_b: str,
    dimension: str = "trust",
    delta: float = 5.0,
) -> str:
    """
    Adjust a relationship dimension between two characters.

    Dimensions: trust, affection, tension, intimacy, rivalry.
    Delta: positive = strengthen, negative = weaken.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.framework import get_framework

        reg = get_character_registry()
        # Update both directions
        for a, b in [(character_a, character_b), (character_b, character_a)]:
            rec = reg.get_record(a)
            if rec and hasattr(rec, 'state') and rec.state:
                relationships = getattr(rec.state, 'relationships', {})
                if not isinstance(relationships, dict):
                    relationships = {}
                rel = relationships.get(b, {})
                current = rel.get(dimension, 50.0)
                rel[dimension] = max(0, min(100, current + delta))
                relationships[b] = rel
                rec.state.relationships = relationships

        get_framework().emit_event("relationship_adjusted", {
            "character_a": character_a, "character_b": character_b,
            "dimension": dimension, "delta": delta,
        })
        return f"Relationship {dimension} between {character_a} and {character_b} adjusted by {delta:+.1f}"
    except Exception as exc:
        return f"Relationship adjust failed: {exc}"


@skill(
    pack="social",
    description="Broadcast a message to all characters in a scene",
    category=SkillCategory.COMMUNICATION,
    tags=["broadcast", "scene", "announcement"],
)
def scene_broadcast(
    scene_id: str,
    message: str,
    sender: str = "narrator",
    message_type: str = "narration",
) -> str:
    """Broadcast a narrative message or announcement to all characters in a scene."""
    try:
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        fw = get_framework()
        scene = fw.get_scene(scene_id)
        present = scene.get_present()

        # Add to scene narrative
        get_scene_state_manager().add_narrative(
            scene_id, message,
            entry_type=message_type, character_id=sender,
        )

        # Inject into each character's inbox
        from engine.mcp.comms_framework import get_router
        router = get_router()
        for cid in present:
            router.send(cid, f"[{sender}]: {message}")

        fw.emit_event("scene_broadcast", {
            "scene_id": scene_id, "sender": sender,
            "message": message[:100], "recipients": present,
        }, source=scene_id)

        return f"Broadcast to {len(present)} characters in '{scene_id}': {message[:60]}..."
    except Exception as exc:
        return f"Broadcast failed: {exc}"


# ══════════════════════════════════════════════════════════════════════
#  ENVIRONMENT SKILLS
# ══════════════════════════════════════════════════════════════════════

@skill(
    pack="environment",
    description="Change the environment of a scene (lighting, music, props, atmosphere)",
    category=SkillCategory.ENVIRONMENT,
    tags=["atmosphere", "lighting", "ambiance"],
    cooldown=15.0,
)
def environment_change(
    scene_id: str,
    change_type: str,
    value: str,
    description: str = "",
) -> str:
    """
    Apply an environment change to a scene.

    change_type: lighting | music | temperature | prop_add | prop_remove | atmosphere
    value: the new state (e.g., "dim candles", "jazz playlist", "warm")
    """
    try:
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        fw = get_framework()
        ssm = get_scene_state_manager()

        narrative = description or f"The {change_type} changes: {value}"
        ssm.add_narrative(scene_id, narrative, entry_type="environment")

        # Emit event for UI/frontend to react
        fw.emit_event("environment_change", {
            "scene_id": scene_id, "change_type": change_type,
            "value": value, "description": narrative,
        }, source=scene_id)

        return f"Environment change in '{scene_id}': {change_type} → {value}"
    except Exception as exc:
        return f"Environment change failed: {exc}"


@skill(
    pack="environment",
    description="Get the current state of a scene's environment and atmosphere",
    category=SkillCategory.ENVIRONMENT,
    tags=["status", "scene", "state"],
)
def get_scene_snapshot(scene_id: str) -> str:
    """Return a text snapshot of a scene: who's present, recent events, atmosphere."""
    try:
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        fw = get_framework()
        scene = fw.get_scene(scene_id)
        ssm = get_scene_state_manager()

        present = scene.get_present()
        narrative = ssm.get_narrative(scene_id, limit=5)
        recent = scene.get_event_log(limit=5)

        lines = [f"Scene: {scene_id}"]
        lines.append(f"Present: {', '.join(present) if present else 'empty'}")
        if narrative:
            lines.append("Recent narrative:")
            for entry in narrative:
                text = entry if isinstance(entry, str) else entry.get("text", str(entry))
                lines.append(f"  • {text[:80]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Scene snapshot failed: {exc}"


# ══════════════════════════════════════════════════════════════════════
#  NARRATIVE SKILLS
# ══════════════════════════════════════════════════════════════════════

@skill(
    pack="narrative",
    description="Inject a story beat or plot point into a scene's narrative",
    category=SkillCategory.NARRATIVE,
    tags=["story", "plot", "director"],
    cooldown=20.0,
)
def inject_story_beat(
    scene_id: str,
    beat: str,
    character_id: str = "",
    urgency: str = "normal",
) -> str:
    """
    Inject a narrative beat that characters will react to.

    urgency: low | normal | high | critical
    """
    try:
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        fw = get_framework()
        ssm = get_scene_state_manager()

        ssm.add_narrative(scene_id, beat, entry_type="story_beat", character_id=character_id)
        fw.emit_event("story_beat", {
            "scene_id": scene_id, "beat": beat,
            "character_id": character_id, "urgency": urgency,
        }, source=scene_id)

        return f"Story beat injected into '{scene_id}' (urgency={urgency}): {beat[:80]}"
    except Exception as exc:
        return f"Story beat injection failed: {exc}"


@skill(
    pack="narrative",
    description="Get dialog options contextually appropriate for the current scene state",
    category=SkillCategory.NARRATIVE,
    tags=["dialog", "options", "choice"],
)
def get_dialog_options(
    character_id: str,
    scene_id: str,
    context_tags: str = "",
) -> str:
    """Return contextual dialog options for a character in a scene."""
    try:
        from engine.mcp.dialog_system import get_dialog_system
        ds = get_dialog_system()
        tags = [t.strip() for t in context_tags.split(",") if t.strip()] if context_tags else []
        options = ds.get_options(character_id, scene_id, context_tags=tags)
        if not options:
            return "No specific dialog options available — character can speak freely."
        lines = ["Available dialog options:"]
        for opt in options:
            label = opt.get("label", "")
            text = opt.get("text", "")
            lines.append(f"  • [{label}] {text[:60]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Dialog options failed: {exc}"
