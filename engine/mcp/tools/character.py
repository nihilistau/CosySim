"""MCP tool domain: character.

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

# ──── CHARACTER TOOLS ────────────────────────────────────────────────────


@mcp_tool
def get_character_state(character_id: str) -> str:
    """
    Get the current state of a character including mood, energy, and relationships.
    Returns JSON with all character state fields.
    """
    try:
        from engine.mcp.tools.character_tools import get_character_state as _impl
        return _impl(character_id, _get_db())
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def adjust_relationship(
    character_a: str,
    character_b: str,
    field: str,
    delta: float,
) -> str:
    """
    Adjust a relationship value between two characters.
    Fields: relationship_level, trust, attraction, arousal_a, arousal_b.
    Delta is added to current value (can be negative). Values clamped 0-1.
    """
    try:
        from engine.mcp.tools.character_tools import adjust_relationship as _impl
        return _impl(character_a, character_b, field, delta, _get_db())
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def list_characters() -> str:
    """
    List all characters in the database with their names and IDs.
    """
    try:
        from engine.mcp.tools.character_tools import list_characters as _impl
        return _impl(_get_db())
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def update_mood(
    character_id: str,
    mood:         str,
    reason:       str = "",
    intensity:    float = 0.5,
) -> str:
    """
    Update a character's current mood and optionally trigger emotional effects.
    mood options: 'happy', 'excited', 'sad', 'anxious', 'flirty', 'mysterious',
                  'playful', 'serious', 'irritated', 'loving', 'bored', 'curious'.
    intensity: float 0.0–1.0 (how strongly the mood is felt).
    reason: short string explaining what caused the mood change.
    Use this after an impactful event, a game result, or an emotional exchange.
    """
    db = _get_db()
    try:
        db.update_character_state(character_id, {
            "mood":           mood,
            "mood_intensity": max(0.0, min(1.0, intensity)),
            "mood_reason":    reason,
        })
        return f"Updated {character_id} mood → {mood} (intensity={intensity:.1f}). Reason: {reason}"
    except Exception as e:
        return f"Failed to update mood: {e}"


@mcp_tool
def apply_effect(
    character_id: str,
    effect_name:  str,
    value:        float = 0.1,
) -> str:
    """
    Apply a status effect to a character's state.
    Effects are additive deltas on personality/relationship fields.
    effect_name options: 'trust_boost', 'attraction_boost', 'trust_drop',
    'energise', 'deflate', 'excite', 'calm', 'curiosity_spike'.
    value: magnitude of the effect (0.0–1.0).
    """
    try:
        EFFECT_MAP = {
            "trust_boost":      {"trust": value},
            "trust_drop":       {"trust": -value},
            "attraction_boost": {"attraction": value},
            "energise":         {"arousal_a": value},
            "deflate":          {"arousal_a": -value},
            "excite":           {"arousal_a": value, "attraction": value * 0.5},
            "calm":             {"arousal_a": -value * 0.5},
            "curiosity_spike":  {"relationship_level": value * 0.3},
        }
        fields = EFFECT_MAP.get(effect_name)
        if not fields:
            return f"Unknown effect '{effect_name}'."
        db = _get_db()
        results = []
        for field, delta in fields.items():
            try:
                db.update_character_state(character_id, {field: delta})
                results.append(f"{field}+={delta:+.2f}")
            except Exception:
                logger.debug("Suppressed exception", exc_info=True)
        return f"Applied effect '{effect_name}' to {character_id}: {', '.join(results)}"
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def check_relationship(character_a: str, character_b: str) -> str:
    """
    Get a concise relationship summary between two characters.
    Returns trust, attraction, relationship level and a natural-language
    summary. Use this before making decisions that depend on relationship state.
    """
    db = _get_db()
    try:
        rel = db.get_or_create_relationship(character_a, character_b)
        if not rel:
            return f"No relationship found between {character_a} and {character_b}."
        r = dict(rel)
        trust    = float(r.get("trust", 0.5))
        attract  = float(r.get("attraction", 0.5))
        level    = float(r.get("relationship_level", 0.5))

        def _desc(v: float) -> str:
            if v >= 0.8: return "very high"
            if v >= 0.6: return "high"
            if v >= 0.4: return "moderate"
            if v >= 0.2: return "low"
            return "very low"

        summary = (
            f"Trust: {_desc(trust)}, "
            f"Attraction: {_desc(attract)}, "
            f"Bond: {_desc(level)}."
        )
        return json.dumps({"raw": r, "summary": summary}, indent=2, default=str)
    except Exception as e:
        return f"Failed to check relationship: {e}"


@mcp_tool
def get_character_scene_stats(character_id: str) -> str:
    """
    Get the full extended emotional/physical stat vector for a character in the
    current scene.

    Stats (all 0-100): arousal, horniness, pleasure, happiness, anger, fear,
    drunkenness, tiredness, explicitness, openness, affection, dominance.

    Also returns 'emotional_state' — a human-readable description of how the
    character is feeling right now.  USE THIS to inform how they should behave.
    """
    try:
        stats = _ssm().get_stats(character_id)
        wardrobe = _ssm().get_wardrobe(character_id)
        return json.dumps({
            "character_id":    character_id,
            "stats":           stats.to_dict(),
            "emotional_state": stats.emotional_state_text(),
            "wearing":         wardrobe.coverage_description(),
            "is_naked":        len(wardrobe.worn_items()) == 0,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def update_character_scene_stats(character_id: str, stat_changes: str) -> str:
    """
    Adjust a character's scene stats by delta values.  Pass a JSON string like:
    '{"arousal": 15, "happiness": -10, "openness": 5}'

    Stats clamp at 0-100.  Use positive values to increase, negative to decrease.
    Call this after interactions, events, emotional moments.
    """
    try:
        changes = json.loads(stat_changes) if isinstance(stat_changes, str) else stat_changes
    except Exception:
        return json.dumps({"error": "stat_changes must be valid JSON: {\"stat\": delta}"})
    _coord().update(character_id, source="mcp_tool", **changes)
    stats = _ssm().get_stats(character_id)
    return json.dumps({
        "updated": True,
        "character_id": character_id,
        "applied_changes": changes,
        "new_stats": stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
    }, indent=2)


@mcp_tool
def set_character_scene_stat(character_id: str, stat: str, value: float) -> str:
    """
    Set a specific stat to an exact value (0-100).  Use when you need precision
    rather than a delta — e.g. resetting a stat at scene start.

    stat: arousal | horniness | pleasure | happiness | anger | fear |
          drunkenness | tiredness | explicitness | openness | affection | dominance
    """
    try:
        _coord().update(character_id, mode="set", source="mcp_tool", **{stat: value})
        stats = _ssm().get_stats(character_id)
        return json.dumps({
            "set": True,
            "stat": stat,
            "value": getattr(stats, stat, None),
            "emotional_state": stats.emotional_state_text(),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def reset_character_scene_stats(character_id: str) -> str:
    """Reset all scene stats for a character back to defaults (scene reset / new character)."""
    try:
        stats = _ssm().reset_stats(character_id)
        return json.dumps({
            "reset": True,
            "character_id": character_id,
            "stats": stats.to_dict(),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def check_character_consent(character_id: str, action_type: str) -> str:
    """
    Check whether a character would willingly perform or receive an action
    based on their current stats.

    Returns a WILL/RELUCTANT/REFUSE decision and the reasoning.
    Characters CAN and SHOULD refuse sometimes — it creates drama.
    They might also take initiative and suggest something the Director didn't.

    action_type examples: 'striptease', 'kiss', 'sex', 'oral', 'cuddle',
                          'dirty_talk', 'remove_top', 'remove_all'
    """
    try:
        stats = _ssm().get_stats(character_id).to_dict()
        openness   = float(stats.get("openness", 65))
        arousal    = float(stats.get("arousal", 20))
        fear       = float(stats.get("fear", 5))
        anger      = float(stats.get("anger", 5))
        happiness  = float(stats.get("happiness", 60))
        affection  = float(stats.get("affection", 50))

        intimacy_map = {
            "cuddle": 20, "kiss": 30, "caress": 35,
            "dirty_talk": 45, "striptease": 50, "remove_top": 45,
            "remove_all": 60, "oral": 65, "foreplay": 55,
            "sex": 70, "role_play": 50, "submission": 65,
        }
        threshold = intimacy_map.get(action_type.lower(), 50)
        score = (openness * 0.4) + (arousal * 0.3) + (happiness * 0.15) + (affection * 0.15)
        score -= (fear * 0.4) + (anger * 0.3)

        if score >= threshold + 15:
            decision = "WILL"
            detail   = "enthusiastically willing — may even take the lead"
        elif score >= threshold:
            decision = "WILL"
            detail   = "willing, probably with some playful resistance"
        elif score >= threshold - 15:
            decision = "RELUCTANT"
            detail   = "hesitant but could be persuaded if approached well"
        else:
            decision  = "REFUSE"
            detail    = "refusing — this goes against current state or mood"

        return json.dumps({
            "character_id":  character_id,
            "action":        action_type,
            "decision":      decision,
            "detail":        detail,
            "score":         round(score, 1),
            "threshold":     threshold,
            "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
            "note": "REFUSE creates drama — lean into it. Negotiation and resistance are part of the scene.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def get_character_agency_summary(character_id: str) -> str:
    """
    Get a full picture of a character's current agency — who they are RIGHT NOW.
    Includes emotional state, compliance level, what they most want, what they'd
    resist, and what they might spontaneously initiate.

    Use this to write authentic agent responses that feel real rather than always-compliant.
    """
    try:
        stats = _ssm().get_stats(character_id).to_dict()
        wardrobe = _ssm().get_wardrobe(character_id)

        arousal    = float(stats.get("arousal", 20))
        openness   = float(stats.get("openness", 65))
        happiness  = float(stats.get("happiness", 60))
        horniness  = float(stats.get("horniness", 15))
        dominance  = float(stats.get("dominance", 50))
        affection  = float(stats.get("affection", 50))
        fear       = float(stats.get("fear", 5))
        anger      = float(stats.get("anger", 5))

        compliance = max(0, min(100, openness * 0.4 + happiness * 0.2 + arousal * 0.2 - fear * 0.3 - anger * 0.3))

        wants, resists, might_initiate = [], [], []
        if arousal > 60:     wants.append("physical closeness, touch, intimacy")
        if horniness > 50:   wants.append("explicitly sexual encounter")
        if happiness > 70:   wants.append("to share joy, laugh, play")
        if affection > 65:   wants.append("tender moments, to be seen and held")
        if fear > 40:        resists.append("unfamiliar or overwhelming actions")
        if anger > 40:       resists.append("being told what to do right now")
        if dominance > 65:   might_initiate.append("taking control of the scene")
        if dominance < 35:   might_initiate.append("asking permission, following lead")
        if arousal > 70 and horniness > 60:
            might_initiate.append("making the first bold move")
        if happiness > 75:   might_initiate.append("playful teasing or mischief")

        return json.dumps({
            "character_id":    character_id,
            "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
            "stats":           stats,
            "wearing":         wardrobe.coverage_description(),
            "compliance_score": round(compliance, 1),
            "compliance_label": (
                "highly compliant — will enthusiastically follow most directions" if compliance > 75 else
                "moderately open — willing with right approach" if compliance > 50 else
                "resistant — may push back or redirect" if compliance > 30 else
                "very resistant — has strong opinions right now"
            ),
            "wants":           wants if wants else ["to engage authentically with the scene"],
            "resists":         resists if resists else ["nothing in particular right now"],
            "might_spontaneously_initiate": might_initiate if might_initiate else ["following your lead"],
            "note": "Honour this — characters with free will are more interesting than yes-machines.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_register(
    character_id: str,
    name: str,
    age: int = 25,
    appearance_json: str = "{}",
    personality_json: str = "{}",
    backstory: str = "",
    voice_style: str = "natural",
    pronouns: str = "she/her",
    scene_roles_json: str = "{}",
) -> str:
    """
    Register a character in the central CharacterRegistry.
    Call this once per character at scene start.  Safe to call multiple times —
    it will auto-create a stub if the character doesn't exist yet.

    Args:
        character_id:     Unique key e.g. "aria" or "user"
        name:             Display name
        age:              Character age
        appearance_json:  JSON dict e.g. '{"hair": "dark", "eyes": "green"}'
        personality_json: JSON dict of 0-1 floats e.g. '{"openness": 0.8}'
        backstory:        Short backstory paragraph
        voice_style:      Speaking style e.g. "warm and literary"
        pronouns:         e.g. "she/her"
        scene_roles_json: JSON dict of scene → role  e.g. '{"bedroom": "lover"}'
    """
    try:
        from engine.mcp.tools.character_tools import character_register as _impl
        return _impl(character_id, name, age=age, appearance_json=appearance_json,
                     personality_json=personality_json, backstory=backstory,
                     voice_style=voice_style, pronouns=pronouns,
                     scene_roles_json=scene_roles_json)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_query(character_id: str, attribute: str) -> str:
    """
    Retrieve any attribute from a character's profile, state, or appearance.

    Args:
        character_id: e.g. "aria"
        attribute:    Any key: "name", "age", "mood", "arousal", "voice_style",
                      "hair", "eye_colour", "restrictions", "flags", etc.
    """
    try:
        from engine.mcp.tools.character_tools import character_query as _impl
        return _impl(character_id, attribute)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_set_attribute(
    character_id: str,
    attribute: str,
    value: str,
) -> str:
    """
    Set a mutable state attribute on a character.

    Supports: mood, mood_intensity, focus, current_role, energy, inhibition,
    or any arbitrary flag stored in character_flags.

    Args:
        character_id: e.g. "aria"
        attribute:    State field name
        value:        New value (will be coerced from string where possible)
    """
    try:
        from engine.mcp.tools.character_tools import character_set_attribute as _impl
        return _impl(character_id, attribute, value)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_get_summary(character_id: str) -> str:
    """
    Return a compact summary of a character's current identity, mood,
    personality, skills, and restrictions — ready for prompt injection.

    Args:
        character_id: e.g. "aria"
    """
    try:
        from engine.mcp.tools.character_tools import character_get_summary as _impl
        return _impl(character_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_assign_skill(
    character_id: str,
    skill_id: str,
    skill_type: str = "custom",
    label: str = "",
    params_json: str = "{}",
    trigger: str = "optional",
    priority: int = 50,
) -> str:
    """
    Assign a new skill to a character.

    Args:
        character_id: Character to receive the skill
        skill_id:     Unique skill identifier
        skill_type:   "memory" | "speech" | "action" | "query" | "custom"
        label:        Human-readable name
        params_json:  JSON dict of skill parameters
        trigger:      "auto" (always runs) | "optional" | "required"
        priority:     Execution priority (lower = earlier)
    """
    try:
        from engine.mcp.tools.character_tools import character_assign_skill as _impl
        return _impl(character_id, skill_id, skill_type=skill_type, label=label,
                     params_json=params_json, trigger=trigger, priority=priority)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_revoke_skill(character_id: str, skill_id: str) -> str:
    """
    Remove a skill from a character.

    Args:
        character_id: e.g. "aria"
        skill_id:     Skill to remove
    """
    try:
        from engine.mcp.tools.character_tools import character_revoke_skill as _impl
        return _impl(character_id, skill_id)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_get_skills(character_id: str, trigger: str = "") -> str:
    """
    List all skills assigned to a character, optionally filtered by trigger type.

    Args:
        character_id: e.g. "aria"
        trigger:      Optional filter: "auto" | "optional" | "required" | "" (all)
    """
    try:
        from engine.mcp.tools.character_tools import character_get_skills as _impl
        return _impl(character_id, trigger=trigger)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_add_restriction(character_id: str, restriction: str) -> str:
    """
    Add a named restriction to a character.  Restrictions are checked by the
    rules engine and character_registry interceptor before actions are allowed.

    Args:
        character_id: e.g. "aria"
        restriction:  Named restriction e.g. "no_nudity", "safe_mode"
    """
    try:
        from engine.mcp.tools.character_tools import character_add_restriction as _impl
        return _impl(character_id, restriction)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def character_remove_restriction(character_id: str, restriction: str) -> str:
    """
    Remove a named restriction from a character.

    Args:
        character_id: e.g. "aria"
        restriction:  Name of the restriction to remove
    """
    try:
        from engine.mcp.tools.character_tools import character_remove_restriction as _impl
        return _impl(character_id, restriction)
    except Exception as e:
        return json.dumps({"error": str(e)})
