"""
Phone Scene — MCP Rules Initialisation
========================================
Called from ``PhoneScene.__init__`` after ``_mcp_init()`` to populate the
phone's ``MCPSceneNode`` with rules, actions, conversation-heat gates, and
autonomous messaging policies.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "phone"


# ──────────────────────────────────────────────────────────────────────────────
#  CONVERSATION HEAT GATE RULES
# ──────────────────────────────────────────────────────────────────────────────

_HEAT_RULES: List[Dict[str, Any]] = [
    {
        "id"          : "friendly_chat",
        "label"       : "Friendly Chat",
        "description" : "Normal conversation — always available. Warm, genuine exchange.",
        "rule_type"   : "always_on",
        "condition"   : {},
        "effects"     : [],
    },
    {
        "id"          : "flirt_mode",
        "label"       : "Flirt Mode Unlocked",
        "description" : "Light flirtation available when warmth ≥ 35 and happiness ≥ 30.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"warmth": 35, "happiness": 30}},
        "effects"     : [
            {"effect_type": "state_set",    "params": {"field": "conversation_mode", "value": "flirty"}},
            {"effect_type": "set_directive","params": {
                "directive_type": "style_lock", "value": "playful", "turns": 1,
            }},
        ],
    },
    {
        "id"          : "sext_gate",
        "label"       : "Sexting Available",
        "description" : "Explicit text becomes natural at arousal ≥ 55, openness ≥ 50, trust ≥ 40.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 55, "openness": 50, "trust": 40}},
        "effects"     : [
            {"effect_type": "state_set",    "params": {"field": "conversation_mode", "value": "intimate"}},
            {"effect_type": "add_narrative","params": {
                "event": "The conversation has become something more private.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "voice_call_comfort",
        "label"       : "Voice Call Comfort",
        "description" : "Character is comfortable with voice calls when trust ≥ 45.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"trust": 45}},
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "voice_call_ok", "value": True}},
        ],
    },
    {
        "id"          : "media_sharing",
        "label"       : "Media Sharing Unlocked",
        "description" : "Character will share personal photos/videos when trust ≥ 55, affection ≥ 50.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"trust": 55, "affection": 50}},
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "media_sharing_ok", "value": True}},
            {"effect_type": "add_narrative","params": {
                "event": "She decides she trusts you enough to share something personal.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "deep_confession",
        "label"       : "Deep Confession Mode",
        "description" : "At trust ≥ 70, character will share their deepest thoughts and secrets.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"trust": 70, "affection": 60}},
        "effects"     : [
            {"effect_type": "set_directive","params": {
                "directive_type": "style_lock", "value": "vulnerable", "turns": 2,
            }},
            {"effect_type": "add_narrative","params": {
                "event": "The walls come down. Something real is being offered.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  PHONE ACTIONS
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "text_casual",
        "label": "Casual Text",
        "description": "Normal friendly message. Always appropriate.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 5}},
        ],
    },
    {
        "id": "flirt_text",
        "label": "Flirt Text",
        "description": "Light, teasing, playful message with flirtatious undertone.",
        "intimacy_level": 2,
        "condition": {"stat_thresholds": {"warmth": 30}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 8}},
            {"effect_type": "stat_adjust", "params": {"stat": "warmth",    "delta": 5}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 6}},
        ],
    },
    {
        "id": "sext",
        "label": "Sext",
        "description": "Explicit, arousing text content.",
        "intimacy_level": 4,
        "condition": {"stat_thresholds": {"arousal": 55, "openness": 50, "trust": 40}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition","delta": -15}},
        ],
    },
    {
        "id": "send_selfie",
        "label": "Send Selfie",
        "description": "Character sends a selfe (AI-generated) — requires media sharing unlock.",
        "intimacy_level": 3,
        "condition": {"character_flags": {"media_sharing_ok": True}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "trust",     "delta": 5}},
            {"effect_type": "scene_event", "params": {"event_type": "selfie_sent"}},
        ],
    },
    {
        "id": "voice_note",
        "label": "Voice Note",
        "description": "Send a short personal voice message.",
        "intimacy_level": 3,
        "condition": {"stat_thresholds": {"trust": 35}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "warmth",    "delta": 8}},
            {"effect_type": "scene_event", "params": {"event_type": "voice_note_sent"}},
        ],
    },
    {
        "id": "confess_feeling",
        "label": "Confess a Feeling",
        "description": "Share something true and vulnerable.",
        "intimacy_level": 2,
        "condition": {"stat_thresholds": {"trust": 40}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "trust",     "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 10}},
        ],
    },
    {
        "id": "request_video_call",
        "label": "Request Video Call",
        "description": "Ask to see each other — more vulnerable than voice.",
        "intimacy_level": 3,
        "condition": {"character_flags": {"voice_call_ok": True}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "warmth",    "delta": 10}},
            {"effect_type": "scene_event", "params": {"event_type": "video_call_requested"}},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  AUTONOMOUS MESSAGING RULES
# ──────────────────────────────────────────────────────────────────────────────

#  These fire as consequence chains — the character sends an unprompted
#  message based on their current emotional state.

AUTONOMOUS_MESSAGE_TRIGGERS: List[Dict[str, Any]] = [
    {
        "trigger": "high_affection",
        "condition": {"stat_thresholds": {"affection": 70, "warmth": 60}},
        "message_type": "spontaneous",
        "note": "Character messages because they're thinking of you.",
        "style": "warm",
    },
    {
        "trigger": "high_arousal",
        "condition": {"stat_thresholds": {"arousal": 75, "openness": 60}},
        "message_type": "flirty_initiative",
        "note": "Character initiates something flirty.",
        "style": "playful",
    },
    {
        "trigger": "lonely",
        "condition": {"stat_thresholds": {"happiness": 20}},   # low happiness
        "message_type": "vulnerable",
        "note": "Character reaches out because they miss connection.",
        "style": "vulnerable",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  REGISTER EVERYTHING
# ──────────────────────────────────────────────────────────────────────────────

def register_phone_rules() -> None:
    """
    Called once during PhoneScene initialisation.
    Registers all phone scene rules, actions, and initial state.
    Safe to call multiple times — subsequent calls are no-ops.
    """
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

        # ── Register rules ──────────────────────────────────────────────────
        for r in _HEAT_RULES:
            cond_data = r.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None

            effects = [RuleEffect(**e) for e in r.get("effects", [])]

            eng.add_rule(SCENE_ID, RuleDefinition(
                rule_id     = r["id"],
                label       = r["label"],
                description = r["description"],
                rule_type   = r["rule_type"],
                condition   = condition,
                effects     = effects,
            ))

        # ── Register actions ────────────────────────────────────────────────
        for a in _ACTIONS:
            cond_data = a.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None

            effects = [RuleEffect(**e) for e in a.get("effects", [])]

            eng.add_action(SCENE_ID, ActionDefinition(
                action_id       = a["id"],
                label           = a["label"],
                description     = a["description"],
                intimacy_level  = a.get("intimacy_level", 1),
                condition       = condition,
                effects         = effects,
            ))

        logger.info("Phone MCP rules registered: %d rules, %d actions",
                    len(_HEAT_RULES), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_phone_rules failed: %s", exc)
