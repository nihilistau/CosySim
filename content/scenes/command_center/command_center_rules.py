"""
Command Center Rules — MCP Rules Initialisation
=================================================
Registers monitoring rules, alert thresholds, and access policies
into the SceneRulesEngine for the Command Center scene.

Called from ``CommandCenterScene.start()`` during MCP initialisation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "command_center"


# ──────────────────────────────────────────────────────────────────────────────
#  MONITORING RULES — alert thresholds, access policies
# ──────────────────────────────────────────────────────────────────────────────

_MONITORING_RULES: List[Dict[str, Any]] = [
    {
        "id": "gpu_vram_warning",
        "label": "GPU VRAM Warning",
        "description": "Alert when GPU VRAM usage exceeds 80%.",
        "rule_type": "threshold",
        "condition": {"metric": "gpu_vram_pct", "operator": ">", "value": 80},
        "effects": [{"effect_type": "alert", "params": {
            "level": "yellow", "node": "gpu_primary"
        }}],
    },
    {
        "id": "gpu_vram_critical",
        "label": "GPU VRAM Critical",
        "description": "Critical alert when GPU VRAM exceeds 95%.",
        "rule_type": "threshold",
        "condition": {"metric": "gpu_vram_pct", "operator": ">", "value": 95},
        "effects": [{"effect_type": "alert", "params": {
            "level": "red", "node": "gpu_primary"
        }}],
    },
    {
        "id": "queue_depth_warning",
        "label": "Queue Depth Warning",
        "description": "Alert when pipeline queue exceeds 5 pending requests.",
        "rule_type": "threshold",
        "condition": {"metric": "queue_depth", "operator": ">", "value": 5},
        "effects": [{"effect_type": "alert", "params": {
            "level": "yellow", "node": "pipeline"
        }}],
    },
    {
        "id": "high_latency",
        "label": "High Latency Alert",
        "description": "Alert when average LLM latency exceeds 2 seconds.",
        "rule_type": "threshold",
        "condition": {"metric": "avg_latency_ms", "operator": ">", "value": 2000},
        "effects": [{"effect_type": "alert", "params": {
            "level": "red", "node": "inference"
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACCESS RULES — who can inject events, edit stats, etc.
# ──────────────────────────────────────────────────────────────────────────────

_ACCESS_RULES: List[Dict[str, Any]] = [
    {
        "id": "director_only",
        "label": "Director Access Only",
        "description": "Scene injection and stat editing require director privileges.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [{"effect_type": "access_gate", "params": {
            "role": "director", "actions": ["inject", "edit_stats", "force_directive"]
        }}],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  ACTIONS — what the command center can do
# ──────────────────────────────────────────────────────────────────────────────

_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "view_dashboard",
        "label": "View Dashboard",
        "description": "Open the full system dashboard.",
        "cooldown": 0,
    },
    {
        "id": "inject_narrative",
        "label": "Inject Narrative",
        "description": "Inject a narrative event into any active scene.",
        "cooldown": 5,
    },
    {
        "id": "inject_directive",
        "label": "Send Directive",
        "description": "Send a behavioral directive to a scene's dialog system.",
        "cooldown": 5,
    },
    {
        "id": "edit_character_stats",
        "label": "Edit Character Stats",
        "description": "Live-edit any character's stats.",
        "cooldown": 2,
    },
    {
        "id": "cycle_scene_monitor",
        "label": "Cycle Scene Monitor",
        "description": "Switch the live monitor to view a different scene.",
        "cooldown": 0,
    },
]


# ──────────────────────────────────────────────────────────────────────────────
#  REGISTRATION
# ──────────────────────────────────────────────────────────────────────────────

# v1.58.0 [2026-06-11] — Rewritten to the real SceneRulesEngine API.
# The old code called add_rule(SCENE_ID, dict) / register_action(SCENE_ID, dict);
# add_rule() takes a single RuleDefinition and register_action() never existed,
# so every command-center rule silently failed to register since v1.42.
def register_command_center_rules() -> None:
    """Register all command center rules with the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import (
            ActionDefinition, RuleDefinition, RuleEffect, get_rules_engine,
        )
        engine = get_rules_engine()
        for r in _MONITORING_RULES + _ACCESS_RULES:
            # Threshold conditions ({metric, operator, value}) are evaluated by
            # the scene's own metric monitor, not RuleCondition — registered
            # here for Director/agent visibility via get_rules_text().
            engine.add_rule(RuleDefinition(
                rule_id=r["id"],
                scene=SCENE_ID,
                label=r["label"],
                description=r["description"],
                rule_type=r["rule_type"],
                effects=[RuleEffect(**e) for e in r.get("effects", [])],
            ))
        for a in _ACTIONS:
            engine.add_action(ActionDefinition(
                action_id=a["id"],
                scene=SCENE_ID,
                label=a["label"],
                description=a["description"],
                category="environment",
                cooldown_secs=float(a.get("cooldown", 0)),
            ))
        logger.info("[%s] Registered %d rules + %d actions (operation=rules_init)",
                    SCENE_ID,
                    len(_MONITORING_RULES) + len(_ACCESS_RULES), len(_ACTIONS))
    except Exception as exc:
        logger.warning("[%s] Failed to register rules (operation=rules_init): %s",
                       SCENE_ID, exc)
