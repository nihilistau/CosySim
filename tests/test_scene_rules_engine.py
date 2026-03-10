"""
Tests for the Scene Rules Engine — rule management, action definitions,
permission matrix, and bootstrapped rules.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────

def _fresh_engine():
    """Create a fresh SceneRulesEngine (bypass singleton for test isolation)."""
    from engine.mcp.scene_rules_engine import SceneRulesEngine
    return SceneRulesEngine()


def _make_rule(**overrides):
    """Shorthand to create a RuleDefinition with sensible defaults."""
    from engine.mcp.scene_rules_engine import RuleDefinition
    defaults = dict(
        rule_id="test_rule",
        scene="penthouse",
        label="Test Rule",
        description="A test rule",
        rule_type="always_on",
        priority=50,
    )
    defaults.update(overrides)
    return RuleDefinition(**defaults)


def _make_action(**overrides):
    """Shorthand to create an ActionDefinition with sensible defaults."""
    from engine.mcp.scene_rules_engine import ActionDefinition
    defaults = dict(
        action_id="test_action",
        scene="penthouse",
        label="Test Action",
        description="A test action",
        intimacy_level=1,
        category="physical",
    )
    defaults.update(overrides)
    return ActionDefinition(**defaults)


# ══════════════════════════════════════════════════════════════════════
#  RuleCondition tests
# ══════════════════════════════════════════════════════════════════════

class TestRuleCondition:
    def test_empty_condition_always_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition()
        assert cond.is_met() is True

    def test_stat_threshold_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(stat_thresholds={"arousal": 30})
        assert cond.is_met(stats={"arousal": 50}) is True

    def test_stat_threshold_not_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(stat_thresholds={"arousal": 30})
        assert cond.is_met(stats={"arousal": 10}) is False

    def test_stat_threshold_missing_stat_defaults_zero(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(stat_thresholds={"arousal": 30})
        assert cond.is_met(stats={}) is False

    def test_scene_flags_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(scene_flags={"lights_off": True})
        assert cond.is_met(scene_state={"lights_off": True}) is True

    def test_scene_flags_not_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(scene_flags={"lights_off": True})
        assert cond.is_met(scene_state={"lights_off": False}) is False

    def test_character_flags(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(character_flags={"dominant": True})
        assert cond.is_met(char_flags={"dominant": True}) is True
        assert cond.is_met(char_flags={"dominant": False}) is False

    def test_any_of_stats_one_passes(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(any_of_stats={"arousal": 50, "openness": 50})
        assert cond.is_met(stats={"arousal": 60, "openness": 10}) is True

    def test_any_of_stats_none_pass(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(any_of_stats={"arousal": 50, "openness": 50})
        assert cond.is_met(stats={"arousal": 10, "openness": 10}) is False

    def test_combined_conditions(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        cond = RuleCondition(
            stat_thresholds={"arousal": 30},
            scene_flags={"lights_off": True},
        )
        assert cond.is_met(stats={"arousal": 40}, scene_state={"lights_off": True}) is True
        assert cond.is_met(stats={"arousal": 40}, scene_state={"lights_off": False}) is False
        assert cond.is_met(stats={"arousal": 10}, scene_state={"lights_off": True}) is False


# ══════════════════════════════════════════════════════════════════════
#  RuleEffect tests
# ══════════════════════════════════════════════════════════════════════

class TestRuleEffect:
    def test_to_dict(self):
        from engine.mcp.scene_rules_engine import RuleEffect
        eff = RuleEffect("stat_adjust", {"stat": "arousal", "delta": 15})
        d = eff.to_dict()
        assert d["effect_type"] == "stat_adjust"
        assert d["params"]["stat"] == "arousal"


# ══════════════════════════════════════════════════════════════════════
#  RuleDefinition tests
# ══════════════════════════════════════════════════════════════════════

class TestRuleDefinition:
    def test_applies_to_specific_scene(self):
        rule = _make_rule(scene="penthouse")
        assert rule.applies_to("penthouse") is True
        assert rule.applies_to("phone") is False

    def test_applies_to_wildcard(self):
        rule = _make_rule(scene="*")
        assert rule.applies_to("penthouse") is True
        assert rule.applies_to("phone") is True
        assert rule.applies_to("anything") is True

    def test_to_dict(self):
        rule = _make_rule()
        d = rule.to_dict()
        assert d["rule_id"] == "test_rule"
        assert d["label"] == "Test Rule"
        assert "enabled" in d
        assert "priority" in d

    def test_default_values(self):
        rule = _make_rule()
        assert rule.enabled is True
        assert rule.can_be_disabled is True
        assert rule.rule_type == "always_on"


# ══════════════════════════════════════════════════════════════════════
#  ActionDefinition tests
# ══════════════════════════════════════════════════════════════════════

class TestActionDefinition:
    def test_is_available_default(self):
        action = _make_action()
        avail, reason = action.is_available("aria")
        assert avail is True
        assert reason == "allowed"

    def test_is_available_forbidden(self):
        action = _make_action(forbidden_for={"aria"})
        avail, reason = action.is_available("aria")
        assert avail is False
        assert "forbidden" in reason

    def test_is_available_condition_not_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        action = _make_action(condition=RuleCondition(stat_thresholds={"arousal": 50}))
        avail, reason = action.is_available("aria", stats={"arousal": 10})
        assert avail is False

    def test_is_available_condition_met(self):
        from engine.mcp.scene_rules_engine import RuleCondition
        action = _make_action(condition=RuleCondition(stat_thresholds={"arousal": 50}))
        avail, reason = action.is_available("aria", stats={"arousal": 60})
        assert avail is True

    def test_cooldown_blocks(self):
        action = _make_action(cooldown_secs=60.0)
        action.last_used["aria"] = time.time()
        avail, reason = action.is_available("aria")
        assert avail is False
        assert "cooldown" in reason

    def test_cooldown_expired(self):
        action = _make_action(cooldown_secs=1.0)
        action.last_used["aria"] = time.time() - 2.0
        avail, reason = action.is_available("aria")
        assert avail is True

    def test_to_dict(self):
        action = _make_action()
        d = action.to_dict()
        assert d["action_id"] == "test_action"
        assert d["label"] == "Test Action"
        assert "intimacy_level" in d


# ══════════════════════════════════════════════════════════════════════
#  PermissionMatrix tests
# ══════════════════════════════════════════════════════════════════════

class TestPermissionMatrix:
    def _make(self):
        from engine.mcp.scene_rules_engine import PermissionMatrix
        return PermissionMatrix()

    def test_default_allowed(self):
        pm = self._make()
        ok, reason = pm.check("penthouse", "aria", "kiss")
        assert ok is True
        assert "default" in reason

    def test_deny_blocks(self):
        pm = self._make()
        pm.deny("penthouse", "aria", "kiss")
        ok, reason = pm.check("penthouse", "aria", "kiss")
        assert ok is False
        assert "denied" in reason

    def test_allow_overrides_deny(self):
        pm = self._make()
        pm.deny("penthouse", "aria", "kiss")
        pm.allow("penthouse", "aria", "kiss")
        ok, reason = pm.check("penthouse", "aria", "kiss")
        assert ok is True

    def test_reset_clears_all(self):
        pm = self._make()
        pm.deny("penthouse", "aria", "kiss")
        pm.reset("penthouse")
        ok, _ = pm.check("penthouse", "aria", "kiss")
        assert ok is True

    def test_reset_specific_character(self):
        pm = self._make()
        pm.deny("penthouse", "aria", "kiss")
        pm.deny("penthouse", "luna", "kiss")
        pm.reset("penthouse", character_id="aria")
        ok_aria, _ = pm.check("penthouse", "aria", "kiss")
        ok_luna, _ = pm.check("penthouse", "luna", "kiss")
        assert ok_aria is True
        assert ok_luna is False


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — bootstrap verification
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEngineBootstrap:
    def test_init_bootstraps_rules(self):
        eng = _fresh_engine()
        # Should have global rules
        all_rules = eng.get_rules("penthouse")
        rule_ids = [r.rule_id for r in all_rules]
        assert "consent_always" in rule_ids
        assert "memory_continuity" in rule_ids
        assert "authentic_voice" in rule_ids

    def test_global_rules_apply_to_all_scenes(self):
        eng = _fresh_engine()
        bedroom_ids = {r.rule_id for r in eng.get_rules("penthouse")}
        phone_ids = {r.rule_id for r in eng.get_rules("phone")}
        # Global rules appear in both
        assert "consent_always" in bedroom_ids
        assert "consent_always" in phone_ids

    def test_bedroom_specific_rules(self):
        eng = _fresh_engine()
        rules = eng.get_rules("penthouse")
        rule_ids = [r.rule_id for r in rules]
        assert "penthouse_wardrobe_first" in rule_ids
        assert "penthouse_stats_drive_behaviour" in rule_ids

    def test_bedroom_rules_not_in_phone(self):
        eng = _fresh_engine()
        phone_ids = {r.rule_id for r in eng.get_rules("phone")}
        assert "penthouse_wardrobe_first" not in phone_ids

    def test_phone_specific_rules(self):
        eng = _fresh_engine()
        rules = eng.get_rules("phone")
        rule_ids = [r.rule_id for r in rules]
        assert "phone_read_history" in rule_ids
        assert "phone_no_walls" in rule_ids

    def test_phone_rules_not_in_bedroom(self):
        eng = _fresh_engine()
        bedroom_ids = {r.rule_id for r in eng.get_rules("penthouse")}
        assert "phone_read_history" not in bedroom_ids

    def test_bedroom_actions_bootstrapped(self):
        eng = _fresh_engine()
        action = eng.get_action("cuddle")
        assert action is not None
        assert action.scene == "penthouse"

    def test_phone_actions_bootstrapped(self):
        eng = _fresh_engine()
        action = eng.get_action("flirt_text")
        assert action is not None
        assert action.scene == "phone"

    def test_consent_rule_cannot_be_disabled(self):
        eng = _fresh_engine()
        result = eng.toggle_rule("consent_always", enabled=False)
        assert result is False  # can_be_disabled=False

    def test_rules_sorted_by_priority(self):
        eng = _fresh_engine()
        rules = eng.get_rules("penthouse")
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities)


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — rule management
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEngineRuleManagement:
    def test_add_rule(self):
        eng = _fresh_engine()
        custom = _make_rule(rule_id="custom_rule", scene="penthouse",
                            label="Custom", priority=100)
        eng.add_rule(custom)
        rules = eng.get_rules("penthouse")
        assert any(r.rule_id == "custom_rule" for r in rules)

    def test_add_rule_replaces_existing(self):
        eng = _fresh_engine()
        r1 = _make_rule(rule_id="dup", label="First")
        r2 = _make_rule(rule_id="dup", label="Second")
        eng.add_rule(r1)
        eng.add_rule(r2)
        rules = [r for r in eng.get_rules("penthouse") if r.rule_id == "dup"]
        assert len(rules) == 1
        assert rules[0].label == "Second"

    def test_remove_rule(self):
        eng = _fresh_engine()
        eng.add_rule(_make_rule(rule_id="removeme"))
        assert eng.remove_rule("removeme") is True
        assert eng.remove_rule("removeme") is False  # already removed

    def test_toggle_rule(self):
        eng = _fresh_engine()
        eng.add_rule(_make_rule(rule_id="togglable", can_be_disabled=True))
        assert eng.toggle_rule("togglable", enabled=False) is True
        rules = eng.get_rules("penthouse")
        assert not any(r.rule_id == "togglable" for r in rules)  # disabled = excluded

    def test_toggle_nonexistent_rule(self):
        eng = _fresh_engine()
        assert eng.toggle_rule("does_not_exist", enabled=True) is False

    def test_get_rules_filter_by_type(self):
        eng = _fresh_engine()
        always_on = eng.get_rules("penthouse", rule_type="always_on")
        director = eng.get_rules("penthouse", rule_type="director_only")
        assert all(r.rule_type == "always_on" for r in always_on)
        assert all(r.rule_type == "director_only" for r in director)

    def test_get_rules_for_nonexistent_scene(self):
        eng = _fresh_engine()
        rules = eng.get_rules("nonexistent_scene")
        # Only global (*) rules should appear
        assert all(r.scene == "*" for r in rules)

    def test_higher_priority_first(self):
        eng = _fresh_engine()
        eng.add_rule(_make_rule(rule_id="low", priority=100, scene="test_scene"))
        eng.add_rule(_make_rule(rule_id="high", priority=5, scene="test_scene"))
        eng.add_rule(_make_rule(rule_id="mid", priority=50, scene="test_scene"))
        rules = eng.get_rules("test_scene")
        scene_rules = [r for r in rules if r.scene == "test_scene"]
        assert scene_rules[0].rule_id == "high"
        assert scene_rules[-1].rule_id == "low"


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — action management
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEngineActionManagement:
    def test_add_action(self):
        eng = _fresh_engine()
        eng.add_action(_make_action(action_id="custom_act", scene="penthouse"))
        assert eng.get_action("custom_act") is not None

    def test_get_action_nonexistent(self):
        eng = _fresh_engine()
        assert eng.get_action("doesnt_exist") is None

    def test_get_available_actions_bedroom(self):
        eng = _fresh_engine()
        actions = eng.get_available_actions("penthouse", "aria",
                                            stats={"arousal": 0, "openness": 0})
        assert isinstance(actions, list)
        assert len(actions) > 0
        # At least cuddle should be available (no conditions)
        cuddle = [a for a in actions if a["action_id"] == "cuddle"]
        assert len(cuddle) == 1
        assert cuddle[0]["available"] is True

    def test_get_available_actions_filters_by_stats(self):
        eng = _fresh_engine()
        # With low stats, striptease should be unavailable
        actions = eng.get_available_actions("penthouse", "aria",
                                            stats={"arousal": 0, "openness": 0})
        striptease = [a for a in actions if a["action_id"] == "striptease"]
        if striptease:
            assert striptease[0]["available"] is False

    def test_get_available_actions_permission_denied(self):
        eng = _fresh_engine()
        eng.deny_action("penthouse", "aria", "cuddle")
        actions = eng.get_available_actions("penthouse", "aria")
        cuddle = [a for a in actions if a["action_id"] == "cuddle"]
        assert len(cuddle) == 0  # denied actions are excluded


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — permission management
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEnginePermissions:
    def test_check_permission_default(self):
        eng = _fresh_engine()
        ok, reason = eng.check_permission("penthouse", "aria", "anything")
        assert ok is True

    def test_deny_and_check(self):
        eng = _fresh_engine()
        eng.deny_action("penthouse", "aria", "striptease")
        ok, reason = eng.check_permission("penthouse", "aria", "striptease")
        assert ok is False

    def test_allow_overrides_deny(self):
        eng = _fresh_engine()
        eng.deny_action("penthouse", "aria", "striptease")
        eng.allow_action("penthouse", "aria", "striptease")
        ok, _ = eng.check_permission("penthouse", "aria", "striptease")
        assert ok is True


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — rule application
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEngineApplyRule:
    def test_apply_rule_success(self):
        from engine.mcp.scene_rules_engine import RuleEffect
        eng = _fresh_engine()
        eng.add_rule(_make_rule(
            rule_id="boost",
            effects=[RuleEffect("stat_adjust", {"stat": "arousal", "delta": 10})],
        ))
        with patch("engine.mcp.state_coordinator.get_coordinator") as mock_coord:
            result = eng.apply_rule("penthouse", "boost", target_ids=["aria"])
        assert result["ok"] is True
        assert result["rule_id"] == "boost"
        assert len(result["effects_applied"]) == 1

    def test_apply_rule_not_found(self):
        eng = _fresh_engine()
        result = eng.apply_rule("penthouse", "nonexistent_rule")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_apply_rule_disabled(self):
        eng = _fresh_engine()
        eng.add_rule(_make_rule(rule_id="disabled_rule", enabled=False))
        result = eng.apply_rule("penthouse", "disabled_rule")
        assert result["ok"] is False
        assert "disabled" in result["error"]

    def test_apply_action_not_found(self):
        eng = _fresh_engine()
        result = eng.apply_action("penthouse", "nonexistent", "aria")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_apply_action_permission_denied(self):
        eng = _fresh_engine()
        eng.deny_action("penthouse", "aria", "cuddle")
        result = eng.apply_action("penthouse", "cuddle", "aria")
        assert result["ok"] is False


# ══════════════════════════════════════════════════════════════════════
#  SceneRulesEngine — rules text and summary
# ══════════════════════════════════════════════════════════════════════

class TestSceneRulesEngineText:
    def test_get_rules_text_contains_scene_name(self):
        eng = _fresh_engine()
        text = eng.get_rules_text("penthouse")
        assert "penthouse" in text

    def test_get_rules_text_contains_always_active(self):
        eng = _fresh_engine()
        text = eng.get_rules_text("penthouse")
        assert "ALWAYS ACTIVE" in text

    def test_get_scene_summary(self):
        eng = _fresh_engine()
        summary = eng.get_scene_summary("penthouse", character_id="aria")
        assert summary["scene"] == "penthouse"
        assert "rules" in summary
        assert "actions" in summary
        assert len(summary["rules"]) > 0

    def test_get_scene_summary_no_character(self):
        eng = _fresh_engine()
        summary = eng.get_scene_summary("penthouse")
        assert summary["actions"] == []
        assert len(summary["rules"]) > 0


# ══════════════════════════════════════════════════════════════════════
#  Edge cases
# ══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_scene_returns_only_global_rules(self):
        eng = _fresh_engine()
        rules = eng.get_rules("")
        # Wildcard rules match empty string
        assert all(r.scene == "*" for r in rules)

    def test_get_available_actions_empty_scene(self):
        eng = _fresh_engine()
        actions = eng.get_available_actions("nonexistent", "aria")
        assert actions == []

    def test_multiple_effects_on_rule(self):
        from engine.mcp.scene_rules_engine import RuleEffect
        eng = _fresh_engine()
        rule = _make_rule(
            rule_id="multi_fx",
            effects=[
                RuleEffect("stat_adjust", {"stat": "arousal", "delta": 10}),
                RuleEffect("stat_adjust", {"stat": "openness", "delta": 5}),
                RuleEffect("add_narrative", {"event": "Something happened"}),
            ],
        )
        eng.add_rule(rule)
        found = [r for r in eng.get_rules("penthouse") if r.rule_id == "multi_fx"]
        assert len(found) == 1
        assert len(found[0].effects) == 3
