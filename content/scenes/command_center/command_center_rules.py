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

def register_command_center_rules() -> None:
    """Register all command center rules with the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import get_rules_engine
        engine = get_rules_engine()
        for rule in _MONITORING_RULES + _ACCESS_RULES:
            engine.add_rule(SCENE_ID, rule)
        for action in _ACTIONS:
            engine.register_action(SCENE_ID, action)
        logger.info("Registered %d command center rules + %d actions",
                     len(_MONITORING_RULES) + len(_ACCESS_RULES), len(_ACTIONS))
    except Exception as exc:
        logger.warning("Failed to register command center rules: %s", exc)
