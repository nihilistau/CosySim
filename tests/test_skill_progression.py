"""Tests for engine.world.skill_progression module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.world.skill_progression import (
    DIFFICULTY_TIERS,
    DIFFICULTY_XP_MULTIPLIER,
    DIMINISHING_RETURNS,
    GLOBAL_LEVEL_XP,
    LEVEL_THRESHOLDS,
    MAX_GLOBAL_LEVEL,
    MAX_SKILL_LEVEL,
    SKILL_DESCRIPTIONS,
    SKILL_ICONS,
    SKILL_NAMES,
    SKILL_UNLOCKS,
    SkillCheckResult,
    SkillManager,
    SkillState,
)


# ──── Fixtures ────

@pytest.fixture
def manager(tmp_path):
    """Create an isolated SkillManager with temp persistence."""
    with patch("engine.world.skill_progression._SAVE_DIR", tmp_path):
        mgr = SkillManager()
        yield mgr


# ──── SkillState Tests ────

class TestSkillState:

    def test_initial_level_zero(self):
        """New skill starts at level 0."""
        state = SkillState(name="hacking")
        assert state.level == 0
        assert state.xp == 0

    def test_compute_level_from_xp(self):
        """Levels compute correctly from XP thresholds."""
        state = SkillState(name="hacking")
        state.xp = 0
        assert state.compute_level() == 0

        state.xp = 100
        assert state.compute_level() == 1

        state.xp = 300
        assert state.compute_level() == 2

        state.xp = 2000
        assert state.compute_level() == 5

    def test_level_capped_at_max(self):
        """Level cannot exceed MAX_SKILL_LEVEL."""
        state = SkillState(name="hacking")
        state.xp = 999999
        assert state.compute_level() == MAX_SKILL_LEVEL

    def test_xp_to_next_level(self):
        """XP needed for next level is computed correctly."""
        state = SkillState(name="hacking")
        state.xp = 0
        state.compute_level()
        assert state.xp_to_next_level() == 100

        state.xp = 50
        state.compute_level()
        assert state.xp_to_next_level() == 50

    def test_xp_to_next_level_at_max(self):
        """At max level, xp_to_next_level returns None."""
        state = SkillState(name="hacking")
        state.xp = 2000
        state.compute_level()
        assert state.xp_to_next_level() is None

    def test_progress_to_next(self):
        """Progress percentage is correct."""
        state = SkillState(name="hacking")
        state.xp = 50
        state.compute_level()
        progress = state.progress_to_next()
        assert 0.0 < progress < 1.0
        assert abs(progress - 0.5) < 0.01

    def test_progress_at_max_is_1(self):
        """At max level, progress is 1.0."""
        state = SkillState(name="hacking")
        state.xp = 2000
        state.compute_level()
        assert state.progress_to_next() == 1.0

    def test_serialization_roundtrip(self):
        """SkillState survives to_dict/from_dict."""
        state = SkillState(name="combat")
        state.xp = 450
        state.uses = 25
        state.compute_level()

        data = state.to_dict()
        restored = SkillState.from_dict(data)
        assert restored.name == "combat"
        assert restored.xp == 450
        assert restored.level == 2
        assert restored.uses == 25


# ──── SkillCheckResult Tests ────

class TestSkillCheckResult:

    def test_narrative_success(self):
        """Success narrative includes skill name and margin."""
        result = SkillCheckResult(
            skill="hacking", level=3, roll=15, effective=12,
            total=27, difficulty=16, difficulty_name="hard",
            success=True, critical=False, margin=11, xp_awarded=7,
        )
        narr = result.narrative()
        assert "SUCCESS" in narr
        assert "hacking" in narr.lower()

    def test_narrative_failure(self):
        """Failure narrative includes shortfall."""
        result = SkillCheckResult(
            skill="stealth", level=1, roll=5, effective=4,
            total=9, difficulty=16, difficulty_name="hard",
            success=False, critical=False, margin=-7, xp_awarded=2,
        )
        narr = result.narrative()
        assert "FAILED" in narr

    def test_narrative_critical_success(self):
        """Nat 20 produces critical success narrative."""
        result = SkillCheckResult(
            skill="combat", level=2, roll=20, effective=8,
            total=28, difficulty=12, difficulty_name="medium",
            success=True, critical=True, margin=16, xp_awarded=5,
        )
        narr = result.narrative()
        assert "CRITICAL SUCCESS" in narr

    def test_narrative_critical_failure(self):
        """Nat 1 produces critical failure narrative."""
        result = SkillCheckResult(
            skill="social", level=4, roll=1, effective=16,
            total=17, difficulty=12, difficulty_name="medium",
            success=False, critical=True, margin=5, xp_awarded=2,
        )
        narr = result.narrative()
        assert "CRITICAL FAILURE" in narr

    def test_serialization_roundtrip(self):
        """SkillCheckResult survives to_dict roundtrip."""
        result = SkillCheckResult(
            skill="tech", level=2, roll=12, effective=8,
            total=20, difficulty=16, difficulty_name="hard",
            success=True, critical=False, margin=4, xp_awarded=7,
        )
        data = result.to_dict()
        assert data["skill"] == "tech"
        assert data["roll"] == 12


# ──── SkillManager Tests ────

class TestSkillManager:

    def test_all_skills_initialized(self, manager):
        """All 8 skills exist on init."""
        skills = manager.get_all_skills()
        assert len(skills) == 8
        for name in SKILL_NAMES:
            assert name in skills

    def test_award_xp_basic(self, manager):
        """Award XP increases skill XP."""
        actual, leveled = manager.award_xp("hacking", 50, reason="test")
        assert actual > 0
        assert manager.get_xp("hacking") > 0

    def test_award_xp_diminishing_returns(self, manager):
        """Higher levels get less XP from same base amount."""
        # Level 0 → full XP
        actual_0, _ = manager.award_xp("combat", 100, reason="test")

        # Manually set to level 3 (600 XP)
        manager._skills["trading"].xp = 600
        manager._skills["trading"].compute_level()
        actual_3, _ = manager.award_xp("trading", 100, reason="test")

        assert actual_3 < actual_0

    def test_award_xp_difficulty_multiplier(self, manager):
        """Higher difficulty awards more XP."""
        actual_easy, _ = manager.award_xp("stealth", 100, difficulty="easy")
        actual_hard, _ = manager.award_xp("stealth", 100, difficulty="hard")
        assert actual_hard > actual_easy

    def test_award_xp_level_up(self, manager):
        """Award enough XP to trigger level up."""
        _, leveled = manager.award_xp("hacking", 200, reason="massive hack")
        assert leveled
        assert manager.get_level("hacking") >= 1

    def test_award_xp_invalid_skill(self, manager):
        """Invalid skill name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown skill"):
            manager.award_xp("telekinesis", 100)

    def test_skill_check_basic(self, manager):
        """Skill check returns valid SkillCheckResult."""
        result = manager.skill_check("hacking", difficulty=12)
        assert isinstance(result, SkillCheckResult)
        assert result.skill == "hacking"
        assert 1 <= result.roll <= 20
        assert result.total == result.roll + result.effective

    def test_skill_check_nat_20_always_succeeds(self, manager):
        """Natural 20 is always a success."""
        with patch("engine.world.skill_progression.random.randint", return_value=20):
            result = manager.skill_check("hacking", difficulty=100)
            assert result.success
            assert result.critical

    def test_skill_check_nat_1_always_fails(self, manager):
        """Natural 1 is always a failure."""
        with patch("engine.world.skill_progression.random.randint", return_value=1):
            result = manager.skill_check("hacking", difficulty=1)
            assert not result.success
            assert result.critical

    def test_skill_check_advantage(self, manager):
        """Advantage takes the higher of two rolls."""
        with patch("engine.world.skill_progression.random.randint", side_effect=[5, 15]):
            result = manager.skill_check("combat", difficulty=12, advantage=True)
            assert result.roll == 15

    def test_skill_check_disadvantage(self, manager):
        """Disadvantage takes the lower of two rolls."""
        with patch("engine.world.skill_progression.random.randint", side_effect=[15, 5]):
            result = manager.skill_check("combat", difficulty=12, disadvantage=True)
            assert result.roll == 5

    def test_skill_check_auto_xp(self, manager):
        """Skill checks award XP by default."""
        result = manager.skill_check("tech", difficulty=12)
        assert result.xp_awarded > 0
        assert manager.get_xp("tech") > 0

    def test_skill_check_no_auto_xp(self, manager):
        """auto_xp=False suppresses XP."""
        result = manager.skill_check("tech", difficulty=12, auto_xp=False)
        assert result.xp_awarded == 0

    def test_skill_check_history(self, manager):
        """Skill checks are recorded in history."""
        manager.skill_check("hacking", difficulty=12)
        history = manager.get_check_history()
        assert len(history) > 0

    def test_global_level_from_total_xp(self, manager):
        """Global level increases with total XP."""
        assert manager.get_global_level() == 1
        manager.award_xp("hacking", 200, difficulty="legendary")
        assert manager.get_global_level() >= 1
        assert manager.get_total_xp() > 0

    def test_can_use_ability(self, manager):
        """Ability unlock gating works."""
        assert manager.can_use_ability("hacking", "basic_scan")
        assert not manager.can_use_ability("hacking", "zero_day_exploit")

    def test_unlocked_abilities(self, manager):
        """Level 0 unlocks only level-0 abilities."""
        unlocked = manager.get_unlocked_abilities("hacking")
        assert "basic_scan" in unlocked
        assert "zero_day_exploit" not in unlocked

    def test_locked_abilities(self, manager):
        """Locked abilities list shows requirements."""
        locked = manager.get_locked_abilities("hacking")
        names = [n for n, _ in locked]
        assert "zero_day_exploit" in names

    def test_get_skill_summary_string(self, manager):
        """Skill summary is a formatted string."""
        summary = manager.get_skill_summary()
        assert "PLAYER SKILLS" in summary
        assert "hacking" in summary

    def test_persistence_roundtrip(self, tmp_path):
        """State persists and reloads across manager instances."""
        with patch("engine.world.skill_progression._SAVE_DIR", tmp_path):
            mgr1 = SkillManager()
            mgr1.award_xp("hacking", 150, reason="test")
            xp_before = mgr1.get_xp("hacking")

            mgr2 = SkillManager()
            assert mgr2.get_xp("hacking") == xp_before


# ──── Constants Validation ────

class TestConstants:

    def test_level_thresholds_ascending(self):
        """Level thresholds must be strictly ascending."""
        for i in range(1, len(LEVEL_THRESHOLDS)):
            assert LEVEL_THRESHOLDS[i] > LEVEL_THRESHOLDS[i - 1]

    def test_global_level_xp_ascending(self):
        """Global level XP must be strictly ascending."""
        for i in range(1, len(GLOBAL_LEVEL_XP)):
            assert GLOBAL_LEVEL_XP[i] > GLOBAL_LEVEL_XP[i - 1]

    def test_all_skills_have_descriptions(self):
        """Every skill has a description."""
        for name in SKILL_NAMES:
            assert name in SKILL_DESCRIPTIONS

    def test_all_skills_have_icons(self):
        """Every skill has an icon."""
        for name in SKILL_NAMES:
            assert name in SKILL_ICONS

    def test_all_skills_have_unlocks(self):
        """Every skill has an unlock tree."""
        for name in SKILL_NAMES:
            assert name in SKILL_UNLOCKS
            assert len(SKILL_UNLOCKS[name]) >= 4

    def test_difficulty_tiers_ascending(self):
        """Difficulty tiers increase in DC."""
        values = list(DIFFICULTY_TIERS.values())
        assert values == sorted(values)

    def test_diminishing_returns_decreasing(self):
        """Higher levels have lower XP multipliers."""
        for i in range(1, MAX_SKILL_LEVEL + 1):
            assert DIMINISHING_RETURNS[i] < DIMINISHING_RETURNS[i - 1]
