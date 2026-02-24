"""
Warzone Scene — MCP Rules Initialisation
==========================================
Registers balance constants, weapon/defense tiers, building rules,
weather effects, and AI behaviour rules into the SceneRulesEngine.

Called from ``WarzoneScene.__init__`` after ``_mcp_init()``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "warzone"


# ──────────────────────────────────────────────────────────────────────────────
#  BALANCE RULES — gate weapon/defense/building unlocks by resource thresholds
# ──────────────────────────────────────────────────────────────────────────────

_GATE_RULES: List[Dict[str, Any]] = [
    {
        "id": "weapon_unlock_t2",
        "label": "Cruise Missile Unlocked",
        "description": "Cruise Missile available at 300 credits.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"credits": 300}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "New weapon tier available — Cruise Missile online!",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "weapon_unlock_t5",
        "label": "Laser Cannon Unlocked",
        "description": "Laser Cannon available at 1200 credits and 5 power.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"credits": 1200, "power": 5}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "Advanced weapons research complete — Laser Cannon ready.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "weapon_unlock_t7",
        "label": "Orbital Strike Unlocked",
        "description": "Orbital Strike — the ultimate weapon at 2500 credits, 8 power, 3 intel.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"credits": 2500, "power": 8, "intel": 3}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "Orbital platform aligned. Strike capability: ACTIVE.",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  COMBAT RULES — escalation, weather interaction, damage modifiers
# ──────────────────────────────────────────────────────────────────────────────

_COMBAT_RULES: List[Dict[str, Any]] = [
    {
        "id": "escalation_ramp",
        "label": "Escalation Ramp",
        "description": "Income multiplier increases 5% per turn, accelerating late-game.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "weather_penalty",
        "label": "Weather Accuracy Penalty",
        "description": "Storm/fog apply accuracy penalties to all attacks.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "counterstrike",
        "label": "Counterstrike Mechanic",
        "description": "If a base drops below 30% HP, automatic counterstrike fires next turn.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"base_hp_pct": 30}},
        "effects": [{"effect_type": "style_lock", "params": {
            "directive": "Desperation mode — unleash maximum firepower!",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  AI COMMANDER RULES — control AI behaviour personality
# ──────────────────────────────────────────────────────────────────────────────

_AI_RULES: List[Dict[str, Any]] = [
    {
        "id": "ai_aggressive",
        "label": "AI Aggression Mode",
        "description": "When AI has weapon advantage, prefer attacking over building.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"ai_weapon_level": 3}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "General Ironside shifts to aggressive posture.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "ai_defensive",
        "label": "AI Defensive Mode",
        "description": "When AI base HP < 50%, prioritise defense upgrades.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"ai_base_hp_pct": 50}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "Ironside orders fortifications — 'Hold the line!'",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "ai_taunt",
        "label": "AI Taunt Trigger",
        "description": "AI taunts player after a successful hit or when dominating.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS — available player/AI actions with resource gates
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "attack",
        "label": "Fire Weapon",
        "description": "Fire current weapon at enemy base.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "stat_delta", "params": {"target_hp": "negative"}}],
    },
    {
        "id": "upgrade_weapon",
        "label": "Upgrade Weapon",
        "description": "Research next weapon tier.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "upgrade_defense",
        "label": "Upgrade Defense",
        "description": "Upgrade defensive systems.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "build",
        "label": "Build Structure",
        "description": "Construct a new building for resource generation.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "New construction complete.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "special_ability",
        "label": "Deploy Special",
        "description": "Use a special ability (spy satellite, EMP, sabotage, etc.).",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
]


def register_warzone_rules() -> None:
    """Register all warzone rules and actions into the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import (
            get_rules_engine, ActionDefinition, RuleDefinition,
            RuleEffect, RuleCondition,
        )
        from engine.mcp.scene_state import get_scene_state_manager

        eng = get_rules_engine()
        ssm = get_scene_state_manager()

        # Guard — only register once
        existing = eng.get_rules(SCENE_ID)
        if existing:
            return

        # Register rules
        all_rules = _GATE_RULES + _COMBAT_RULES + _AI_RULES
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

        # Register actions
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

        # Default atmosphere
        ssm.set_atmosphere(SCENE_ID, lighting="night", mood="tense", music="military")

        logger.info("Warzone MCP rules registered: %d rules, %d actions",
                    len(all_rules), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_warzone_rules failed: %s", exc)
