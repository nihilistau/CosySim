"""
NeonCity Scene — MCP Rules Initialisation
==========================================
Registers cyberpunk balance constants, combat rules, hacking mechanics,
and AI behaviour rules into the SceneRulesEngine.

Called from ``NeonCityScene.__init__`` after ``_mcp_init()``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "neoncity"


# ──────────────────────────────────────────────────────────────────────────────
#  ZONE RULES — Glitch Storm, safe zones, loot gates
# ──────────────────────────────────────────────────────────────────────────────

_ZONE_RULES: List[Dict[str, Any]] = [
    {
        "id": "glitch_storm_shrink",
        "label": "Glitch Storm Closes",
        "description": "The Glitch Storm shrinks the playable grid by 1 tile each round.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "The Glitch Storm closes in — move to safety!",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "storm_damage",
        "label": "Storm Damage",
        "description": "Players caught in the Glitch Storm take 15 damage per turn.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "stat_delta", "params": {"hp": -15}}],
    },
    {
        "id": "safe_zone_bonus",
        "label": "Safe Zone Regen",
        "description": "Standing in the safe zone regenerates 5 HP per turn.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"in_safe_zone": 1}},
        "effects": [{"effect_type": "stat_delta", "params": {"hp": 5}}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  COMBAT RULES — weapon tiers, accuracy, damage modifiers
# ──────────────────────────────────────────────────────────────────────────────

_COMBAT_RULES: List[Dict[str, Any]] = [
    {
        "id": "melee_range_bonus",
        "label": "Close Combat Bonus",
        "description": "Melee weapons get +15 accuracy at range 1.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "stun_effect",
        "label": "Stun Effect",
        "description": "EMP weapons stun target for 1 turn (skip movement).",
        "rule_type": "triggered",
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "Target stunned — cybernetics temporarily offline!",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "critical_hit",
        "label": "Critical Hit",
        "description": "10% chance for 2x damage on any attack.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  HACKING RULES — skill checks, firewall levels, consequences
# ──────────────────────────────────────────────────────────────────────────────

_HACKING_RULES: List[Dict[str, Any]] = [
    {
        "id": "hack_skill_check",
        "label": "Hacking Skill Check",
        "description": "Hacking roll: hacking_stat + program_power vs target_security. "
                       "Success steals credits or disables defenses. Failure triggers alarm.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "alarm_escalation",
        "label": "Alarm Escalation",
        "description": "Failed hacks raise alert level. At level 3, security drones attack.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"alert_level": 3}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "SECURITY ALERT: Corporate drones inbound!",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  AI OPPONENT RULES — behaviour profiles
# ──────────────────────────────────────────────────────────────────────────────

_AI_RULES: List[Dict[str, Any]] = [
    {
        "id": "ai_aggressive",
        "label": "Aggressive AI",
        "description": "AI prioritises chasing and attacking players over looting.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "ai_opportunist",
        "label": "Opportunist AI",
        "description": "AI loots when safe, attacks when advantaged, flees when low HP.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "ai_flee_threshold",
        "label": "AI Flee Threshold",
        "description": "AI runs away when HP drops below 25%.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"hp_pct": 25}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "The AI opponent is fleeing — they're on the ropes!",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "move",
        "label": "Move",
        "description": "Move up to movement_points tiles on the grid.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "attack",
        "label": "Attack",
        "description": "Attack an adjacent player or AI with equipped weapon.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "stat_delta", "params": {"target_hp": "negative"}}],
    },
    {
        "id": "hack",
        "label": "Hack Target",
        "description": "Attempt to hack a location or player using hacking programs.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "loot",
        "label": "Loot Location",
        "description": "Search a prefab location for items, weapons, or implants.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "use_implant",
        "label": "Use Implant",
        "description": "Activate an installed cybernetic implant for a stat boost.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
]


def register_neoncity_rules() -> None:
    """Register all NeonCity rules and actions into the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import (
            get_rules_engine, ActionDefinition, RuleDefinition,
            RuleEffect, RuleCondition,
        )
        from engine.mcp.scene_state import get_scene_state_manager

        eng = get_rules_engine()
        ssm = get_scene_state_manager()

        # v1.58.0 [2026-06-11] — Idempotency guard must ignore the engine's
        # bootstrap "*" wildcard rules; get_rules() includes them, so the old
        # check ALWAYS early-returned and NeonCity rules never registered.
        if any(r.scene == SCENE_ID for r in eng.get_rules(SCENE_ID)):
            return

        all_rules = _ZONE_RULES + _COMBAT_RULES + _HACKING_RULES + _AI_RULES
        for r in all_rules:
            cond_data = r.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None

            effects = [RuleEffect(**e) for e in r.get("effects", [])]

            # v1.58.0 [2026-06-11] — add_rule takes ONE RuleDefinition; the
            # old add_rule(SCENE_ID, ...) raised "takes 2 positional arguments
            # but 3 were given" so NO NeonCity rules were ever registered.
            eng.add_rule(RuleDefinition(
                rule_id=r["id"],
                scene=SCENE_ID,
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

            eng.add_action(ActionDefinition(  # v1.58.0 — same signature fix
                action_id=a["id"],
                scene=SCENE_ID,
                label=a["label"],
                description=a["description"],
                intimacy_level=a.get("intimacy_level", 1),
                condition=condition,
                effects=effects,
            ))

        ssm.set_atmosphere(SCENE_ID, lighting="neon", mood="cyberpunk", music="synthwave")

        logger.info("NeonCity MCP rules registered: %d rules, %d actions",
                    len(all_rules), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_neoncity_rules failed: %s", exc)
