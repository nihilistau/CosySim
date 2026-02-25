"""
The Realm — MCP Rules Initialisation
======================================
Registers combat rules, skill check mechanics, inventory gates,
exploration rules, and Director personality rules into the SceneRulesEngine.

Called from ``RealmScene.__init__`` after ``_mcp_init()``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "realm"


# ──────────────────────────────────────────────────────────────────────────────
#  COMBAT RULES — turn-based mechanics, damage, death
# ──────────────────────────────────────────────────────────────────────────────

_COMBAT_RULES: List[Dict[str, Any]] = [
    {
        "id": "combat_initiative",
        "label": "Initiative Roll",
        "description": "Combat starts with d20 + agility. Higher goes first.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "weapon_damage",
        "label": "Weapon Damage Calculation",
        "description": "Damage = weapon.damage + strength_mod. Critical on nat 20 (2x damage).",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "death_check",
        "label": "Death on Zero HP",
        "description": "HP ≤ 0 triggers death. Lose a random item, respawn at camp with 50% HP.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"hp": 0}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "You collapse. Darkness takes you... but the realm isn't finished with you yet.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "healing_items",
        "label": "Consumable Healing",
        "description": "Health potions restore heal amount. Can only use 1 per combat turn.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  SKILL CHECK RULES — d20 + stat modifier vs DC
# ──────────────────────────────────────────────────────────────────────────────

_SKILL_RULES: List[Dict[str, Any]] = [
    {
        "id": "skill_check_formula",
        "label": "Skill Check: d20 + Stat Mod",
        "description": "Roll d20 + stat_modifier (stat // 2 - 5). Meet or exceed DC to succeed.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "critical_success",
        "label": "Critical Success (Nat 20)",
        "description": "Natural 20 always succeeds, grants bonus loot or extra effect.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "CRITICAL SUCCESS! The impossible becomes reality!",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "critical_failure",
        "label": "Critical Failure (Nat 1)",
        "description": "Natural 1 always fails, may cause a complication.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "A spectacular failure! Things just got worse...",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  EXPLORATION RULES — rooms, loot, encounters
# ──────────────────────────────────────────────────────────────────────────────

_EXPLORATION_RULES: List[Dict[str, Any]] = [
    {
        "id": "room_discovery",
        "label": "Room Discovery",
        "description": "Each new room has a 30% encounter chance, 40% loot chance, 30% empty.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "locked_door",
        "label": "Locked Door",
        "description": "Some rooms require lockpicking (DC 14) or brute strength (DC 16) to enter.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "level_up",
        "label": "Level Up",
        "description": "At XP ≥ xp_next: level +1, +10 max_hp, +5 max_mp, +2 to random stat, xp_next *= 1.5.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"xp_overflow": 1}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "LEVEL UP! You feel power surge through your body.",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  DIRECTOR RULES — personality affects narration style
# ──────────────────────────────────────────────────────────────────────────────

_DIRECTOR_RULES: List[Dict[str, Any]] = [
    {
        "id": "director_patience",
        "label": "Director Patience",
        "description": "Director patience decreases each turn. At 0, Director triggers mutiny event.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "director_mutiny",
        "label": "Director Mutiny",
        "description": "At patience 0, Director seizes control — forced narrative, no player choice.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"director_patience": 0}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "The Director has lost patience. 'Enough of YOUR choices. This is MY story now.'",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "assistant_fourth_wall",
        "label": "Assistant Fourth-Wall Breaks",
        "description": "The Assistant may steal UI elements, break the fourth wall, or bicker with Director.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  MURDER MYSTERY RULES
# ──────────────────────────────────────────────────────────────────────────────

_MYSTERY_RULES: List[Dict[str, Any]] = [
    {
        "id": "clue_discovery",
        "label": "Clue Discovery",
        "description": "Investigation checks reveal clues. 3 correct clues unlock accusation.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "accusation",
        "label": "Murder Accusation",
        "description": "Accuse NPC + weapon + room. Correct = mystery solved. Wrong = lose 25 HP.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "explore",
        "label": "Explore",
        "description": "Move to a new room or location. May trigger encounters.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "attack",
        "label": "Attack",
        "description": "Attack an enemy with equipped weapon. Roll d20 + strength mod vs enemy defense.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "stat_delta", "params": {"target_hp": "negative"}}],
    },
    {
        "id": "defend",
        "label": "Defend",
        "description": "Raise guard to halve incoming damage this round. Enemy still attacks.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "flee",
        "label": "Flee",
        "description": "Attempt to flee combat. Roll d20 + agility mod vs DC 12.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "use_item",
        "label": "Use Item",
        "description": "Use an item from inventory (potion, torch, etc.).",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "skill_check",
        "label": "Attempt Skill Check",
        "description": "Roll a skill check against a challenge DC.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "talk_to_npc",
        "label": "Talk to NPC",
        "description": "Engage in dialogue with an NPC. May require persuasion/intimidation.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "accuse",
        "label": "Make Accusation",
        "description": "Accuse an NPC of the murder (requires 3+ clues).",
        "intimacy_level": 1,
        "condition": {"stat_thresholds": {"clues_found": 3}},
        "effects": [],
    },
    {
        "id": "rest",
        "label": "Rest",
        "description": "Rest at a safe location. Restore 20% HP and MP. Advance time 1 hour.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "stat_delta", "params": {"hp": 20, "mp": 10}}],
    },
    {
        "id": "move_location",
        "label": "Travel",
        "description": "Move to a connected location. May trigger random encounters en route.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
]


def register_realm_rules() -> None:
    """Register all Realm rules and actions into the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import (
            get_rules_engine, ActionDefinition, RuleDefinition,
            RuleEffect, RuleCondition,
        )
        from engine.mcp.scene_state import get_scene_state_manager

        eng = get_rules_engine()
        ssm = get_scene_state_manager()

        existing = eng.get_rules(SCENE_ID)
        if existing:
            return

        all_rules = _COMBAT_RULES + _SKILL_RULES + _EXPLORATION_RULES + _DIRECTOR_RULES + _MYSTERY_RULES
        for r in all_rules:
            cond_data = r.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None

            effects = [RuleEffect(**e) for e in r.get("effects", [])]

            eng.add_rule(SCENE_ID, RuleDefinition(
                rule_id=r["id"],
                label=r["label"],
                description=r["description"],
                rule_type=r["rule_type"],
                condition=condition,
                effects=effects,
            ))

        for a in _ACTIONS:
            cond_data = a.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None

            effects = [RuleEffect(**e) for e in a.get("effects", [])]

            eng.add_action(SCENE_ID, ActionDefinition(
                action_id=a["id"],
                label=a["label"],
                description=a["description"],
                intimacy_level=a.get("intimacy_level", 1),
                condition=condition,
                effects=effects,
            ))

        ssm.set_atmosphere(SCENE_ID, lighting="dungeon", mood="adventurous", music="fantasy")

        logger.info("Realm MCP rules registered: %d rules, %d actions",
                    len(all_rules), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_realm_rules failed: %s", exc)
