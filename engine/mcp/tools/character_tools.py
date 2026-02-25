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


# ── Database-backed helpers ────────────────────────────────────────────

def get_character_state(character_id: str, db: Any) -> str:
    """Get mood, energy, relationships for a character.

    Args:
        character_id: Character to query.
        db:           A ``Database`` instance.

    Returns:
        JSON string with ``state`` and ``relationships`` keys.
    """
    try:
        state = db.get_character_state(character_id)
        if state is None:
            return f"No state found for character {character_id}."
        rels = db.list_relationships(character_id)
        return json.dumps({
            "state": dict(state) if state else {},
            "relationships": [dict(r) for r in rels] if rels else [],
        }, indent=2, default=str)
    except Exception as e:
        return f"Failed to get character state: {e}"


def adjust_relationship(
    character_a: str,
    character_b: str,
    field: str,
    delta: float,
    db: Any,
) -> str:
    """Modify a relationship value between two characters.

    Args:
        character_a: First character id.
        character_b: Second character id.
        field:       One of ``relationship_level``, ``trust``, ``attraction``,
                     ``arousal_a``, ``arousal_b``.
        delta:       Amount to add (can be negative). Result clamped 0–1.
        db:          A ``Database`` instance.

    Returns:
        Confirmation with old → new value, or error message.
    """
    valid_fields = {"relationship_level", "trust", "attraction", "arousal_a", "arousal_b"}
    if field not in valid_fields:
        return f"Invalid field '{field}'. Must be one of: {', '.join(sorted(valid_fields))}"

    try:
        rel = db.get_or_create_relationship(character_a, character_b)
        current = rel.get(field, 0.0) if rel else 0.0
        new_val = max(0.0, min(1.0, current + delta))
        db.update_relationship(character_a, character_b, {field: new_val})
        return f"Updated {field}: {current:.2f} → {new_val:.2f}"
    except Exception as e:
        return f"Failed to adjust relationship: {e}"


def list_characters(db: Any) -> str:
    """List all characters in the database with names and IDs.

    Args:
        db: A ``Database`` instance.

    Returns:
        Newline-separated list, or error message.
    """
    try:
        chars = db.get_all_characters()
        if not chars:
            return "No characters found."
        lines: list[str] = []
        for c in chars:
            c_dict = dict(c) if not isinstance(c, dict) else c
            lines.append(f"- {c_dict.get('name', '?')} (id: {c_dict.get('id', '?')})")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list characters: {e}"


# ── CharacterRegistry-backed helpers ───────────────────────────────────

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
    """Register a character in the central CharacterRegistry.

    Safe to call multiple times — auto-creates a stub if the character
    doesn't exist yet.

    Args:
        character_id:     Unique key e.g. ``"aria"``
        name:             Display name
        age:              Character age
        appearance_json:  JSON dict e.g. ``'{"hair": "dark"}'``
        personality_json: JSON dict of 0–1 floats
        backstory:        Short backstory paragraph
        voice_style:      Speaking style
        pronouns:         e.g. ``"she/her"``
        scene_roles_json: JSON dict of scene → role

    Returns:
        JSON ``{"ok": True, ...}`` or ``{"ok": False, "error": ...}``.
    """
    try:
        from engine.mcp.character_registry import get_character_registry, apply_default_skills
        reg = get_character_registry()
        appearance  = json.loads(appearance_json)  if appearance_json  else {}
        personality = json.loads(personality_json) if personality_json else {}
        scene_roles = json.loads(scene_roles_json) if scene_roles_json else {}
        rec = reg.register(
            character_id,
            name        = name,
            age         = age,
            appearance  = appearance,
            personality = personality,
            backstory   = backstory,
            voice_style = voice_style,
            pronouns    = pronouns,
            scene_roles = scene_roles,
        )
        apply_default_skills(character_id)
        return json.dumps({"ok": True, "character_id": character_id, "name": rec.profile.name})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def character_query(character_id: str, attribute: str) -> str:
    """Retrieve any attribute from a character's profile, state, or appearance.

    Args:
        character_id: e.g. ``"aria"``
        attribute:    Any key such as ``"name"``, ``"mood"``, ``"arousal"``, etc.

    Returns:
        JSON with the queried value.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        value = reg.get_attribute(character_id, attribute)
        if value is None:
            state = reg.get_state(character_id)
            value = state.__dict__.get(attribute) if state else None
        return json.dumps({"character_id": character_id, "attribute": attribute, "value": value})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def character_set_attribute(
    character_id: str,
    attribute: str,
    value: str,
) -> str:
    """Set a mutable state attribute on a character.

    Supports mood, mood_intensity, focus, current_role, energy, inhibition,
    or any arbitrary flag stored in character_flags.

    Args:
        character_id: e.g. ``"aria"``
        attribute:    State field name.
        value:        New value (coerced from string where possible).

    Returns:
        JSON confirmation or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        coerced: Any = value
        try:
            coerced = float(value) if '.' in value else int(value)
        except (ValueError, TypeError):
            if value.lower() in ("true", "false"):
                coerced = value.lower() == "true"
        reg.set_state(character_id, **{attribute: coerced})
        return json.dumps({"ok": True, "character_id": character_id, attribute: coerced})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def character_get_summary(character_id: str) -> str:
    """Return a compact summary of a character's identity, mood, skills, etc.

    Args:
        character_id: e.g. ``"aria"``

    Returns:
        JSON summary suitable for prompt injection.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        summary = reg.get_character_summary(character_id)
        return json.dumps(summary, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def character_assign_skill(
    character_id: str,
    skill_id: str,
    skill_type: str = "custom",
    label: str = "",
    params_json: str = "{}",
    trigger: str = "optional",
    priority: int = 50,
) -> str:
    """Assign a new skill to a character.

    Args:
        character_id: Character to receive the skill.
        skill_id:     Unique skill identifier.
        skill_type:   ``"memory"`` | ``"speech"`` | ``"action"`` | ``"query"`` | ``"custom"``
        label:        Human-readable name.
        params_json:  JSON dict of skill parameters.
        trigger:      ``"auto"`` | ``"optional"`` | ``"required"``
        priority:     Execution priority (lower = earlier).

    Returns:
        JSON confirmation or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        params = json.loads(params_json) if params_json else {}
        entry = reg.assign_skill(
            character_id,
            skill_id   = skill_id,
            skill_type = skill_type,
            label      = label or skill_id,
            params     = params,
            trigger    = trigger,
            priority   = priority,
        )
        return json.dumps({"ok": True, "character_id": character_id, "skill_id": skill_id, "trigger": entry.trigger})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def character_revoke_skill(character_id: str, skill_id: str) -> str:
    """Remove a skill from a character.

    Args:
        character_id: e.g. ``"aria"``
        skill_id:     Skill to remove.

    Returns:
        JSON confirmation or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        ok = get_character_registry().revoke_skill(character_id, skill_id)
        return json.dumps({"ok": ok, "character_id": character_id, "skill_id": skill_id})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def character_get_skills(character_id: str, trigger: str = "") -> str:
    """List all skills assigned to a character.

    Args:
        character_id: e.g. ``"aria"``
        trigger:      Optional filter: ``"auto"`` | ``"optional"`` | ``"required"``
                      or ``""`` for all.

    Returns:
        JSON list of skill dicts, or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        reg = get_character_registry()
        reg.ensure(character_id)
        skills = reg.get_skills(character_id, trigger=trigger or None)
        return json.dumps([
            {"skill_id": s.skill_id, "label": s.label, "type": s.skill_type,
             "trigger": s.trigger, "priority": s.priority, "enabled": s.enabled}
            for s in skills
        ], indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def character_add_restriction(character_id: str, restriction: str) -> str:
    """Add a named restriction to a character.

    Args:
        character_id: e.g. ``"aria"``
        restriction:  Named restriction e.g. ``"no_nudity"``, ``"safe_mode"``

    Returns:
        JSON confirmation or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        get_character_registry().add_restriction(character_id, restriction)
        return json.dumps({"ok": True, "character_id": character_id, "added": restriction})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def character_remove_restriction(character_id: str, restriction: str) -> str:
    """Remove a named restriction from a character.

    Args:
        character_id: e.g. ``"aria"``
        restriction:  Name of the restriction to remove.

    Returns:
        JSON confirmation or error.
    """
    try:
        from engine.mcp.character_registry import get_character_registry
        get_character_registry().remove_restriction(character_id, restriction)
        return json.dumps({"ok": True, "character_id": character_id, "removed": restriction})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
