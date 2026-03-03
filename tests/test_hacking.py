"""Tests for the CosySim hacking engine and hacking skills.

Covers:
- HackEngine target registration (builtin + custom)
- Puzzle generation (size, timer, modifiers)
- Correct solution accepted
- Wrong solution rejected with heat penalty
- Timed-out solution rejected
- Already-solved / already-failed guard
- Cyberdeck stat helpers in InventoryManager
- Hacking @skill tools (via the public API)
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from engine.services.hack_engine import (
    HackEngine,
    HackTarget,
    _BASE_TIMER,
    _GRID_SIZE,
    _SEQ_LEN,
    _TRACE_RESIST_BONUS,
    get_hack_engine,
    reset_hack_engine,
)


# ──── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_engine():
    """Ensure a clean HackEngine singleton for every test."""
    reset_hack_engine()
    yield
    reset_hack_engine()


@pytest.fixture()
def engine() -> HackEngine:
    return get_hack_engine()


# ──── Target Registration ──────────────────────────────────────────────────────


class TestTargetRegistration:
    def test_builtin_targets_registered(self, engine):
        targets = engine.list_targets()
        assert len(targets) >= 15

    def test_register_custom_target(self, engine):
        t = engine.register_target(
            "test_terminal",
            security_level=2,
            label="Test Terminal",
            location="THE LAB",
            rewards=["credits:100"],
        )
        assert t.target_id == "test_terminal"
        assert t.security_level == 2
        assert t.label == "Test Terminal"
        assert t.rewards == ["credits:100"]

    def test_security_level_clamped(self, engine):
        t = engine.register_target("low", security_level=0)
        assert t.security_level == 1
        t2 = engine.register_target("high", security_level=99)
        assert t2.security_level == 5

    def test_update_existing_target(self, engine):
        engine.register_target("x", security_level=1, label="Old")
        engine.register_target("x", security_level=3, label="New")
        t = engine.get_target("x")
        assert t.security_level == 3
        assert t.label == "New"

    def test_list_targets_filtered_by_location(self, engine):
        engine.register_target("loc_a", location="ZONE_A")
        engine.register_target("loc_b", location="ZONE_B")
        results = engine.list_targets(location="ZONE_A")
        ids = [r["target_id"] for r in results]
        assert "loc_a" in ids
        assert "loc_b" not in ids

    def test_get_target_returns_none_for_unknown(self, engine):
        assert engine.get_target("nonexistent") is None

    def test_target_locked_flag(self, engine):
        engine.register_target("locked_dev", security_level=1)
        t = engine.get_target("locked_dev")
        t.locked_until = time.time() + 3600
        result = engine.list_targets()
        dev = next(r for r in result if r["target_id"] == "locked_dev")
        assert dev["locked"] is True


# ──── Puzzle Generation ────────────────────────────────────────────────────────


class TestPuzzleGeneration:
    def test_puzzle_has_required_fields(self, engine):
        engine.register_target("p_target", security_level=1)
        p = engine.generate_puzzle("p_target")
        assert "error" not in p
        for key in ("puzzle_id", "grid", "grid_size", "sequence_length", "time_limit"):
            assert key in p

    def test_grid_size_matches_security_level(self, engine):
        for level in (1, 2, 3, 4, 5):
            engine.register_target(f"target_lv{level}", security_level=level)
            p = engine.generate_puzzle(f"target_lv{level}")
            assert "error" not in p
            assert p["grid_size"] == _GRID_SIZE[level]
            assert len(p["grid"]) == _GRID_SIZE[level]
            for row in p["grid"]:
                assert len(row) == _GRID_SIZE[level]

    def test_time_limit_matches_base(self, engine):
        engine.register_target("timer_test", security_level=1)
        p = engine.generate_puzzle("timer_test", hacking_skill=1)
        assert p["time_limit"] == pytest.approx(_BASE_TIMER[1], abs=2.0)

    def test_trace_resist_extends_timer(self, engine):
        engine.register_target("resist_test", security_level=1)
        p_base = engine.generate_puzzle("resist_test", trace_resist=0)
        p_boosted = engine.generate_puzzle("resist_test", trace_resist=5)
        assert p_boosted["time_limit"] > p_base["time_limit"]
        expected_bonus = 5 * _TRACE_RESIST_BONUS
        assert p_boosted["time_limit"] - p_base["time_limit"] == pytest.approx(expected_bonus, abs=0.5)

    def test_crack_speed_reduces_sequence_length(self, engine):
        engine.register_target("crack_test", security_level=3)
        p_base = engine.generate_puzzle("crack_test", crack_speed=0)
        p_cracked = engine.generate_puzzle("crack_test", crack_speed=6)
        assert p_cracked["sequence_length"] < p_base["sequence_length"]

    def test_sequence_length_min_is_two(self, engine):
        engine.register_target("min_seq", security_level=1)
        p = engine.generate_puzzle("min_seq", crack_speed=100)
        assert p["sequence_length"] >= 2

    def test_sequence_codes_length_matches(self, engine):
        engine.register_target("codes_test", security_level=2)
        p = engine.generate_puzzle("codes_test")
        assert "sequence_codes" in p
        assert len(p["sequence_codes"]) == p["sequence_length"]

    def test_puzzle_error_on_unknown_target(self, engine):
        p = engine.generate_puzzle("does_not_exist")
        assert "error" in p

    def test_puzzle_error_when_locked(self, engine):
        engine.register_target("locked_target", security_level=1)
        t = engine.get_target("locked_target")
        t.locked_until = time.time() + 3600
        p = engine.generate_puzzle("locked_target")
        assert "error" in p

    def test_different_seeds_produce_different_puzzles(self, engine):
        engine.register_target("seed_test", security_level=2)
        p1 = engine.generate_puzzle("seed_test")
        p2 = engine.generate_puzzle("seed_test")
        assert p1["puzzle_id"] != p2["puzzle_id"]


# ──── Attempt Evaluation ───────────────────────────────────────────────────────


class TestAttemptEvaluation:
    def _get_puzzle_and_solution(self, engine, target_id="eval_target", level=1):
        engine.register_target(target_id, security_level=level, rewards=["credits:200"])
        puzzle = engine.generate_puzzle(target_id)
        assert "error" not in puzzle
        # Retrieve the actual solution from the stored puzzle object
        stored = engine._puzzles[puzzle["puzzle_id"]]
        solution = list(map(list, stored.solution))
        return puzzle, solution

    def test_correct_solution_succeeds(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, solution = self._get_puzzle_and_solution(engine)
            result = engine.evaluate_attempt(puzzle["puzzle_id"], solution, elapsed_seconds=1.0)
        assert result.success is True
        assert result.message == "ACCESS GRANTED"

    def test_correct_solution_grants_rewards(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            ps_mock = MagicMock()
            mock_ps.return_value = ps_mock
            puzzle, solution = self._get_puzzle_and_solution(engine)
            result = engine.evaluate_attempt(puzzle["puzzle_id"], solution, elapsed_seconds=1.0)
        assert result.success
        assert "credits:200" in result.rewards_granted

    def test_wrong_solution_fails(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, _ = self._get_puzzle_and_solution(engine)
            # Submit wrong cells
            wrong = [[0, 0], [0, 0]]
            result = engine.evaluate_attempt(puzzle["puzzle_id"], wrong, elapsed_seconds=1.0)
        assert result.success is False

    def test_wrong_solution_raises_heat(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            ps_mock = MagicMock()
            mock_ps.return_value = ps_mock
            puzzle, _ = self._get_puzzle_and_solution(engine)
            result = engine.evaluate_attempt(puzzle["puzzle_id"], [[0, 0]], elapsed_seconds=1.0)
        assert result.heat_delta > 0

    def test_timeout_fails_puzzle(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, solution = self._get_puzzle_and_solution(engine)
            result = engine.evaluate_attempt(
                puzzle["puzzle_id"], solution, elapsed_seconds=puzzle["time_limit"] + 1.0
            )
        assert result.success is False

    def test_double_submit_returns_completed(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, solution = self._get_puzzle_and_solution(engine)
            engine.evaluate_attempt(puzzle["puzzle_id"], solution, elapsed_seconds=1.0)
            # Second attempt
            result2 = engine.evaluate_attempt(puzzle["puzzle_id"], solution, elapsed_seconds=1.0)
        assert result2.message == "Puzzle already completed."

    def test_unknown_puzzle_id_returns_error(self, engine):
        result = engine.evaluate_attempt("nonexistent_id", [[0, 0]], 0.0)
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_failed_hack_locks_target(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, _ = self._get_puzzle_and_solution(engine, "lock_after_fail", level=2)
            engine.evaluate_attempt(puzzle["puzzle_id"], [[0, 0]], elapsed_seconds=1.0)
        t = engine.get_target("lock_after_fail")
        assert t.is_locked() is True

    def test_success_increments_hack_count(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            puzzle, solution = self._get_puzzle_and_solution(engine, "count_target")
        engine.evaluate_attempt(puzzle["puzzle_id"], solution, elapsed_seconds=1.0)
        t = engine.get_target("count_target")
        assert t.hack_count == 1

    def test_heat_delta_scales_with_level(self, engine):
        with patch("engine.services.hack_engine.get_player_state") as mock_ps:
            mock_ps.return_value = MagicMock()
            engine.register_target("heat_lv1", security_level=1)
            engine.register_target("heat_lv5", security_level=5)
            p1 = engine.generate_puzzle("heat_lv1")
            p5 = engine.generate_puzzle("heat_lv5")
        r1 = engine.evaluate_attempt(p1["puzzle_id"], [[0, 0]], 1.0)
        r5 = engine.evaluate_attempt(p5["puzzle_id"], [[0, 0]], 1.0)
        assert r5.heat_delta > r1.heat_delta


# ──── Lock Reset ───────────────────────────────────────────────────────────────


class TestLockReset:
    def test_reset_lock_removes_cooldown(self, engine):
        engine.register_target("reset_me", security_level=1)
        t = engine.get_target("reset_me")
        t.locked_until = time.time() + 3600
        assert t.is_locked()
        ok = engine.reset_target_lock("reset_me")
        assert ok is True
        assert t.is_locked() is False

    def test_reset_unknown_target_returns_false(self, engine):
        assert engine.reset_target_lock("ghost_target") is False


# ──── Cyberdeck Stat Helpers ───────────────────────────────────────────────────


class TestCyberdeckStats:
    def test_no_deck_returns_zeros(self, tmp_path):
        from engine.world.inventory import InventoryManager
        orig = InventoryManager._SAVE_PATH
        InventoryManager._SAVE_PATH = tmp_path / "inv_test_empty.json"
        try:
            mgr = InventoryManager()
            stats = mgr.get_cyberdeck_stats()
            assert stats == {"crack_speed": 0, "trace_resist": 0}
        finally:
            InventoryManager._SAVE_PATH = orig

    def test_equipped_deck_returns_stats(self, tmp_path):
        from engine.world.inventory import InventoryManager
        orig = InventoryManager._SAVE_PATH
        InventoryManager._SAVE_PATH = tmp_path / "inv_test_netrunner.json"
        try:
            mgr = InventoryManager()
            mgr.add_item("netrunner_mk1")
            mgr.equip("netrunner_mk1", "cyberdeck")
            stats = mgr.get_cyberdeck_stats()
            assert stats["crack_speed"] == 1
            assert stats["trace_resist"] == 1
        finally:
            InventoryManager._SAVE_PATH = orig

    def test_legendary_deck_has_high_stats(self, tmp_path):
        from engine.world.inventory import InventoryManager
        orig = InventoryManager._SAVE_PATH
        InventoryManager._SAVE_PATH = tmp_path / "inv_test_specter.json"
        try:
            mgr = InventoryManager()
            mgr.add_item("specter_3000")
            mgr.equip("specter_3000", "cyberdeck")
            stats = mgr.get_cyberdeck_stats()
            assert stats["crack_speed"] >= 5
            assert stats["trace_resist"] >= 5
        finally:
            InventoryManager._SAVE_PATH = orig


# ──── HackTarget dataclass ─────────────────────────────────────────────────────


class TestHackTarget:
    def test_is_locked_false_initially(self):
        t = HackTarget(target_id="x", security_level=1)
        assert t.is_locked() is False

    def test_is_locked_true_when_in_future(self):
        t = HackTarget(target_id="x", security_level=1, locked_until=time.time() + 60)
        assert t.is_locked() is True

    def test_to_dict_includes_required_keys(self):
        t = HackTarget(target_id="x", security_level=2, label="Test", location="THE LAB")
        d = t.to_dict()
        for k in ("target_id", "security_level", "label", "location", "rewards", "locked", "hack_count"):
            assert k in d


# ──── Hacking Skills ──────────────────────────────────────────────────────────


class TestHackingSkills:
    """Test the @skill wrapper functions (via direct import)."""

    def _import_skills(self):
        import importlib
        import sys
        for key in list(sys.modules.keys()):
            if "hacking_skills" in key:
                del sys.modules[key]
        return importlib.import_module("engine.skills.builtin.hacking_skills")

    def test_list_hack_targets_returns_string(self):
        mod = self._import_skills()
        result = mod.list_hack_targets.__wrapped__() if hasattr(mod.list_hack_targets, "__wrapped__") else mod.list_hack_targets()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_list_hack_targets_filtered_empty(self):
        mod = self._import_skills()
        fn = getattr(mod.list_hack_targets, "__wrapped__", mod.list_hack_targets)
        result = fn(location="NONEXISTENT_LOCATION_XYZ")
        assert "No hackable targets" in result

    def test_get_hacking_profile_returns_string(self):
        mod = self._import_skills()
        with (
            patch("engine.skills.builtin.hacking_skills._player") as mock_ps,
            patch("engine.skills.builtin.hacking_skills._deck_stats") as mock_deck,
        ):
            mock_ps.return_value = MagicMock(skills={"hacking": 2})
            mock_deck.return_value = {"crack_speed": 1, "trace_resist": 2}
            fn = getattr(mod.get_hacking_profile, "__wrapped__", mod.get_hacking_profile)
            result = fn()
        assert "HACKING PROFILE" in result
        assert "Lv2" in result

    def test_can_hack_target_locked_message(self):
        mod = self._import_skills()
        with patch("engine.skills.builtin.hacking_skills._engine") as mock_eng:
            t = MagicMock()
            t.is_locked.return_value = True
            t.locked_until = time.time() + 120
            mock_eng.return_value = MagicMock(get_target=MagicMock(return_value=t))
            fn = getattr(mod.can_hack_target, "__wrapped__", mod.can_hack_target)
            result = fn("some_target")
        assert "LOCKED" in result

    def test_can_hack_target_not_found(self):
        mod = self._import_skills()
        with patch("engine.skills.builtin.hacking_skills._engine") as mock_eng:
            mock_eng.return_value = MagicMock(get_target=MagicMock(return_value=None))
            fn = getattr(mod.can_hack_target, "__wrapped__", mod.can_hack_target)
            result = fn("ghost")
        assert "NOT FOUND" in result

    def test_register_hack_target_skill(self):
        mod = self._import_skills()
        fn = getattr(mod.register_hack_target, "__wrapped__", mod.register_hack_target)
        result = fn("custom_device", security_level=2, label="Test Device", location="TEST", rewards="credits:100")
        assert "REGISTERED" in result
        assert "Test Device" in result

    def test_reset_hack_target_lock_skill(self):
        mod = self._import_skills()
        # Register and lock a target first
        eng = get_hack_engine()
        eng.register_target("unlock_me", security_level=1)
        t = eng.get_target("unlock_me")
        t.locked_until = time.time() + 3600
        fn = getattr(mod.reset_hack_target_lock, "__wrapped__", mod.reset_hack_target_lock)
        result = fn("unlock_me")
        assert "RESET" in result

    def test_initiate_hack_returns_puzzle_info(self):
        mod = self._import_skills()
        with (
            patch("engine.skills.builtin.hacking_skills._deck_stats", return_value={"crack_speed": 0, "trace_resist": 0}),
            patch("engine.skills.builtin.hacking_skills._hacking_skill_level", return_value=1),
        ):
            fn = getattr(mod.initiate_hack, "__wrapped__", mod.initiate_hack)
            result = fn("signal_comms_tower")
        assert "HACK INITIATED" in result or "HACK FAILED" in result

    def test_submit_hack_solution_invalid_cells(self):
        mod = self._import_skills()
        fn = getattr(mod.submit_hack_solution, "__wrapped__", mod.submit_hack_solution)
        result = fn("fake_id", "not-json", 0.0)
        assert "ERROR" in result or "Invalid" in result

    def test_submit_hack_solution_unknown_puzzle(self):
        mod = self._import_skills()
        fn = getattr(mod.submit_hack_solution, "__wrapped__", mod.submit_hack_solution)
        result = fn("bad_puzzle_id", "[[0,0],[0,1]]", 0.0)
        # Should return a failure string from the engine
        assert isinstance(result, str)
        assert "❌" in result or "not found" in result.lower()
