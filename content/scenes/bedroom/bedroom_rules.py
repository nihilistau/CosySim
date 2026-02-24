"""
Bedroom Scene — MCP Rules Initialisation
==========================================
Called from ``BedroomScene.__init__`` after ``_mcp_init()`` to populate the
bedroom's ``MCPSceneNode`` with rules, actions, permission matrix, and
initial atmosphere.

All bedroom logic that used to be scattered across the Python scene file is now
declared here as first-class MCP rules.  The governing interceptor, the agent,
and the Director can all read and apply these rules via the standard MCP tools.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "bedroom"


# ──────────────────────────────────────────────────────────────────────────────
#  INTIMACY GATE RULES
# ──────────────────────────────────────────────────────────────────────────────
#  Each rule has a stat threshold that must be met before the associated
#  action category becomes available.  The rules engine enforces these gates.

_GATE_RULES: List[Dict[str, Any]] = [
    {
        "id"          : "light_touch_gate",
        "label"       : "Light Touch Available",
        "description" : "Soft physical contact (hand-holding, shoulder touch) — always available.",
        "rule_type"   : "always_on",
        "condition"   : {},   # always met
        "effects"     : [],
    },
    {
        "id"          : "kiss_gate",
        "label"       : "Kissing Available",
        "description" : "Kissing becomes natural when warmth ≥ 30 and comfort ≥ 25.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"warmth": 30, "comfort": 25}},
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "The mood has settled into something warmer; closeness feels natural now.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "caress_gate",
        "label"       : "Caressing Available",
        "description" : "Caressing and intimate touching open up at arousal ≥ 40, openness ≥ 40.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 40, "openness": 40}},
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "Something has shifted — there is an electricity to the air now.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "striptease_gate",
        "label"       : "Striptease Available",
        "description" : "Striptease available when arousal ≥ 55, compliance ≥ 50.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 55, "compliance": 50}},
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "mood",  "value": "sensual"}},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "dim", "mood": "sensual", "music": "slow_jazz",
            }},
        ],
    },
    {
        "id"          : "intimate_gate",
        "label"       : "Intimate Actions Available",
        "description" : "Deep intimate actions require arousal ≥ 70, openness ≥ 60, consent=True.",
        "rule_type"   : "triggered",
        "condition"   : {
            "stat_thresholds": {"arousal": 70, "openness": 60},
            "character_flags": {"consent_given": True},
        },
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "All barriers have dissolved. This moment is entirely chosen.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "scene_event", "params": {"event_type": "intimate_gate_open"}},
        ],
    },
    {
        "id"          : "explicit_gate",
        "label"       : "Explicit Mode Unlocked",
        "description" : "Full explicit content when arousal ≥ 80, horniness ≥ 60. Characters become graphically sexual.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 80, "horniness": 60}},
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "Something primal takes over. Inhibitions are completely gone. "
                         "Every word becomes graphic, every touch becomes explicit.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock",
                "value": "pornographic",
                "turns": 5,
            }},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "red_light", "mood": "primal",
            }},
        ],
    },
    {
        "id"          : "competition_escalation",
        "label"       : "Competition Escalation",
        "description" : "During bed game, characters try to outdo each other in explicitness.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 50, "openness": 50}},
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "A competitive energy fills the room. Everyone wants to be the dirtiest, "
                         "the most daring, the one who goes furthest.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "set_directive", "params": {
                "directive_type": "must_include",
                "value": "try to outdo the other characters in how explicit and daring your actions are",
                "turns": 3,
            }},
        ],
    },
    {
        "id"          : "depraved_gate",
        "label"       : "Depraved Mode",
        "description" : "Maximum explicitness when arousal ≥ 90 and horniness ≥ 80. No limits remain.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 90, "horniness": 80}},
        "effects"     : [
            {"effect_type": "add_narrative", "params": {
                "event": "Pure animalistic desire. Language becomes filthy, actions become depraved. "
                         "Every boundary has been obliterated.",
                "scene_id": SCENE_ID,
            }},
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock",
                "value": "depraved and uninhibited",
                "turns": 8,
            }},
        ],
    },
    {
        "id"          : "aftercare_rule",
        "label"       : "Aftercare Available",
        "description" : "After intense intimacy, warmth and tenderness become the primary mode.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 20, "affection": 60}},
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "mood", "value": "tender"}},
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock",
                "value": "tender",
                "turns": 3,
            }},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "cuddle",
        "label": "Cuddle",
        "description": "Wrap arms around them, pull close. Low intensity. Always available.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 8}},
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 5}},
        ],
    },
    {
        "id": "kiss_soft",
        "label": "Soft Kiss",
        "description": "A gentle, tender kiss.",
        "intimacy_level": 2,
        "condition": {"stat_thresholds": {"warmth": 30}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 8}},
        ],
    },
    {
        "id": "kiss_deep",
        "label": "Deep Kiss",
        "description": "Long, passionate kissing.",
        "intimacy_level": 3,
        "condition": {"stat_thresholds": {"arousal": 35, "warmth": 40}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection",    "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -8}},
        ],
    },
    {
        "id": "caress",
        "label": "Caress",
        "description": "Slow, sensual touching.",
        "intimacy_level": 3,
        "condition": {"stat_thresholds": {"arousal": 40, "openness": 35}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",     "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -10}},
        ],
    },
    {
        "id": "striptease",
        "label": "Striptease",
        "description": "A slow, deliberate removal of clothing as performance.",
        "intimacy_level": 4,
        "condition": {"stat_thresholds": {"arousal": 55, "compliance": 50}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",     "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -20}},
            {"effect_type": "scene_event", "params": {"event_type": "striptease_started"}},
        ],
    },
    {
        "id": "deep_talk",
        "label": "Deep Talk",
        "description": "Vulnerable, honest conversation.",
        "intimacy_level": 2,
        "condition": {},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "trust",     "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 8}},
        ],
    },
    {
        "id": "intimate",
        "label": "Intimate",
        "description": "Full intimacy — requires consent and high stats.",
        "intimacy_level": 5,
        "condition": {
            "stat_thresholds": {"arousal": 70, "openness": 60},
            "character_flags": {"consent_given": True},
        },
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 30}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness",    "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "affection",    "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -25}},
            {"effect_type": "add_narrative", "params": {
                "event": "An intimate moment — deeply felt by both.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id": "oral_sex",
        "label": "Oral Sex",
        "description": "Going down — giving or receiving oral pleasure.",
        "intimacy_level": 5,
        "condition": {
            "stat_thresholds": {"arousal": 60, "openness": 55},
            "character_flags": {"consent_given": True},
        },
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "pleasure",     "delta": 30}},
            {"effect_type": "stat_adjust", "params": {"stat": "horniness",    "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -20}},
        ],
    },
    {
        "id": "rough_sex",
        "label": "Rough Sex",
        "description": "Hard, aggressive, dominant sex — hair pulling, spanking, choking.",
        "intimacy_level": 5,
        "condition": {
            "stat_thresholds": {"arousal": 80, "openness": 65},
            "character_flags": {"consent_given": True},
        },
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 35}},
            {"effect_type": "stat_adjust", "params": {"stat": "pleasure",     "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "dominance",    "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "fear",         "delta": 8}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -30}},
            {"effect_type": "add_narrative", "params": {
                "event": "Things turn rough and primal. Inhibitions shatter.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id": "dirty_talk",
        "label": "Dirty Talk",
        "description": "Explicit verbal filth — describing desires, demands, degradation.",
        "intimacy_level": 3,
        "condition": {"stat_thresholds": {"arousal": 40, "openness": 40}},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "horniness",    "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",     "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -15}},
        ],
    },
    {
        "id": "bondage",
        "label": "Bondage",
        "description": "Restraint play — tying up, blindfolding, controlling.",
        "intimacy_level": 5,
        "condition": {
            "stat_thresholds": {"arousal": 65, "openness": 55},
            "character_flags": {"consent_given": True},
        },
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "fear",         "delta": 12}},
            {"effect_type": "stat_adjust", "params": {"stat": "horniness",    "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "dominance",    "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",   "delta": -20}},
        ],
    },
    {
        "id": "orgasm",
        "label": "Orgasm",
        "description": "Climax — the peak of pleasure, then the crash of satisfaction.",
        "intimacy_level": 5,
        "condition": {
            "stat_thresholds": {"arousal": 85, "horniness": 70},
            "character_flags": {"consent_given": True},
        },
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",      "delta": -40}},
            {"effect_type": "stat_adjust", "params": {"stat": "pleasure",     "delta": 40}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness",    "delta": 30}},
            {"effect_type": "stat_adjust", "params": {"stat": "horniness",    "delta": -30}},
            {"effect_type": "stat_adjust", "params": {"stat": "tiredness",    "delta": 15}},
            {"effect_type": "add_narrative", "params": {
                "event": "Waves of orgasm. Muscles clenching, breath catching, pure release.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id": "aftercare",
        "label": "Aftercare",
        "description": "Tender post-intimacy care — holding, soft words, warmth.",
        "intimacy_level": 2,
        "condition": {},
        "effects": [
            {"effect_type": "stat_adjust", "params": {"stat": "affection", "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "happiness", "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "trust",     "delta": 10}},
            {"effect_type": "state_set",   "params": {"field": "mood", "value": "tender"}},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  DIRECTOR RULES  (only the Director can apply these)
# ──────────────────────────────────────────────────────────────────────────────

_DIRECTOR_RULES: List[Dict[str, Any]] = [
    {
        "id"          : "lights_off",
        "label"       : "Lights Off",
        "description" : "Director dims all lights — mood drops to intimate darkness.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "dark", "mood": "intimate",
            }},
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",    "delta": 10}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition", "delta": -10}},
        ],
    },
    {
        "id"          : "mood_lift",
        "label"       : "Mood Lift",
        "description" : "Director injects warmth and joy into the scene.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "stat_adjust",  "params": {"stat": "happiness", "delta": 20}},
            {"effect_type": "stat_adjust",  "params": {"stat": "warmth",    "delta": 15}},
            {"effect_type": "state_set",    "params": {"field": "mood", "value": "joyful"}},
            {"effect_type": "set_directive","params": {
                "directive_type": "style_lock", "value": "playful", "turns": 2,
            }},
        ],
    },
    {
        "id"          : "escalate",
        "label"       : "Escalate",
        "description" : "Director escalates the scene — stat boost across the board.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition","delta": -15}},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "candlelight", "mood": "intense",
                "music": "slow_pulse",
            }},
        ],
    },
    {
        "id"          : "reset",
        "label"       : "Reset Scene",
        "description" : "Director resets all stats and atmosphere to neutral defaults.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "mood", "value": "neutral"}},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "evening", "mood": "relaxed", "music": "ambient",
            }},
        ],
    },
    {
        "id"          : "max_arousal",
        "label"       : "Max Arousal",
        "description" : "Director maxes out arousal and horniness — instant heat.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",     "delta": 50}},
            {"effect_type": "stat_adjust", "params": {"stat": "horniness",   "delta": 50}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",    "delta": 30}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition",  "delta": -40}},
            {"effect_type": "set_directive", "params": {
                "directive_type": "style_lock", "value": "pornographic", "turns": 5,
            }},
            {"effect_type": "set_atmosphere", "params": {
                "scene_id": SCENE_ID, "lighting": "red_light", "mood": "primal",
            }},
        ],
    },
    {
        "id"          : "strip_everyone",
        "label"       : "Strip Everyone",
        "description" : "Director orders all clothes off — everyone naked immediately.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 20}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 25}},
            {"effect_type": "stat_adjust", "params": {"stat": "inhibition","delta": -25}},
            {"effect_type": "add_narrative", "params": {
                "event": "The Director commands: all clothes off. NOW.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "dare_them",
        "label"       : "Dare Them",
        "description" : "Director dares characters to do something filthy — they must comply or be punished.",
        "rule_type"   : "director_only",
        "effects"     : [
            {"effect_type": "stat_adjust", "params": {"stat": "arousal",   "delta": 15}},
            {"effect_type": "stat_adjust", "params": {"stat": "openness",  "delta": 20}},
            {"effect_type": "set_directive", "params": {
                "directive_type": "must_include",
                "value": "comply with the dare enthusiastically and describe it in explicit detail",
                "turns": 2,
            }},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  CONSENT MANAGEMENT RULES
# ──────────────────────────────────────────────────────────────────────────────

_CONSENT_RULES: List[Dict[str, Any]] = [
    {
        "id"          : "grant_consent",
        "label"       : "Grant Consent",
        "description" : "Character explicitly consents to intimate actions.",
        "rule_type"   : "triggered",
        "condition"   : {"stat_thresholds": {"arousal": 45, "trust": 35}},
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "consent_given", "value": True}},
            {"effect_type": "add_narrative", "params": {
                "event": "Consent given — a pivotal moment of trust.",
                "scene_id": SCENE_ID,
            }},
        ],
    },
    {
        "id"          : "withdraw_consent",
        "label"       : "Withdraw Consent",
        "description" : "Character withdraws consent — all intimate actions stop.",
        "rule_type"   : "always_on",
        "effects"     : [
            {"effect_type": "state_set", "params": {"field": "consent_given", "value": False}},
            {"effect_type": "add_restriction", "params": {"restriction": "no_intimate_actions"}},
            {"effect_type": "set_directive", "params": {
                "directive_type": "must_include",
                "value": "pauses and steps back",
                "turns": 1,
            }},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  TIMED ACTION RULES  (using MCPTimer + ScheduledConsequence)
# ──────────────────────────────────────────────────────────────────────────────

TIMED_ACTION_DURATIONS: Dict[str, int] = {
    "striptease"  : 45,   # seconds
    "massage"     : 120,
    "intimate"    : 180,
    "deep_talk"   : 90,
    "dance"       : 60,
}


# ──────────────────────────────────────────────────────────────────────────────
#  REGISTER EVERYTHING
# ──────────────────────────────────────────────────────────────────────────────

def register_bedroom_rules() -> None:
    """
    Called once during BedroomScene initialisation.

    Registers all rules and actions for the bedroom scene into the
    MCPFramework's SceneNode and SceneRulesEngine.

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
        all_rule_defs = _GATE_RULES + _DIRECTOR_RULES + _CONSENT_RULES
        for r in all_rule_defs:
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

        # ── Default atmosphere ──────────────────────────────────────────────
        ssm.set_atmosphere(SCENE_ID, lighting="evening", mood="relaxed", music="ambient")

        logger.info("Bedroom MCP rules registered: %d rules, %d actions",
                    len(all_rule_defs), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_bedroom_rules failed: %s", exc)


def get_timed_action_duration(action_type: str) -> int:
    """Return the MCP-managed duration in seconds for a timed action."""
    return TIMED_ACTION_DURATIONS.get(action_type, 60)
