"""Tests for crew skill-checks & graded operation outcomes.

Covers the v1.60.0 "Living Systems" upgrade to ``engine.world.crew``:
the probabilistic skill-check model, SUCCESS / PARTIAL / FAILURE outcome
grading, scaled rewards + failure penalty, and per-outcome loyalty shifts.

These tests are HERMETIC: each constructs a fresh ``CrewManager`` on a temp
save path, resets the singleton, stubs randomness, and mocks ``get_player_state``
so they never touch global ``data/*.json`` state or other singletons.

Version: v1.60.0 [2026-06-13]
Author:  CosySim Team

Change Log:
    v1.60.0 [2026-06-13] — Initial skill-check / graded-outcome test suite.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

from engine.world import crew as crew_module
from engine.world.crew import (
    OUTCOME_FAILURE,
    OUTCOME_PARTIAL,
    OUTCOME_SUCCESS,
    CrewManager,
    CrewOperation,
)


# ──── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def manager(tmp_path):
    """Fresh, isolated CrewManager with no persistence side effects."""
    CrewManager._SAVE_PATH = tmp_path / "crew.json"
    CrewManager._instance = None
    mgr = CrewManager()
    # Neutralize persistence so tests never write/read shared files.
    mgr._save = lambda: None  # type: ignore[method-assign]
    yield mgr
    CrewManager._instance = None


def _recruit(mgr: CrewManager, cid: str, role: str, level: int, loyalty: float) -> None:
    """Insert a fully-specified crew member directly (bypasses relationship gates)."""
    ok, _ = mgr.recruit(cid, role=role, skip_check=True)
    assert ok, f"failed to recruit {cid}"
    m = mgr.get_member(cid)
    assert m is not None
    m.level = level
    m.loyalty = loyalty


def _make_op(mgr: CrewManager, op_type: str, crew, *, credits: int, xp: int) -> CrewOperation:
    """Create a completed-status operation object ready for resolution."""
    op = CrewOperation(
        op_id="testop01",
        op_type=op_type,
        label="Test Op",
        assigned_crew=list(crew),
        started_at=0.0,
        duration_secs=0.0,
        status="complete",
        reward_credits=credits,
        reward_xp=xp,
    )
    return op


# ──── compute_success_chance ──────────────────────────────────────────────────


class TestComputeSuccessChance:
    def test_better_crew_raises_chance(self, manager):
        # Two hackers vs a 'hack' op (skill_weight hacker:3).
        _recruit(manager, "weak", "hacker", level=1, loyalty=50)
        _recruit(manager, "strong", "hacker", level=5, loyalty=90)
        low, _ = manager.compute_success_chance("hack", ["weak"])
        high, _ = manager.compute_success_chance("hack", ["strong"])
        assert high > low

    def test_role_fit_beats_off_role(self, manager):
        # Same level/loyalty; on-role specialist should out-score off-role member.
        _recruit(manager, "netrunner", "hacker", level=3, loyalty=60)
        _recruit(manager, "thug", "muscle", level=3, loyalty=60)
        fit, _ = manager.compute_success_chance("hack", ["netrunner"])
        offrole, _ = manager.compute_success_chance("hack", ["thug"])
        assert fit > offrole

    def test_loyalty_raises_chance(self, manager):
        _recruit(manager, "loyal", "fixer", level=2, loyalty=100)
        _recruit(manager, "fickle", "fixer", level=2, loyalty=0)
        hi, _ = manager.compute_success_chance("deal", ["loyal"])
        lo, _ = manager.compute_success_chance("deal", ["fickle"])
        assert hi > lo

    def test_harder_op_lowers_chance(self, manager):
        # Same crew, easy recon vs brutal heist.
        _recruit(manager, "a", "hacker", level=3, loyalty=70)
        easy, _ = manager.compute_success_chance("recon", ["a"])
        hard, _ = manager.compute_success_chance("heist", ["a"])
        assert easy > hard

    def test_chance_is_clamped(self, manager):
        # Stack the deck: many maxed specialists → still capped at max_chance.
        for i in range(6):
            _recruit(manager, f"ace{i}", "hacker", level=5, loyalty=100)
        chance, _ = manager.compute_success_chance("recon", [f"ace{i}" for i in range(6)])
        assert chance <= crew_module._skill_cfg("max_chance") + 1e-9
        # Empty / unknown crew → never below min_chance.
        floor, _ = manager.compute_success_chance("heist", [])
        assert floor >= crew_module._skill_cfg("min_chance") - 1e-9

    def test_breakdown_keys_present(self, manager):
        _recruit(manager, "a", "hacker", level=2, loyalty=50)
        _, breakdown = manager.compute_success_chance("hack", ["a"])
        for key in ("base", "effective_skill", "loyalty_term", "difficulty_term", "chance"):
            assert key in breakdown


# ──── Graded outcomes ─────────────────────────────────────────────────────────


class TestGradedOutcomes:
    def test_success_full_reward_and_loyalty_gain(self, manager):
        _recruit(manager, "a", "hacker", level=3, loyalty=50)
        op = _make_op(manager, "hack", ["a"], credits=1000, xp=40)
        ps = MagicMock()
        # roll=0.0 always <= chance → guaranteed SUCCESS
        with patch.object(random, "random", return_value=0.0), \
             patch("engine.world.player_state.get_player_state", return_value=ps):
            result = manager._resolve_operation(op)
        assert result["outcome"] == OUTCOME_SUCCESS
        assert result["credits_earned"] == 1000
        assert result["xp_earned"] == 40
        ps.earn_credits.assert_called_once()
        # Loyalty went up.
        assert manager.get_member("a").loyalty == pytest.approx(
            50 + crew_module._skill_cfg("loyalty_on_success")
        )

    def test_failure_zero_reward_penalty_and_loyalty_drop(self, manager):
        _recruit(manager, "a", "hacker", level=1, loyalty=50)
        op = _make_op(manager, "heist", ["a"], credits=1000, xp=40)
        ps = MagicMock()
        # roll=1.0 always > chance + partial_band → guaranteed FAILURE
        with patch.object(random, "random", return_value=1.0), \
             patch("engine.world.player_state.get_player_state", return_value=ps):
            result = manager._resolve_operation(op)
        assert result["outcome"] == OUTCOME_FAILURE
        assert result["credits_earned"] == 0
        assert result["xp_earned"] == 0
        assert op.status == "failed"
        # Penalty charged via spend_credits.
        expected_penalty = int(round(1000 * crew_module._skill_cfg("failure_credit_penalty_mult")))
        if expected_penalty > 0:
            ps.spend_credits.assert_called_once()
        ps.earn_credits.assert_not_called()
        # Loyalty dropped.
        assert manager.get_member("a").loyalty == pytest.approx(
            50 + crew_module._skill_cfg("loyalty_on_failure")
        )

    def test_partial_scaled_reward(self, manager):
        _recruit(manager, "a", "hacker", level=3, loyalty=50)
        op = _make_op(manager, "hack", ["a"], credits=1000, xp=40)
        chance, _ = manager.compute_success_chance("hack", ["a"])
        # Force a roll that misses success but lands inside the partial band.
        band = crew_module._skill_cfg("partial_band")
        partial_roll = min(chance + band / 2.0, 0.999)
        # Ensure the construction actually yields a partial for this chance.
        assert partial_roll > chance
        ps = MagicMock()
        with patch.object(random, "random", return_value=partial_roll), \
             patch("engine.world.player_state.get_player_state", return_value=ps):
            result = manager._resolve_operation(op)
        assert result["outcome"] == OUTCOME_PARTIAL
        expected = int(round(1000 * crew_module._skill_cfg("partial_reward_mult")))
        assert result["credits_earned"] == expected

    def test_member_made_available_and_op_count_incremented(self, manager):
        _recruit(manager, "a", "hacker", level=2, loyalty=50)
        manager.get_member("a").available = False
        op = _make_op(manager, "hack", ["a"], credits=100, xp=10)
        with patch.object(random, "random", return_value=0.0), \
             patch("engine.world.player_state.get_player_state", return_value=MagicMock()):
            manager._resolve_operation(op)
        m = manager.get_member("a")
        assert m.available is True
        assert m.operations == 1


# ──── Config override / determinism ───────────────────────────────────────────


class TestConfigOverride:
    def test_base_chance_override_respected(self, manager):
        _recruit(manager, "a", "hacker", level=1, loyalty=0)

        def fake_cfg(path, default):
            if path == "crew.skill_check.base_chance":
                return 0.99
            return default

        with patch.object(crew_module, "_cfg", side_effect=fake_cfg):
            chance, _ = manager.compute_success_chance("recon", ["a"])
        # With a 0.99 base and an easy op, chance should be high (near max clamp).
        assert chance >= 0.90

    def test_not_always_success_distribution(self, manager):
        """Regression for the audit finding: operations must NOT always succeed."""
        _recruit(manager, "a", "muscle", level=1, loyalty=20)  # weak, off-role, hard op
        outcomes = {OUTCOME_SUCCESS: 0, OUTCOME_PARTIAL: 0, OUTCOME_FAILURE: 0}
        rng = random.Random(1234)
        ps = MagicMock()
        for _ in range(200):
            op = _make_op(manager, "heist", ["a"], credits=500, xp=20)
            with patch.object(random, "random", side_effect=rng.random), \
                 patch("engine.world.player_state.get_player_state", return_value=ps):
                res = manager._resolve_operation(op)
            outcomes[res["outcome"]] += 1
            # reset member state between runs for stable inputs
            manager.get_member("a").loyalty = 20
        # A weak crew on a brutal op should fail at least some of the time.
        assert outcomes[OUTCOME_FAILURE] > 0, outcomes
        # And the total clearly is not all-success.
        assert outcomes[OUTCOME_SUCCESS] < 200, outcomes


# ──── Integration via check_operations ────────────────────────────────────────


class TestCheckOperationsIntegration:
    def test_check_operations_resolves_due_op(self, manager):
        _recruit(manager, "a", "hacker", level=3, loyalty=80)
        ok, _ = manager.start_operation(
            "hack", ["a"], label="Live Op", duration_secs=0.0,
            reward_credits=300, reward_xp=30,
        )
        assert ok
        with patch.object(random, "random", return_value=0.0), \
             patch("engine.world.player_state.get_player_state", return_value=MagicMock()):
            completed = manager.check_operations()
        assert len(completed) == 1
        assert completed[0]["outcome"] in (OUTCOME_SUCCESS, OUTCOME_PARTIAL, OUTCOME_FAILURE)
        # Crew freed up after resolution.
        assert manager.get_member("a").available is True

    def test_start_operation_records_odds(self, manager):
        _recruit(manager, "a", "hacker", level=3, loyalty=80)
        manager.start_operation("hack", ["a"], duration_secs=999, reward_credits=10)
        active = manager.get_active_operations()
        assert active
        assert 0.0 < active[0].success_chance <= crew_module._skill_cfg("max_chance")
