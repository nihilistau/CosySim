"""
Heist scene rules — register with SceneRulesEngine for phase-gated actions.

These rules control what actions are available in each phase and how the
AI agents are nudged to behave appropriately during the heist.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_heist_rules():
    """Register heist-specific rules with the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import get_scene_rules_engine
        engine = get_scene_rules_engine()
    except Exception:
        logger.debug("SceneRulesEngine not available, skipping heist rules")
        return

    # Phase-gated directives
    engine.register_rule("heist", "planning_mode", {
        "condition": {"phase": "planning"},
        "directive": (
            "You are in the PLANNING phase. Discuss strategy with the crew. "
            "Consider each member's specialty. Assign roles. Scout the venue. "
            "Do NOT attempt to enter the target yet."
        ),
        "priority": 10,
    })

    engine.register_rule("heist", "approach_mode", {
        "condition": {"phase": "approach"},
        "directive": (
            "You are APPROACHING the target. Be stealthy. Avoid suspicion. "
            "Use disguises, distractions, or social engineering to get close. "
            "Watch for patrols and cameras."
        ),
        "priority": 10,
    })

    engine.register_rule("heist", "execution_mode", {
        "condition": {"phase": "execution"},
        "directive": (
            "You are INSIDE the target. Work fast. Clear obstacles. "
            "Crack safes, disable alarms, handle guards. Every turn raises "
            "time pressure. Coordinate with your crew."
        ),
        "priority": 10,
    })

    engine.register_rule("heist", "escape_mode", {
        "condition": {"phase": "escape"},
        "directive": (
            "GET OUT! The heist is done. Escape before the cops arrive. "
            "Use the getaway vehicle. Handle roadblocks. Split up if needed. "
            "Protect the loot."
        ),
        "priority": 10,
    })

    # Suspicion-based escalation
    engine.register_rule("heist", "low_suspicion", {
        "condition": {"suspicion_below": 30},
        "directive": "Things are calm. You have time to plan carefully.",
        "priority": 5,
    })

    engine.register_rule("heist", "medium_suspicion", {
        "condition": {"suspicion_range": [30, 60]},
        "directive": (
            "Guards are getting suspicious. Be more careful. "
            "Avoid loud actions. Consider distractions."
        ),
        "priority": 7,
    })

    engine.register_rule("heist", "high_suspicion", {
        "condition": {"suspicion_above": 60},
        "directive": (
            "DANGER! Suspicion is critically high. One more mistake and "
            "you're busted. Consider aborting or rushing the objective."
        ),
        "priority": 9,
    })

    # Specialty nudges
    engine.register_rule("heist", "use_specialty", {
        "condition": {"always": True},
        "directive": (
            "Remember your specialty — use it! "
            "Call heist_action with actions that match your skills for best results."
        ),
        "priority": 3,
    })

    logger.info("Heist rules registered (%d rules)", 7)
