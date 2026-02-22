"""
Realm Skills — MCP skill functions for The Realm LitRPG scene.

Exposes inventory management, skill checks, director control, murder mystery
actions, and fourth-wall mechanics as @skill-decorated functions callable
by LMS agents via tool use.
"""
from __future__ import annotations

import json
import logging

from engine.skills.skill import skill, SkillCategory

logger = logging.getLogger(__name__)


def _get_realm_scene():
    """Look up the running Realm scene instance."""
    from engine.scenes.base_scene import get_active_scene
    return get_active_scene("realm")


# ── Inventory ─────────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="List the player's current inventory in The Realm.",
)
def realm_inventory() -> str:
    """Return a formatted list of all items the player is carrying."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    items = scene.state.inventory
    if not items:
        return "Inventory is empty."
    lines = [f"🎒 Inventory ({len(items)} items):"]
    for i in items:
        lines.append(f"  • {i['name']} ({i.get('type', '?')}) — {i.get('description', '')[:60]}")
    return "\n".join(lines)


@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="Add an item to the player's inventory.",
)
def realm_add_item(name: str, item_type: str = "misc", description: str = "") -> str:
    """Give the player a new item."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    item = {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "type": item_type,
        "description": description,
    }
    scene.state.add_item(item)
    return f"Added '{name}' to inventory."


@skill(
    pack="realm",
    tags=["game", "inventory"],
    category=SkillCategory.GAME,
    description="Remove an item from the player's inventory by its ID.",
)
def realm_remove_item(item_id: str) -> str:
    """Remove an item from the player's inventory."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    removed = scene.state.remove_item(item_id)
    if removed:
        return f"Removed '{removed['name']}' from inventory."
    return f"Item '{item_id}' not found in inventory."


# ── Stats & Skills ────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Get the player's current stats in The Realm.",
)
def realm_stats() -> str:
    """Return the player's stats as a formatted summary."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    s = scene.state.player_stats
    return (
        f"HP: {s['hp']}/{s['max_hp']} | MP: {s['mp']}/{s['max_mp']}\n"
        f"Level {s['level']} ({s['xp']}/{s['xp_next']} XP)\n"
        f"STR: {s['strength']} AGI: {s['agility']} INT: {s['intellect']} "
        f"CHA: {s['charisma']} LCK: {s['luck']}"
    )


@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Perform a skill check for the player (d20 + stat bonus vs DC).",
)
def realm_skill_check(skill_name: str, dc_modifier: int = 0) -> str:
    """Roll a skill check and return the result."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.skill_check(skill_name, dc_modifier)
    if not result.get("success") and result.get("reason") == "unknown skill":
        return f"Unknown skill '{skill_name}'. Available: persuasion, lockpicking, arcana, athletics, stealth, intimidation, deception, investigation, survival."
    outcome = "SUCCESS ✅" if result["success"] else "FAILURE ❌"
    return (
        f"Skill Check: {skill_name} — {outcome}\n"
        f"Roll: {result['roll']} + {result['bonus']} ({result['stat']} {result['stat_value']}) = {result['total']} vs DC {result['dc']}"
    )


@skill(
    pack="realm",
    tags=["game", "stats"],
    category=SkillCategory.GAME,
    description="Deal damage to or heal the player.",
)
def realm_adjust_hp(amount: int) -> str:
    """Positive heals, negative damages. Returns new HP and death status."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    if amount >= 0:
        hp = scene.state.heal(amount)
        return f"Healed {amount} HP. Current: {hp}/{scene.state.player_stats['max_hp']}"
    hp, dead = scene.state.take_damage(abs(amount))
    result = f"Took {abs(amount)} damage. Current: {hp}/{scene.state.player_stats['max_hp']}"
    if dead:
        result += " — PLAYER DIED 💀"
    return result


# ── Director Control ──────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="Get the Director's current personality and patience level.",
)
def realm_director_status() -> str:
    """Return Director personality, patience meter, and mutiny status."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    st = scene.state
    mutiny = "ACTIVE ⚡" if st.is_mutiny_active() else "inactive"
    return (
        f"Director: {st.director_personality} | Patience: {st.director_patience:.0f}/100\n"
        f"Mutiny: {mutiny} | Turn: {st.turn_number}"
    )


@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="The Assistant steals a UI element and adds it to the player's inventory (fourth-wall break).",
)
def realm_fourth_wall_steal(item_name: str) -> str:
    """The Assistant rips an item from the game interface."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    item = scene.state.assistant_steal(item_name)
    return f"🕳️ FOURTH WALL BREACH — Stole '{item_name}' from the UI! Added as [{item['name']}]."


@skill(
    pack="realm",
    tags=["game", "narrative"],
    category=SkillCategory.NARRATIVE,
    description="Sacrifice 10 max HP to force the Director to start a fresh conversation context.",
    cooldown=30.0,
)
def realm_desperation_dice() -> str:
    """Desperation dice — sacrifice permanent HP to reset Director context."""
    scene = _get_realm_scene()
    if not scene or not scene.state:
        return "No active Realm game."
    result = scene.state.desperation_dice()
    if result["success"]:
        scene._director_conv_id = None
        return f"🎲 DESPERATION DICE — Sacrificed 10 max HP! New max: {result['new_max_hp']}. Director context reset."
    return f"Cannot sacrifice — {result['reason']}"


# ── Murder Mystery ────────────────────────────────────────────

@skill(
    pack="realm",
    tags=["game", "narrative", "murder_mystery"],
    category=SkillCategory.GAME,
    description="Get the current state of the murder mystery investigation.",
)
def realm_murder_status() -> str:
    """Return murder mystery phase, clues, accusations remaining."""
    scene = _get_realm_scene()
    if not scene or not scene.state or not scene.state.murder:
        return "No active murder mystery."
    m = scene.state.murder
    return (
        f"Phase: {m.phase} | Time remaining: {m.phase_time_remaining():.0f}s\n"
        f"Clues found: {len(m.clues_found)} | Interrogations: {len(m.interrogations)}\n"
        f"Accusations remaining: {m.accusations_remaining} | Resolved: {m.resolved}"
    )


@skill(
    pack="realm",
    tags=["game", "narrative", "murder_mystery"],
    category=SkillCategory.GAME,
    description="Make an accusation in the murder mystery (suspect_id, weapon, room).",
)
def realm_murder_accuse(suspect_id: str, weapon: str, room: str) -> str:
    """Accuse a suspect with a weapon and room. Returns verdict."""
    scene = _get_realm_scene()
    if not scene or not scene.state or not scene.state.murder:
        return "No active murder mystery."
    result = scene.state.murder.accuse(suspect_id, weapon, room)
    if not result.get("allowed"):
        return f"Cannot accuse: {result.get('reason', 'unknown')}"
    parts = []
    if result["correct_suspect"]:
        parts.append("✅ Correct suspect")
    else:
        parts.append("❌ Wrong suspect")
    if result["correct_weapon"]:
        parts.append("✅ Correct weapon")
    else:
        parts.append("❌ Wrong weapon")
    if result["correct_room"]:
        parts.append("✅ Correct room")
    else:
        parts.append("❌ Wrong room")
    verdict = "🎉 CASE SOLVED!" if result["won"] else f"Wrong! {result['remaining']} attempts left."
    return f"Accusation: {' | '.join(parts)}\n{verdict}"
