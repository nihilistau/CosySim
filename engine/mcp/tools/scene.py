"""MCP tool domain: scene.

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

# ──── SCENE TOOLS ────────────────────────────────────────────────────────


@mcp_tool
def add_scene_narrative(
    scene_id: str,
    event: str,
    character_id: str = "",
    entry_type: str = "action",
) -> str:
    """
    Add an event to the scene's rolling narrative log.  This is the continuity
    system — use it to record important moments, actions, dialogue, and
    environmental changes so the story remains consistent.

    entry_type: 'action' | 'dialogue' | 'environment' | 'system'

    Examples:
      "Maya removes her silk robe and lets it fall."
      "The Director dims the lights to red."
      "Aria admits she's been thinking about him all day."
    """
    try:
        from engine.mcp.tools.scene_tools import add_scene_narrative as _impl
        return _impl(scene_id, event, character_id=character_id, entry_type=entry_type)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_scene_narrative(scene_id: str, limit: int = 20) -> str:
    """
    Read the last N entries from the scene's narrative log.
    Use this to maintain continuity — know what has already happened.

    Returns a text summary and a structured list of entries.
    Always call this at scene start and after resuming a paused session.
    """
    try:
        from engine.mcp.tools.scene_tools import get_scene_narrative as _impl
        return _impl(scene_id, limit)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_full_scene_snapshot(scene_id: str, character_ids: str = "") -> str:
    """
    Get a complete snapshot of the scene state — all characters' stats, wardrobes,
    emotional states, current timed actions, atmosphere, and recent narrative.

    character_ids: comma-separated list, or blank to include all known characters.

    Use this at scene start, after a skip, or to ground your response in the
    current reality of the room.  This is your oracle.
    """
    try:
        from engine.mcp.tools.scene_tools import get_full_scene_snapshot as _impl
        return _impl(scene_id, character_ids)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def set_scene_atmosphere(
    scene_id: str,
    lighting: str = "",
    mood: str = "",
    music: str = "",
    temperature: str = "",
    props_present: str = "",
    note: str = "",
) -> str:
    """
    Set the atmosphere of a scene.  All parameters are optional strings —
    describe the vibe you want.

    lighting: 'candlelight' | 'red_light' | 'dim' | 'bright' | custom string
    mood:     'romantic' | 'playful' | 'tense' | 'relaxed' | 'electric' | custom
    music:    'jazz' | 'no music' | 'soft pop' | custom
    temperature: 'warm' | 'hot' | 'cool' | custom
    props_present: comma-separated items visible in room
    note: any additional atmosphere detail

    This is written into the narrative log and returned to agents via
    get_full_scene_snapshot().
    """
    try:
        from engine.mcp.tools.scene_tools import set_scene_atmosphere as _impl
        return _impl(scene_id, lighting=lighting, mood=mood, music=music,
                     temperature=temperature, props_present=props_present, note=note)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_scene_rules(scene_id: str) -> str:
    """
    Return the full rules reference for a scene in human-readable form.
    Inject this into your system prompt at scene start to understand what
    is expected, what is forbidden, and what the Director can activate.

    Args:
        scene_id: e.g. "bedroom" or "phone"
    """
    try:
        from engine.mcp.tools.scene_tools import get_scene_rules as _impl
        return _impl(scene_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_scene_available_actions(
    scene_id: str,
    character_id: str,
    stats_json: str = "{}",
    scene_state_json: str = "{}",
) -> str:
    """
    Return all actions available to a character in a scene right now,
    filtered by their current stats and the scene's permission matrix.

    Args:
        scene_id:         e.g. "bedroom"
        character_id:     e.g. "aria"
        stats_json:       JSON dict of current stats
        scene_state_json: JSON dict of scene state flags
    """
    try:
        from engine.mcp.tools.scene_tools import get_scene_available_actions as _impl
        return _impl(scene_id, character_id, stats_json=stats_json,
                     scene_state_json=scene_state_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def apply_scene_rule(
    scene_id: str,
    rule_id: str,
    target_ids_json: str = "[]",
    issuer: str = "director",
) -> str:
    """
    Apply a named Director rule immediately — fires all its effects on the
    target characters.  Can be used to set atmosphere, issue directives,
    adjust stats, etc. via a single memorable rule name.

    Examples: "bedroom_lights_off", "bedroom_mood_lift", "phone_escalate"

    Args:
        scene_id:        Scene the rule belongs to
        rule_id:         Rule identifier
        target_ids_json: JSON list of target character IDs
        issuer:          Who triggered this (for audit)
    """
    try:
        from engine.mcp.tools.scene_tools import apply_scene_rule as _impl
        return _impl(scene_id, rule_id, target_ids_json=target_ids_json, issuer=issuer)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_scene_rules_summary(scene_id: str, character_id: str = "") -> str:
    """
    **SCENE INTELLIGENCE SUMMARY** — Complete scene rules + actions + character
    capabilities in a single call.  This is the "what can I do right now?" tool.

    Returns:
    - All active rules for the scene
    - Every available action for this character (with availability status)
    - Current conversation heat and any active directive
    - Character skills active in this context

    Call this at scene start or when you're unsure what's appropriate.

    Args:
        scene_id:     e.g. "bedroom" or "phone"
        character_id: The character you're working with
    """
    try:
        from engine.mcp.tools.scene_tools import get_scene_rules_summary as _impl
        return _impl(scene_id, character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_framework_status() -> str:
    """
    Return a full MCPFramework status snapshot: active scenes, characters,
    timers, and pending consequence chains.  Use as a Director overview.
    """
    try:
        from engine.mcp.tools.utility_tools import get_framework_status_logic as _impl
        return _impl()
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def mood_contagion(
    scene_id:         str,
    initiator_id:     str,
    emotion:          str,
    intensity:        float = 0.6,
    target_ids_json:  str   = "[]",
    affinity_factor:  float = 1.0,
) -> str:
    """
    **MOOD CONTAGION** — Spread an emotional state from one character to others
    in the same scene.

    Mood contagion is realistic: high-affinity characters absorb more mood.
    Characters with restrictions or high inhibition resist.  The spread is
    scaled by intensity (0.0→1.0) and the affinity_factor (how close they are).

    This is physics for emotion.  Use it when:
    - One character laughing makes others smile
    - Sadness fills the room after a confession
    - Dominant mood overtakes submissive character
    - Tension spikes because one person is visibly aroused

    The tool adjusts mood state in CharacterRegistry and optionally biases
    stats.  It logs the contagion event to the scene narrative.

    Emotions:
      excited, aroused, tender, warm, sad, nervous, dominant, submissive,
      playful, serious, angry, fearful, joyful, vulnerable, charged

    Args:
        scene_id:        Scene where contagion occurs
        initiator_id:    Character whose mood is spreading
        emotion:         The emotion/mood spreading
        intensity:       How strongly it spreads (0.0 = no effect, 1.0 = full)
        target_ids_json: JSON list of target char IDs (empty = all present in scene)
        affinity_factor: Multiplier for closeness (1.0 = normal, 2.0 = very close)
    """
    try:
        import json as _json
        from engine.mcp.character_registry import get_character_registry
        from engine.mcp.framework import get_framework
        from engine.mcp.scene_state import get_scene_state_manager

        target_ids: List[str] = _json.loads(target_ids_json) if target_ids_json and target_ids_json != "[]" else []

        # If no targets specified, get everyone present in the scene
        if not target_ids:
            target_ids = get_framework().get_characters_in_scene(scene_id)
            target_ids = [c for c in target_ids if c != initiator_id]

        reg     = get_character_registry()
        ssm     = get_scene_state_manager()
        applied = []

        # Emotion → stat impact mapping
        _EMOTION_STATS: Dict[str, Dict[str, float]] = {
            "excited":    {"happiness":  0.3, "arousal":  0.2},
            "aroused":    {"arousal":    0.5, "openness": 0.15},
            "tender":     {"affection":  0.4, "happiness": 0.2},
            "warm":       {"happiness":  0.35, "affection": 0.2},
            "sad":        {"happiness": -0.4},
            "nervous":    {"fear":       0.3, "arousal":  0.1},
            "dominant":   {"inhibition": -0.2, "openness": 0.1},
            "submissive": {"inhibition":  0.2, "openness": 0.2},
            "playful":    {"happiness":  0.3, "arousal":  0.1},
            "serious":    {"happiness": -0.1},
            "angry":      {"fear":       0.2, "happiness": -0.3},
            "fearful":    {"fear":       0.5},
            "joyful":     {"happiness":  0.5, "arousal":  0.15},
            "vulnerable": {"affection":  0.3, "openness":  0.25},
            "charged":    {"arousal":    0.4, "openness":  0.2},
        }
        stat_impacts = _EMOTION_STATS.get(emotion, {"happiness": 0.1})

        for target_id in target_ids:
            try:
                reg.ensure(target_id)
                state = reg.get_state(target_id)
                # Check inhibition resistance
                inhibition = getattr(state, "inhibition", 0.3)
                resistance = inhibition * 0.5
                effective  = max(0.0, intensity * affinity_factor * (1.0 - resistance))

                # Set mood state
                reg.set_state(target_id, mood=emotion, mood_intensity=effective)

                # Apply stat impacts
                for stat, delta_factor in stat_impacts.items():
                    delta = delta_factor * effective * 100  # scale to stat points
                    try:
                        ssm.update_stats(target_id, **{stat: delta})
                    except Exception:
                        logger.debug("Suppressed exception", exc_info=True)

                applied.append({
                    "target":                  target_id,
                    "mood_set":                emotion,
                    "effective_intensity":     round(effective, 2),
                    "resistance":              round(resistance, 2),
                    "inhibition":              round(inhibition, 2),
                })
            except Exception as te:
                applied.append({"target": target_id, "error": str(te)})

        # Narrative
        narrative = (f"{initiator_id}'s {emotion} mood spreads through the room "
                     f"(intensity: {intensity:.0%})")
        ssm.add_narrative(scene_id, narrative, entry_type="mood_contagion",
                          character_id=initiator_id)

        return json.dumps({
            "ok":         True,
            "initiator":  initiator_id,
            "emotion":    emotion,
            "intensity":  intensity,
            "affected":   applied,
            "narrative":  narrative,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
