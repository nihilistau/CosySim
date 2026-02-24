"""
Gallery Scene — MCP Rules Initialisation
==========================================
Registers exhibition rules, art evaluation criteria, debate mechanics,
and room access rules into the SceneRulesEngine.

Called from ``GalleryScene.start()`` after ``_mcp_init()``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "gallery"


# ──────────────────────────────────────────────────────────────────────────────
#  EXHIBITION RULES — theme enforcement, style gates
# ──────────────────────────────────────────────────────────────────────────────

_EXHIBITION_RULES: List[Dict[str, Any]] = [
    {
        "id": "theme_enforcement",
        "label": "Theme Enforcement",
        "description": "All artwork must relate to the current exhibition theme.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "style_lock", "params": {
            "directive": "Stay on-theme. Art must relate to the current exhibition.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "style_variety",
        "label": "Style Variety Bonus",
        "description": "Using a different art style than the last piece earns a creativity bonus.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  CRITIQUE RULES — evaluation criteria, debate mechanics
# ──────────────────────────────────────────────────────────────────────────────

_CRITIQUE_RULES: List[Dict[str, Any]] = [
    {
        "id": "structured_critique",
        "label": "Structured Art Critique",
        "description": "Critiques score: technique (0-10), emotion (0-10), originality (0-10). "
                       "Characters may disagree and debate scores.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "debate_rebuttal",
        "label": "Debate Rebuttal",
        "description": "After initial critiques, characters can rebut each other's scores.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "masterpiece_declaration",
        "label": "Masterpiece Declaration",
        "description": "If average score ≥ 9.0, the piece is declared a masterpiece.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"avg_critique_score": 9}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "A MASTERPIECE! The gallery erupts in applause!",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ROOM RULES — access and atmosphere
# ──────────────────────────────────────────────────────────────────────────────

_ROOM_RULES: List[Dict[str, Any]] = [
    {
        "id": "private_collection_gate",
        "label": "Private Collection Access",
        "description": "The Private Collection room requires trust ≥ 60 to enter.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"trust": 60}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "The curator nods — the private collection is now open to you.",
            "scene_id": SCENE_ID,
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "create_art",
        "label": "Create Artwork",
        "description": "Generate a new piece of art using AI image generation.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "critique",
        "label": "Critique Art",
        "description": "Evaluate a piece with technique/emotion/originality scores.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "debate",
        "label": "Start Debate",
        "description": "Characters debate the merits of a piece of art.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "change_room",
        "label": "Move to Room",
        "description": "Move to a different gallery room.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "curate_exhibition",
        "label": "Curate Exhibition",
        "description": "Start a new themed exhibition.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "A new exhibition opens — the gallery transforms!",
            "scene_id": SCENE_ID,
        }}],
    },
]


def register_gallery_rules() -> None:
    """Register all Gallery rules and actions into the SceneRulesEngine."""
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

        all_rules = _EXHIBITION_RULES + _CRITIQUE_RULES + _ROOM_RULES
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

        ssm.set_atmosphere(SCENE_ID, lighting="gallery", mood="contemplative", music="ambient")

        logger.info("Gallery MCP rules registered: %d rules, %d actions",
                    len(all_rules), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_gallery_rules failed: %s", exc)
