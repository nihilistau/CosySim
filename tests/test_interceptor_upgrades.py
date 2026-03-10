"""
Tests for interceptor upgrades:
- ConversationVarietyInterceptor thread safety
- MoodSyncInterceptor threshold rule auto-evaluation
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ── ConversationVarietyInterceptor thread safety ──────────────────


class TestConversationVarietyThreadSafety:
    """Verify that concurrent post_call writes don't corrupt state."""

    def _make_interceptor(self):
        from engine.agents.interceptors import ConversationVarietyInterceptor
        inst = ConversationVarietyInterceptor()
        # Reset class-level state for isolation
        ConversationVarietyInterceptor._recent_responses = {}
        return inst

    def test_has_lock(self):
        from engine.agents.interceptors import ConversationVarietyInterceptor
        assert hasattr(ConversationVarietyInterceptor, "_recent_lock")
        assert isinstance(ConversationVarietyInterceptor._recent_lock, type(threading.Lock()))

    def test_concurrent_post_calls_no_corruption(self):
        """Hammer post_call from 10 threads simultaneously."""
        interceptor = self._make_interceptor()
        errors = []

        def worker(agent_id, reply):
            try:
                ctx = {"agent_id": agent_id, "reply": reply, "scene": "test"}
                interceptor.post_call(ctx)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            agent_id = f"agent_{i % 3}"  # 3 agents, concurrent writes
            t = threading.Thread(target=worker, args=(agent_id, f"reply_{i}"))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread errors: {errors}"
        # Verify state is consistent
        from engine.agents.interceptors import ConversationVarietyInterceptor
        for agent_id, responses in ConversationVarietyInterceptor._recent_responses.items():
            assert len(responses) <= ConversationVarietyInterceptor._MAX_TRACKED

    def test_pre_call_reads_snapshot(self):
        """pre_call should read a snapshot, not hold lock during prompt building."""
        interceptor = self._make_interceptor()
        from engine.agents.interceptors import ConversationVarietyInterceptor
        ConversationVarietyInterceptor._recent_responses["agent_a"] = [
            "hello there", "how are you",
        ]
        ctx = {"agent_id": "agent_a", "system_prompt": "", "scene": "test"}
        interceptor.pre_call(ctx)
        assert "CONVERSATION VARIETY" in ctx["system_prompt"]


# ── MoodSyncInterceptor threshold rules ──────────────────────────


class TestMoodSyncThresholdRules:
    """Verify that MoodSyncInterceptor auto-fires threshold rules."""

    def _make_interceptor(self):
        from engine.agents.interceptors import MoodSyncInterceptor
        return MoodSyncInterceptor()

    def _make_parsed(self, mood="happy", intensity=0.8):
        """Create a mock ParsedResponse."""
        parsed = MagicMock()
        parsed.mood = mood
        parsed.mood_intensity = intensity
        parsed.content = "She smiled warmly."
        return parsed

    @patch("engine.agents.interceptors.MoodSyncInterceptor._evaluate_threshold_rules")
    def test_threshold_eval_called_when_scene_present(self, mock_eval):
        """When scene is in ctx, threshold evaluation should fire."""
        interceptor = self._make_interceptor()
        ctx = {
            "agent_id": "lola",
            "reply": "She smiled warmly. [MOOD:happy]",
            "parsed": self._make_parsed(),
            "scene": "penthouse",
        }
        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg:
            mock_reg.return_value = MagicMock()
            interceptor.post_call(ctx)

        mock_eval.assert_called_once_with("penthouse", "lola", ctx)

    @patch("engine.agents.interceptors.MoodSyncInterceptor._evaluate_threshold_rules")
    def test_threshold_eval_skipped_when_no_scene(self, mock_eval):
        """When scene is empty, threshold evaluation should not fire."""
        interceptor = self._make_interceptor()
        ctx = {
            "agent_id": "lola",
            "reply": "She smiled. [MOOD:happy]",
            "parsed": self._make_parsed(),
            "scene": "",
        }
        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg:
            mock_reg.return_value = MagicMock()
            interceptor.post_call(ctx)

        mock_eval.assert_not_called()

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.scene_rules_engine.get_rules_engine")
    def test_threshold_rules_fire_effects(self, mock_eng_fn, mock_ssm_fn):
        """When stats cross thresholds, rules should auto-fire via apply_rule."""
        interceptor = self._make_interceptor()

        # Mock SSM to return stats with high arousal
        mock_ssm = MagicMock()
        mock_ssm.get_stats.return_value = {"arousal": 70, "happiness": 50}
        mock_ssm_fn.return_value = mock_ssm

        # Mock rules engine: one triggered rule
        mock_eng = MagicMock()
        mock_eng.evaluate_threshold_rules.return_value = [
            {"rule_id": "intimate_unlock", "label": "Unlock intimate actions"}
        ]
        mock_eng.apply_rule.return_value = {"ok": True}
        mock_eng_fn.return_value = mock_eng

        ctx = {"agent_id": "lola", "scene": "penthouse"}
        interceptor._evaluate_threshold_rules("penthouse", "lola", ctx)

        mock_eng.evaluate_threshold_rules.assert_called_once_with(
            "penthouse", "lola", {"arousal": 70, "happiness": 50}
        )
        mock_eng.apply_rule.assert_called_once_with(
            "penthouse", "intimate_unlock",
            target_ids=["lola"],
            issuer="threshold_auto",
            ctx={"agent_id": "lola", "scene": "penthouse"},
        )

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.scene_rules_engine.get_rules_engine")
    def test_threshold_no_rules_no_apply(self, mock_eng_fn, mock_ssm_fn):
        """When no thresholds crossed, apply_rule should not be called."""
        interceptor = self._make_interceptor()

        mock_ssm = MagicMock()
        mock_ssm.get_stats.return_value = {"arousal": 10}
        mock_ssm_fn.return_value = mock_ssm

        mock_eng = MagicMock()
        mock_eng.evaluate_threshold_rules.return_value = []
        mock_eng_fn.return_value = mock_eng

        interceptor._evaluate_threshold_rules("penthouse", "lola", {})
        mock_eng.apply_rule.assert_not_called()

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.scene_rules_engine.get_rules_engine")
    def test_threshold_eval_graceful_on_error(self, mock_eng_fn, mock_ssm_fn):
        """If rules engine raises, interceptor should not propagate."""
        interceptor = self._make_interceptor()

        mock_ssm_fn.side_effect = RuntimeError("SSM unavailable")

        # Should not raise
        interceptor._evaluate_threshold_rules("penthouse", "lola", {})

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.scene_rules_engine.get_rules_engine")
    def test_threshold_merges_registry_stats(self, mock_eng_fn, mock_ssm_fn):
        """Stats from CharacterRegistry should merge into threshold check."""
        interceptor = self._make_interceptor()

        mock_ssm = MagicMock()
        mock_ssm.get_stats.return_value = {"arousal": 50}
        mock_ssm_fn.return_value = mock_ssm

        mock_eng = MagicMock()
        mock_eng.evaluate_threshold_rules.return_value = []
        mock_eng_fn.return_value = mock_eng

        # Mock registry with energy/inhibition
        mock_state = MagicMock()
        mock_state.mood_intensity = 0.9
        mock_state.energy = 80
        mock_state.inhibition = 20
        mock_rec = MagicMock()
        mock_rec.state = mock_state

        with patch("engine.mcp.character_registry.get_character_registry") as mock_reg_fn:
            mock_reg = MagicMock()
            mock_reg.get_character.return_value = mock_rec
            mock_reg_fn.return_value = mock_reg

            interceptor._evaluate_threshold_rules("penthouse", "lola", {})

        # Check that stats dict included merged values
        call_args = mock_eng.evaluate_threshold_rules.call_args
        stats = call_args[0][2]  # third positional arg
        assert stats["arousal"] == 50       # from SSM
        assert stats["mood_intensity"] == 0.9  # from registry
        assert stats["energy"] == 80
        assert stats["inhibition"] == 20

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.scene_rules_engine.get_rules_engine")
    def test_multiple_rules_all_fire(self, mock_eng_fn, mock_ssm_fn):
        """When multiple thresholds cross, all matching rules should fire."""
        interceptor = self._make_interceptor()

        mock_ssm = MagicMock()
        mock_ssm.get_stats.return_value = {"arousal": 90, "happiness": 80}
        mock_ssm_fn.return_value = mock_ssm

        mock_eng = MagicMock()
        mock_eng.evaluate_threshold_rules.return_value = [
            {"rule_id": "rule_a", "label": "First rule"},
            {"rule_id": "rule_b", "label": "Second rule"},
        ]
        mock_eng.apply_rule.return_value = {"ok": True}
        mock_eng_fn.return_value = mock_eng

        interceptor._evaluate_threshold_rules("penthouse", "lola", {})
        assert mock_eng.apply_rule.call_count == 2
