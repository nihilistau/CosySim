"""
Pure business-logic helpers for character MCP tools.

These functions are called by the thin ``@mcp.tool()`` wrappers in
``cosysim_server.py``.  They receive service dependencies (``db``,
registry helpers) as explicit parameters so they stay free of
module-level globals.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from engine.mcp.decorators import mcp_tool


# ── Domain Models ────────────────────────────────────────────────────


class CharacterStateResponse(BaseModel):
    state: Dict[str, Any]
    relationships: List[Dict[str, Any]]


class RelationshipResponse(BaseModel):
    message: str


class CharacterRegistrationResponse(BaseModel):
    ok: bool
    character_id: str
    name: str


class QueryAttributeResponse(BaseModel):
    character_id: str
    attribute: str
    value: Any


class SetAttributeResponse(BaseModel):
    ok: bool
    character_id: str
    attribute: str
    value: Any


class SkillAssignResponse(BaseModel):
    ok: bool
    character_id: str
    skill_id: str
    trigger: str


class SkillRevokeResponse(BaseModel):
    ok: bool
    character_id: str
    skill_id: str


class RestrictionResponse(BaseModel):
    ok: bool
    character_id: str
    added: Optional[str] = None
    removed: Optional[str] = None


# ── Database-backed helpers ────────────────────────────────────────────


@mcp_tool
def get_character_state(character_id: str, db: Any) -> Any:
    """Get mood, energy, relationships for a character.

    Args:
        character_id: Character to query.
        db:           A ``Database`` instance.

    Returns:
        JSON string with ``state`` and ``relationships`` keys.
    """
    state = db.get_character_state(character_id)
    if state is None:
        return f"No state found for character {character_id}."
    rels = db.list_relationships(character_id)
    return CharacterStateResponse(
        state=dict(state) if state else {},
        relationships=[dict(r) for r in rels] if rels else [],
    )


@mcp_tool
def adjust_relationship(
    character_a: str,
    character_b: str,
    field: str,
    delta: float,
    db: Any,
) -> RelationshipResponse:
    """Modify a relationship value between two characters."""
    valid_fields = {
        "relationship_level",
        "trust",
        "attraction",
        "arousal_a",
        "arousal_b",
    }
    if field not in valid_fields:
        return RelationshipResponse(
            message=f"Invalid field '{field}'. Must be one of: {', '.join(sorted(valid_fields))}"
        )

    rel = db.get_or_create_relationship(character_a, character_b)
    current = rel.get(field, 0.0) if rel else 0.0
    new_val = max(0.0, min(1.0, current + delta))
    db.update_relationship(character_a, character_b, {field: new_val})
    return RelationshipResponse(
        message=f"Updated {field}: {current:.2f} → {new_val:.2f}"
    )


@mcp_tool
def list_characters(db: Any) -> str:
    """List all characters in the database with names and IDs."""
    chars = db.get_all_characters()
    if not chars:
        return "No characters found."
    lines: list[str] = []
    for c in chars:
        c_dict = dict(c) if not isinstance(c, dict) else c
        lines.append(f"- {c_dict.get('name', '?')} (id: {c_dict.get('id', '?')})")
    return "\n".join(lines)


# ── CharacterRegistry-backed helpers ───────────────────────────────────


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
) -> CharacterRegistrationResponse:
    """Register a character in the central CharacterRegistry."""
    from engine.mcp.character_registry import (
        get_character_registry,
        apply_default_skills,
    )

    reg = get_character_registry()
    appearance = json.loads(appearance_json) if appearance_json else {}
    personality = json.loads(personality_json) if personality_json else {}
    scene_roles = json.loads(scene_roles_json) if scene_roles_json else {}
    rec = reg.register(
        character_id,
        name=name,
        age=age,
        appearance=appearance,
        personality=personality,
        backstory=backstory,
        voice_style=voice_style,
        pronouns=pronouns,
        scene_roles=scene_roles,
    )
    apply_default_skills(character_id)
    return CharacterRegistrationResponse(
        ok=True, character_id=character_id, name=rec.profile.name
    )


@mcp_tool
def character_query(character_id: str, attribute: str) -> QueryAttributeResponse:
    """Retrieve any attribute from a character's profile, state, or appearance."""
    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()
    reg.ensure(character_id)
    value = reg.get_attribute(character_id, attribute)
    if value is None:
        state = reg.get_state(character_id)
        value = state.__dict__.get(attribute) if state else None
    return QueryAttributeResponse(
        character_id=character_id, attribute=attribute, value=value
    )


@mcp_tool
def character_set_attribute(
    character_id: str,
    attribute: str,
    value: str,
) -> SetAttributeResponse:
    """Set a mutable state attribute on a character."""
    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()
    reg.ensure(character_id)
    coerced: Any = value
    try:
        coerced = float(value) if "." in value else int(value)
    except (ValueError, TypeError):
        if value.lower() in ("true", "false"):
            coerced = value.lower() == "true"
    reg.set_state(character_id, **{attribute: coerced})
    return SetAttributeResponse(
        ok=True, character_id=character_id, attribute=attribute, value=coerced
    )


@mcp_tool
def character_get_summary(character_id: str) -> Dict[str, Any]:
    """Return a compact summary of a character's identity, mood, skills, etc."""
    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()
    reg.ensure(character_id)
    summary = reg.get_character_summary(character_id)
    return summary


@mcp_tool
def character_assign_skill(
    character_id: str,
    skill_id: str,
    skill_type: str = "custom",
    label: str = "",
    params_json: str = "{}",
    trigger: str = "optional",
    priority: int = 50,
) -> SkillAssignResponse:
    """Assign a new skill to a character."""
    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()
    reg.ensure(character_id)
    params = json.loads(params_json) if params_json else {}
    entry = reg.assign_skill(
        character_id,
        skill_id=skill_id,
        skill_type=skill_type,
        label=label or skill_id,
        params=params,
        trigger=trigger,
        priority=priority,
    )
    return SkillAssignResponse(
        ok=True, character_id=character_id, skill_id=skill_id, trigger=entry.trigger
    )


@mcp_tool
def character_revoke_skill(character_id: str, skill_id: str) -> SkillRevokeResponse:
    """Remove a skill from a character."""
    from engine.mcp.character_registry import get_character_registry

    ok = get_character_registry().revoke_skill(character_id, skill_id)
    return SkillRevokeResponse(ok=ok, character_id=character_id, skill_id=skill_id)


@mcp_tool
def character_get_skills(character_id: str, trigger: str = "") -> List[Dict[str, Any]]:
    """List all skills assigned to a character."""
    from engine.mcp.character_registry import get_character_registry

    reg = get_character_registry()
    reg.ensure(character_id)
    skills = reg.get_skills(character_id, trigger=trigger or None)
    return [
        {
            "skill_id": s.skill_id,
            "label": s.label,
            "type": s.skill_type,
            "trigger": s.trigger,
            "priority": s.priority,
            "enabled": s.enabled,
        }
        for s in skills
    ]


@mcp_tool
def character_add_restriction(
    character_id: str, restriction: str
) -> RestrictionResponse:
    """Add a named restriction to a character."""
    from engine.mcp.character_registry import get_character_registry

    get_character_registry().add_restriction(character_id, restriction)
    return RestrictionResponse(ok=True, character_id=character_id, added=restriction)


@mcp_tool
def character_remove_restriction(
    character_id: str, restriction: str
) -> RestrictionResponse:
    """Remove a named restriction from a character."""
    from engine.mcp.character_registry import get_character_registry

    get_character_registry().remove_restriction(character_id, restriction)
    return RestrictionResponse(ok=True, character_id=character_id, removed=restriction)

# ── Stats & Emotion Effects ────────────────────────────────────────────


@mcp_tool
def update_mood_impl(
    character_id: str,
    mood: str,
    reason: str = "",
    intensity: float = 0.5,
    db: Any = None,
) -> str:
    """Update a character's current mood and trigger emotional effects."""
    db.update_character_state(
        character_id,
        {
            "mood": mood,
            "mood_intensity": max(0.0, min(1.0, intensity)),
            "mood_reason": reason,
        },
    )
    return f"Updated {character_id} mood → {mood} (intensity={intensity:.1f}). Reason: {reason}"


@mcp_tool
def apply_effect_impl(
    character_id: str,
    effect_name: str,
    value: float = 0.1,
    db: Any = None,
) -> str:
    """Apply a status effect to a character's state."""
    EFFECT_MAP = {
        "trust_boost": {"trust": value},
        "trust_drop": {"trust": -value},
        "attraction_boost": {"attraction": value},
        "energise": {"arousal_a": value},
        "deflate": {"arousal_a": -value},
        "excite": {"arousal_a": value, "attraction": value * 0.5},
        "calm": {"arousal_a": -value * 0.5},
        "curiosity_spike": {"relationship_level": value * 0.3},
    }
    fields = EFFECT_MAP.get(effect_name)
    if not fields:
        return f"Unknown effect '{effect_name}'."
        
    results = []
    for field, delta in fields.items():
        try:
            db.update_character_state(character_id, {field: delta})
            results.append(f"{field}+={delta:+.2f}")
        except Exception:
            pass  # Ignore failing fields
            
    return f"Applied effect '{effect_name}' to {character_id}: {', '.join(results)}"


@mcp_tool
def check_relationship_impl(character_a: str, character_b: str, db: Any = None) -> Dict[str, Any]:
    """Get a concise relationship summary between two characters."""
    rel = db.get_or_create_relationship(character_a, character_b)
    if not rel:
        return {"error": f"No relationship found between {character_a} and {character_b}."}
        
    r = dict(rel)
    trust = float(r.get("trust", 0.5))
    attract = float(r.get("attraction", 0.5))
    level = float(r.get("relationship_level", 0.5))

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
    return {"raw": r, "summary": summary}

# ── Character Scene Stats & Consent ────────────────────────────────────

class CharacterSceneStatsResponse(BaseModel):
    character_id: str
    stats: Dict[str, Any]
    emotional_state: str
    wearing: str
    is_naked: bool

class ConsentCheckResponse(BaseModel):
    character_id: str
    action: str
    decision: str
    detail: str
    score: float
    threshold: int
    emotional_state: str
    note: str

def _ssm():
    from engine.mcp.scene_state import get_scene_state_manager
    return get_scene_state_manager()

def _coord():
    from engine.mcp.scene_coordinator import get_coordinator
    return get_coordinator()

@mcp_tool
def get_character_scene_stats_impl(character_id: str) -> CharacterSceneStatsResponse:
    stats = _ssm().get_stats(character_id)
    wardrobe = _ssm().get_wardrobe(character_id)
    return CharacterSceneStatsResponse(
        character_id=character_id,
        stats=stats.to_dict(),
        emotional_state=stats.emotional_state_text(),
        wearing=wardrobe.coverage_description(),
        is_naked=len(wardrobe.worn_items()) == 0,
    )

@mcp_tool
def update_character_scene_stats_impl(character_id: str, stat_changes: str) -> Dict[str, Any]:
    changes = json.loads(stat_changes) if isinstance(stat_changes, str) else stat_changes
    if not isinstance(changes, dict):
        raise ToolExecutionError('stat_changes must be a JSON dictionary: {"stat": delta}')
        
    _coord().update(character_id, source="mcp_tool", **changes)
    stats = _ssm().get_stats(character_id)
    return {
        "updated": True,
        "character_id": character_id,
        "applied_changes": changes,
        "new_stats": stats.to_dict(),
        "emotional_state": stats.emotional_state_text(),
    }

@mcp_tool
def set_character_scene_stat_impl(character_id: str, stat: str, value: float) -> Dict[str, Any]:
    _coord().update(character_id, mode="set", source="mcp_tool", **{stat: value})
    stats = _ssm().get_stats(character_id)
    return {
        "set": True,
        "stat": stat,
        "value": getattr(stats, stat, None),
        "emotional_state": stats.emotional_state_text(),
    }

@mcp_tool
def reset_character_scene_stats_impl(character_id: str) -> Dict[str, Any]:
    _ssm().reset_stats(character_id)
    _ssm().get_wardrobe(character_id).reset()
    return {"reset": True, "character_id": character_id}

@mcp_tool
def check_character_consent_impl(character_id: str, action_type: str) -> ConsentCheckResponse:
    stats = _ssm().get_stats(character_id).to_dict()
    openness = float(stats.get("openness", 65))
    arousal = float(stats.get("arousal", 20))
    fear = float(stats.get("fear", 5))
    anger = float(stats.get("anger", 5))
    happiness = float(stats.get("happiness", 60))
    affection = float(stats.get("affection", 50))

    intimacy_map = {
        "cuddle": 20,
        "kiss": 30,
        "caress": 35,
        "dirty_talk": 45,
        "striptease": 50,
        "remove_top": 45,
        "remove_all": 60,
        "oral": 65,
        "foreplay": 55,
        "sex": 70,
        "role_play": 50,
        "submission": 65,
    }
    threshold = intimacy_map.get(action_type.lower(), 50)
    score = (openness * 0.4) + (arousal * 0.3) + (happiness * 0.15) + (affection * 0.15)
    score -= (fear * 0.4) + (anger * 0.3)

    if score >= threshold + 15:
        decision = "WILL"
        detail = "enthusiastically willing — may even take the lead"
    elif score >= threshold:
        decision = "WILL"
        detail = "willing, probably with some playful resistance"
    elif score >= threshold - 15:
        decision = "RELUCTANT"
        detail = "hesitant but could be persuaded if approached well"
    else:
        decision = "REFUSE"
        detail = "refusing — this goes against current state or mood"

    return ConsentCheckResponse(
        character_id=character_id,
        action=action_type,
        decision=decision,
        detail=detail,
        score=round(score, 1),
        threshold=threshold,
        emotional_state=_ssm().get_stats(character_id).emotional_state_text(),
        note="REFUSE creates drama — lean into it. Negotiation and resistance are part of the scene.",
    )

@mcp_tool
def get_character_agency_summary_impl(character_id: str) -> Dict[str, Any]:
    stats = _ssm().get_stats(character_id).to_dict()
    wardrobe = _ssm().get_wardrobe(character_id)

    arousal = float(stats.get("arousal", 20))
    openness = float(stats.get("openness", 65))
    happiness = float(stats.get("happiness", 60))
    horniness = float(stats.get("horniness", 15))
    dominance = float(stats.get("dominance", 50))
    affection = float(stats.get("affection", 50))
    fear = float(stats.get("fear", 5))
    anger = float(stats.get("anger", 5))

    compliance = max(0, min(100, 50 + (happiness * 0.3) + (affection * 0.3) - (anger * 0.5) - (fear * 0.2)))
    agency = max(0, min(100, 50 + (dominance * 0.4) + (openness * 0.3) - (fear * 0.5)))

    wants = []
    if arousal > 70 or horniness > 70:
        wants.append("physical release / intimacy")
    elif affection > 70:
        wants.append("closeness / cuddling / validation")
    if dominance > 70:
        wants.append("to take control / issue orders")
    elif dominance < 30:
        wants.append("to be guided / told what to do")
    if openness > 70 and happiness > 60:
        wants.append("to try something new / play a game")

    resists = []
    if fear > 40:
        resists.append("sudden changes / high intensity")
    if anger > 40:
        resists.append("being told what to do / sweetness")
    if openness < 40:
        resists.append("kinky or unusual requests")
    if arousal < 30:
        resists.append("direct sexual escalation")

    initiates = []
    if agency > 70:
        if arousal > 60:
            initiates.append("stealing a kiss / touching")
        if dominance > 60:
            initiates.append("changing the subject entirely / teasing")

    return {
        "character_id": character_id,
        "emotional_state": _ssm().get_stats(character_id).emotional_state_text(),
        "wearing": wardrobe.coverage_description(),
        "meta": {
            "compliance_score": round(compliance, 1),
            "agency_score": round(agency, 1),
        },
        "mindset": {
            "most_wants": wants or ["normal conversation"],
            "will_resist": resists or ["nothing strongly right now"],
            "might_initiate": initiates or ["waiting for the other to act"],
        },
    }

