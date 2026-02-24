"""
Coders Room — MCP Rules Initialisation
========================================
Registers coding pipeline rules, code quality gates, agent role rules,
and phase transition mechanics into the SceneRulesEngine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SCENE_ID = "coders"


_RULES: List[Dict[str, Any]] = [
    {
        "id": "phase_progression",
        "label": "Phase Progression",
        "description": "Pipeline must follow phase order: FEATURE → DESIGN → CODING → REVIEW → TESTING.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "reviewer_speaks_first",
        "label": "Reviewer Speaks First",
        "description": "In FEATURE and REVIEW phases, the Reviewer agent provides analysis before Writer acts.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "writer_codes",
        "label": "Writer Generates Code",
        "description": "In CODING phase, only the Writer agent produces code.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "qa_tests",
        "label": "QA Tests Code",
        "description": "In TESTING phase, QA runs sandboxed tests and reports results.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "code_quality_gate",
        "label": "Code Quality Gate",
        "description": "Code must pass sandboxed execution without errors to advance past CODING.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"test_pass_rate": 100}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "All tests pass! Code quality gate cleared.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "failure_rollback",
        "label": "Failure Rollback",
        "description": "If tests fail 3 consecutive times, phase rolls back to DESIGN.",
        "rule_type": "triggered",
        "condition": {"stat_thresholds": {"consecutive_failures": 3}},
        "effects": [{"effect_type": "add_narrative", "params": {
            "event": "Too many failures — rolling back to DESIGN phase.",
            "scene_id": SCENE_ID,
        }}],
    },
    {
        "id": "feature_auto_queue",
        "label": "Feature Auto-Queue",
        "description": "When feature queue is empty, system auto-generates a new feature spec.",
        "rule_type": "always_on",
        "condition": {},
        "effects": [],
    },
    {
        "id": "agent_encouragement",
        "label": "Agent Encouragement",
        "description": "After successful test runs, agents receive positive feedback boosting morale.",
        "rule_type": "triggered",
        "condition": {},
        "effects": [],
    },
]


_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "submit_feature",
        "label": "Submit Feature",
        "description": "Submit a new feature request to the coding pipeline.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "run_tests",
        "label": "Run Tests",
        "description": "Execute sandboxed tests against the current code.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "approve_code",
        "label": "Approve Code",
        "description": "Approve the current code during review phase.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
    {
        "id": "reject_code",
        "label": "Reject Code",
        "description": "Reject code and send back for revision.",
        "intimacy_level": 1,
        "condition": {},
        "effects": [],
    },
]


def register_coders_rules() -> None:
    """Register Coders Room rules and actions into the SceneRulesEngine."""
    try:
        from engine.mcp.scene_rules_engine import (
            get_rules_engine, ActionDefinition, RuleDefinition,
            RuleEffect, RuleCondition,
        )
        from engine.mcp.scene_state import get_scene_state_manager

        eng = get_rules_engine()
        ssm = get_scene_state_manager()

        if eng.get_rules(SCENE_ID):
            return

        for r in _RULES:
            cond_data = r.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None
            effects = [RuleEffect(**e) for e in r.get("effects", [])]
            eng.add_rule(SCENE_ID, RuleDefinition(
                rule_id=r["id"], label=r["label"], description=r["description"],
                rule_type=r["rule_type"], condition=condition, effects=effects,
            ))

        for a in _ACTIONS:
            cond_data = a.get("condition", {})
            condition = RuleCondition(
                stat_thresholds=cond_data.get("stat_thresholds", {}),
                character_flags=cond_data.get("character_flags", {}),
            ) if cond_data else None
            effects = [RuleEffect(**e) for e in a.get("effects", [])]
            eng.add_action(SCENE_ID, ActionDefinition(
                action_id=a["id"], label=a["label"], description=a["description"],
                intimacy_level=a.get("intimacy_level", 1), condition=condition, effects=effects,
            ))

        ssm.set_atmosphere(SCENE_ID, lighting="terminal", mood="focused", music="lo-fi")
        logger.info("Coders MCP rules registered: %d rules, %d actions", len(_RULES), len(_ACTIONS))

    except Exception as exc:
        logger.warning("register_coders_rules failed: %s", exc)
