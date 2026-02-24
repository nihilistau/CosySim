"""
Tests for CharacterStateCoordinator — the unified state write-through API.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, call
import pytest


# ── Helpers ───────────────────────────────────────────────────────────

def _fresh_coordinator():
    """Create a fresh coordinator (bypass singleton for test isolation)."""
    from engine.mcp.state_coordinator import CharacterStateCoordinator
    return CharacterStateCoordinator()


def _mock_registry():
    """Create a mock CharacterRegistry with basic behavior."""
    reg = MagicMock()
    reg.get_state.return_value = {
        "mood": "neutral", "mood_intensity": 0.5,
        "focus": "", "current_role": "default",
        "energy": 80.0, "inhibition": 30.0,
        "restrictions": [], "flags": {},
    }
    return reg


def _mock_ssm():
    """Create a mock SceneStateManager with basic behavior."""
    ssm = MagicMock()
    stats = MagicMock()
    stats.to_dict.return_value = {
        "arousal": 20.0, "horniness": 15.0, "pleasure": 10.0,
        "happiness": 60.0, "anger": 5.0, "fear": 5.0,
        "drunkenness": 0.0, "tiredness": 20.0, "explicitness": 60.0,
        "openness": 65.0, "affection": 50.0, "dominance": 50.0,
    }
    ssm.get_stats.return_value = stats
    return ssm


# ══════════════════════════════════════════════════════════════════════
#  Field Routing Tests
# ══════════════════════════════════════════════════════════════════════

class TestFieldRouting:
    """Verify that fields are routed to the correct store."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_registry_fields_routed_to_registry(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = _mock_ssm()

        coord.update("lola", mood="flirty", energy=-10)
        mock_reg.set_state.assert_called_once_with(
            "lola", mood="flirty", energy=-10
        )

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_stats_fields_routed_to_ssm_delta(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_ssm = _mock_ssm()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = mock_ssm

        coord.update("lola", arousal=15, happiness=-5)
        mock_ssm.update_stats.assert_called_once_with("lola", arousal=15, happiness=-5)

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_stats_fields_routed_to_ssm_set(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_ssm = _mock_ssm()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = mock_ssm

        coord.update("lola", arousal=50, mode="set")
        mock_ssm.set_stats.assert_called_once_with("lola", arousal=50)

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_mixed_fields_split_correctly(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_ssm = _mock_ssm()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = mock_ssm

        coord.update("lola", mood="excited", arousal=20, happiness=10)

        mock_reg.set_state.assert_called_once_with("lola", mood="excited")
        mock_ssm.update_stats.assert_called_once_with("lola", arousal=20, happiness=10)

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_unknown_fields_go_to_flags(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = _mock_ssm()

        coord.update("lola", custom_field="value123")
        mock_reg.set_state.assert_called_once_with(
            "lola", flags={"custom_field": "value123"}
        )


# ══════════════════════════════════════════════════════════════════════
#  Restriction Tests
# ══════════════════════════════════════════════════════════════════════

class TestRestrictions:
    """Verify restriction add/remove operations."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_add_restriction(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = _mock_ssm()

        coord.update("lola", add_restriction="refuse_explicit")
        mock_reg.add_restriction.assert_called_once_with("lola", "refuse_explicit")

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_remove_restriction(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = _mock_ssm()

        coord.update("lola", remove_restriction="refuse_explicit")
        mock_reg.remove_restriction.assert_called_once_with("lola", "refuse_explicit")

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_add_multiple_restrictions(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg = _mock_registry()
        mock_reg_fn.return_value = mock_reg
        mock_ssm_fn.return_value = _mock_ssm()

        coord.update("lola", add_restriction=["no_violence", "no_drugs"])
        assert mock_reg.add_restriction.call_count == 2


# ══════════════════════════════════════════════════════════════════════
#  Event Emission Tests
# ══════════════════════════════════════════════════════════════════════

class TestEvents:
    """Verify state change events are emitted."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_listener_called_on_update(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        events = []
        coord.on_state_changed(lambda event, snap: events.append(event))

        coord.update("lola", mood="happy", scene="bedroom", source="test")

        assert len(events) == 1
        assert events[0]["character_id"] == "lola"
        assert events[0]["type"] == "state_changed"
        assert events[0]["scene"] == "bedroom"
        assert events[0]["source"] == "test"
        assert "mood" in events[0]["changes"]

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_listener_error_doesnt_propagate(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        def bad_listener(event, snap):
            raise RuntimeError("boom")

        coord.on_state_changed(bad_listener)
        # Should not raise
        coord.update("lola", mood="angry")


# ══════════════════════════════════════════════════════════════════════
#  Full State Snapshot Tests
# ══════════════════════════════════════════════════════════════════════

class TestFullState:
    """Verify unified state snapshots."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_full_state_merges_both_stores(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        state = coord.get_full_state("lola")

        # Registry fields
        assert state["mood"] == "neutral"
        assert state["energy"] == 80.0
        # SSM fields
        assert state["arousal"] == 20.0
        assert state["happiness"] == 60.0
        # Character ID
        assert state["character_id"] == "lola"

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_get_field_single_value(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        assert coord.get_field("lola", "mood") == "neutral"
        assert coord.get_field("lola", "arousal") == 20.0
        assert coord.get_field("lola", "nonexistent", "default") == "default"

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_empty_update_returns_snapshot(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        state = coord.update("lola")
        assert "mood" in state
        assert "arousal" in state


# ══════════════════════════════════════════════════════════════════════
#  Graceful Degradation Tests
# ══════════════════════════════════════════════════════════════════════

class TestGracefulDegradation:
    """Verify coordinator handles failures without crashing."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_registry_failure_doesnt_crash(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.side_effect = RuntimeError("Registry unavailable")
        mock_ssm_fn.return_value = _mock_ssm()

        # Should not raise
        result = coord.update("lola", mood="happy", arousal=10)
        assert isinstance(result, dict)

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_ssm_failure_doesnt_crash(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.side_effect = RuntimeError("SSM unavailable")

        # Should not raise
        result = coord.update("lola", arousal=10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════
#  Thread Safety Tests
# ══════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    """Verify concurrent updates don't corrupt state."""

    @patch("engine.mcp.scene_state.get_scene_state_manager")
    @patch("engine.mcp.character_registry.get_character_registry")
    def test_concurrent_different_characters(self, mock_reg_fn, mock_ssm_fn):
        coord = _fresh_coordinator()
        mock_reg_fn.return_value = _mock_registry()
        mock_ssm_fn.return_value = _mock_ssm()

        errors = []

        def worker(char_id, i):
            try:
                coord.update(char_id, mood=f"mood_{i}", arousal=i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"char_{i % 3}", i))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors

    def test_per_character_locks_are_independent(self):
        coord = _fresh_coordinator()
        lock_a = coord._get_char_lock("alice")
        lock_b = coord._get_char_lock("bob")
        assert lock_a is not lock_b
        # Same character returns same lock
        assert coord._get_char_lock("alice") is lock_a


# ══════════════════════════════════════════════════════════════════════
#  Singleton Tests
# ══════════════════════════════════════════════════════════════════════

class TestSingleton:
    """Verify singleton behavior."""

    def test_get_coordinator_returns_same_instance(self):
        from engine.mcp.state_coordinator import get_coordinator
        a = get_coordinator()
        b = get_coordinator()
        assert a is b

    def test_get_coordinator_returns_correct_type(self):
        from engine.mcp.state_coordinator import get_coordinator, CharacterStateCoordinator
        assert isinstance(get_coordinator(), CharacterStateCoordinator)


# ══════════════════════════════════════════════════════════════════════
#  Field Classification Tests
# ══════════════════════════════════════════════════════════════════════

class TestFieldClassification:
    """Verify field routing constants are complete."""

    def test_registry_fields_complete(self):
        from engine.mcp.state_coordinator import REGISTRY_FIELDS
        expected = {"mood", "mood_intensity", "focus", "current_role", "energy", "inhibition"}
        assert REGISTRY_FIELDS == expected

    def test_stats_fields_complete(self):
        from engine.mcp.state_coordinator import STATS_FIELDS
        assert "arousal" in STATS_FIELDS
        assert "happiness" in STATS_FIELDS
        assert "dominance" in STATS_FIELDS
        assert "relationship" in STATS_FIELDS
        assert "attraction" in STATS_FIELDS
        assert "trust" in STATS_FIELDS
        assert len(STATS_FIELDS) == 15

    def test_no_overlap_between_registry_and_stats(self):
        from engine.mcp.state_coordinator import REGISTRY_FIELDS, STATS_FIELDS
        assert not REGISTRY_FIELDS.intersection(STATS_FIELDS)


class TestRelationshipBuffSystem:
    """Tests for the buff/debuff system on CharacterStateCoordinator."""

    def _fresh_coord(self):
        from engine.mcp.state_coordinator import CharacterStateCoordinator
        return CharacterStateCoordinator()

    def test_add_buff(self):
        coord = self._fresh_coord()
        coord.add_buff("lola", "flirt_bonus", {"affection": 10}, duration_secs=60)
        buffs = coord.get_active_buffs("lola")
        assert "flirt_bonus" in buffs
        assert buffs["flirt_bonus"]["deltas"]["affection"] == 10
        assert buffs["flirt_bonus"]["remaining_secs"] > 0

    def test_expired_buff_removed(self):
        coord = self._fresh_coord()
        coord.add_buff("lola", "temp_debuff", {"happiness": -5}, duration_secs=0.01)
        time.sleep(0.02)
        removed = coord.remove_expired_buffs("lola")
        assert "temp_debuff" in removed
        buffs = coord.get_active_buffs("lola")
        assert "temp_debuff" not in buffs

    def test_no_buffs_returns_empty(self):
        coord = self._fresh_coord()
        buffs = coord.get_active_buffs("unknown_char")
        assert buffs == {}

    def test_multiple_buffs(self):
        coord = self._fresh_coord()
        coord.add_buff("lola", "buff_a", {"arousal": 5}, duration_secs=60)
        coord.add_buff("lola", "buff_b", {"happiness": 10}, duration_secs=60)
        buffs = coord.get_active_buffs("lola")
        assert len(buffs) == 2


class TestAttractionModel:
    """Tests for the attraction calculation."""

    def test_baseline_attraction(self):
        from engine.mcp.state_coordinator import CharacterStateCoordinator
        coord = CharacterStateCoordinator()
        score = coord.calculate_attraction("char_a", "char_b")
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_attraction_in_valid_range(self):
        from engine.mcp.state_coordinator import CharacterStateCoordinator
        coord = CharacterStateCoordinator()
        for _ in range(10):
            score = coord.calculate_attraction("x", "y")
            assert 0 <= score <= 100
