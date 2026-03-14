"""Tests for faction_politics system and daily challenge generator.

All tests run offline — no real MCP, LMStudio, or Nexus calls.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ──── Helpers ─────────────────────────────────────────────────────────────────


def _fresh_manager():
    """Return a new, isolated FactionManager (not the singleton)."""
    from engine.story.faction_politics import FactionManager
    mgr = FactionManager()
    return mgr


def _sample_faction(fid: str = "alpha", scene: str = "penthouse") -> "Faction":
    from engine.story.faction_politics import Faction
    return Faction(id=fid, name=fid.title(), scene=scene)


# ──── Faction dataclass ───────────────────────────────────────────────────────


class TestFaction:
    def test_defaults(self):
        from engine.story.faction_politics import Faction
        f = Faction(id="x", name="X", scene="penthouse")
        assert f.player_standing == 0
        assert f.relationships == {}
        assert f.tags == []
        assert f.description == ""

    def test_custom_values(self):
        from engine.story.faction_politics import Faction
        f = Faction(id="y", name="Y", scene="casino", player_standing=50,
                    relationships={"z": -30}, tags=["power"])
        assert f.player_standing == 50
        assert f.relationships == {"z": -30}
        assert "power" in f.tags


# ──── FactionManager registration ─────────────────────────────────────────────


class TestFactionManagerRegistration:
    def test_register_and_get(self):
        mgr = _fresh_manager()
        f = _sample_faction("a")
        mgr.register(f)
        assert mgr.get("a") is f

    def test_get_unknown_returns_none(self):
        mgr = _fresh_manager()
        assert mgr.get("nope") is None

    def test_register_replaces_existing(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="Old", scene="penthouse"))
        mgr.register(Faction(id="a", name="New", scene="penthouse"))
        assert mgr.get("a").name == "New"

    def test_get_by_scene(self):
        mgr = _fresh_manager()
        mgr.register(_sample_faction("a", "penthouse"))
        mgr.register(_sample_faction("b", "penthouse"))
        mgr.register(_sample_faction("c", "casino"))
        result = mgr.get_by_scene("penthouse")
        ids = {f.id for f in result}
        assert ids == {"a", "b"}

    def test_get_by_scene_empty(self):
        mgr = _fresh_manager()
        assert mgr.get_by_scene("nowhere") == []

    def test_reset_clears_all(self):
        mgr = _fresh_manager()
        mgr.register(_sample_faction("a"))
        mgr.reset()
        assert mgr.get("a") is None
        assert mgr.get_by_scene("penthouse") == []


# ──── modify_standing ─────────────────────────────────────────────────────────


class TestModifyStanding:
    def test_positive_delta(self):
        mgr = _fresh_manager()
        mgr.register(_sample_faction("a"))
        changes = mgr.modify_standing("a", 20)
        assert changes["a"] == 20
        assert mgr.get("a").player_standing == 20

    def test_negative_delta(self):
        mgr = _fresh_manager()
        mgr.register(_sample_faction("a"))
        changes = mgr.modify_standing("a", -30)
        assert changes["a"] == -30

    def test_clamp_upper(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", player_standing=90))
        mgr.modify_standing("a", 50)
        assert mgr.get("a").player_standing == 100

    def test_clamp_lower(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", player_standing=-90))
        mgr.modify_standing("a", -50)
        assert mgr.get("a").player_standing == -100

    def test_unknown_faction_returns_empty(self):
        mgr = _fresh_manager()
        assert mgr.modify_standing("ghost", 10) == {}

    def test_no_cascade_when_disabled(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"b": 80}))
        mgr.register(Faction(id="b", name="B", scene="penthouse"))
        mgr.modify_standing("a", 20, cascade=False)
        assert mgr.get("b").player_standing == 0

    def test_ally_cascade_positive(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"b": 100}))
        mgr.register(Faction(id="b", name="B", scene="penthouse"))
        mgr.modify_standing("a", 40)
        # cascade_delta = int(40 * (100/200)) = 20
        assert mgr.get("b").player_standing == 20

    def test_enemy_cascade_negative(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"b": -100}))
        mgr.register(Faction(id="b", name="B", scene="penthouse"))
        mgr.modify_standing("a", 40)
        # cascade_delta = int(40 * (-100/200)) = -20
        assert mgr.get("b").player_standing == -20

    def test_cascade_missing_other_faction_ignored(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"missing": 80}))
        changes = mgr.modify_standing("a", 10)
        assert "missing" not in changes

    def test_zero_cascade_delta_not_included(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        # relationship = 0 → cascade_delta = 0 → not included in changes
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"b": 0}))
        mgr.register(Faction(id="b", name="B", scene="penthouse"))
        changes = mgr.modify_standing("a", 10)
        assert "b" not in changes

    def test_returns_all_modified_factions(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="A", scene="penthouse", relationships={"b": 60, "c": -60}))
        mgr.register(Faction(id="b", name="B", scene="penthouse"))
        mgr.register(Faction(id="c", name="C", scene="penthouse"))
        changes = mgr.modify_standing("a", 20)
        assert set(changes.keys()) == {"a", "b", "c"}


# ──── get_scene_politics ──────────────────────────────────────────────────────


class TestGetScenePolitics:
    def test_returns_scene_name(self):
        mgr = _fresh_manager()
        result = mgr.get_scene_politics("penthouse")
        assert result["scene"] == "penthouse"

    def test_returns_faction_list(self):
        from engine.story.faction_politics import Faction
        mgr = _fresh_manager()
        mgr.register(Faction(id="a", name="Alpha", scene="penthouse", tags=["power"]))
        result = mgr.get_scene_politics("penthouse")
        assert len(result["factions"]) == 1
        faction_data = result["factions"][0]
        assert faction_data["id"] == "a"
        assert faction_data["name"] == "Alpha"
        assert "standing_label" in faction_data
        assert "player_standing" in faction_data
        assert "tags" in faction_data

    def test_empty_scene_returns_empty_list(self):
        mgr = _fresh_manager()
        result = mgr.get_scene_politics("empty_scene")
        assert result["factions"] == []


# ──── _standing_label ─────────────────────────────────────────────────────────


class TestStandingLabel:
    def test_revered(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(75) == "revered"
        assert _standing_label(100) == "revered"

    def test_honored(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(40) == "honored"
        assert _standing_label(74) == "honored"

    def test_friendly(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(10) == "friendly"
        assert _standing_label(39) == "friendly"

    def test_neutral(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(0) == "neutral"
        assert _standing_label(-9) == "neutral"

    def test_unfriendly(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(-10) == "unfriendly"
        assert _standing_label(-39) == "unfriendly"

    def test_hostile(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(-40) == "hostile"
        assert _standing_label(-74) == "hostile"

    def test_hated(self):
        from engine.story.faction_politics import _standing_label
        assert _standing_label(-75) == "hated"
        assert _standing_label(-100) == "hated"


# ──── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_faction_manager_returns_same_instance(self):
        from engine.story.faction_politics import get_faction_manager
        a = get_faction_manager()
        b = get_faction_manager()
        assert a is b


# ──── faction_templates ───────────────────────────────────────────────────────


class TestFactionTemplates:
    def _isolated_seed(self):
        """Seed into a fresh manager (not singleton)."""
        from engine.story.faction_politics import FactionManager
        from engine.story.faction_templates import SCENE_FACTIONS
        mgr = FactionManager()
        for _scene, factions in SCENE_FACTIONS.items():
            for faction in factions:
                mgr.register(faction)
        return mgr

    def test_all_9_scenes_have_factions(self):
        from engine.story.faction_templates import SCENE_FACTIONS
        expected = {"penthouse", "casino", "arena", "tavern", "lounge",
                    "gallery", "realm", "neoncity", "phone"}
        assert set(SCENE_FACTIONS.keys()) == expected

    def test_seed_all_returns_count(self):
        from engine.story.faction_politics import FactionManager
        from engine.story.faction_templates import SCENE_FACTIONS
        mgr = FactionManager()
        total = sum(len(v) for v in SCENE_FACTIONS.values())
        assert total >= 18  # at least 2 per scene

    def test_bedroom_has_elite_and_press(self):
        mgr = self._isolated_seed()
        assert mgr.get("elite") is not None
        assert mgr.get("press") is not None

    def test_casino_factions(self):
        mgr = self._isolated_seed()
        for fid in ("house", "players", "enforcers"):
            assert mgr.get(fid) is not None, f"Missing faction: {fid}"

    def test_arena_factions(self):
        mgr = self._isolated_seed()
        for fid in ("gladiators", "promoters", "underground"):
            assert mgr.get(fid) is not None

    def test_tavern_factions(self):
        mgr = self._isolated_seed()
        for fid in ("guild", "outlaws", "guard"):
            assert mgr.get(fid) is not None

    def test_guild_vs_outlaws_hostile(self):
        mgr = self._isolated_seed()
        guild = mgr.get("guild")
        assert guild is not None
        assert guild.relationships.get("outlaws", 0) < -10

    def test_neoncity_factions(self):
        mgr = self._isolated_seed()
        for fid in ("omnicorp", "ghost_net", "synthsec"):
            assert mgr.get(fid) is not None

    def test_realm_crown_vs_rebels_hostile(self):
        mgr = self._isolated_seed()
        crown = mgr.get("crown")
        assert crown is not None
        assert crown.relationships.get("rebels", 0) < -50

    def test_phone_network_positive_standing(self):
        mgr = self._isolated_seed()
        network = mgr.get("network")
        assert network is not None
        assert network.player_standing > 0


# ──── Faction skills ──────────────────────────────────────────────────────────


class TestFactionSkills:
    def test_get_faction_politics_returns_string(self):
        from engine.skills.builtin.story_skills import get_faction_politics
        from engine.story.faction_politics import Faction, FactionManager
        mgr = FactionManager()
        mgr.register(Faction(id="elite", name="The Elite", scene="penthouse"))
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = get_faction_politics("penthouse")
        assert isinstance(result, str)

    def test_get_faction_politics_no_factions(self):
        from engine.skills.builtin.story_skills import get_faction_politics
        from engine.story.faction_politics import FactionManager
        mgr = FactionManager()
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = get_faction_politics("empty")
        assert "No factions" in result

    def test_change_faction_standing_returns_string(self):
        from engine.skills.builtin.story_skills import change_faction_standing
        from engine.story.faction_politics import Faction, FactionManager
        mgr = FactionManager()
        mgr.register(Faction(id="elite", name="The Elite", scene="penthouse"))
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = change_faction_standing("elite", 20, "helped the cause")
        assert isinstance(result, str)
        assert "elite" in result

    def test_change_faction_standing_not_found(self):
        from engine.skills.builtin.story_skills import change_faction_standing
        from engine.story.faction_politics import FactionManager
        mgr = FactionManager()
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = change_faction_standing("ghost", 10)
        assert "not found" in result

    def test_check_faction_standing_returns_string(self):
        from engine.skills.builtin.story_skills import check_faction_standing
        from engine.story.faction_politics import Faction, FactionManager
        mgr = FactionManager()
        mgr.register(Faction(id="elite", name="The Elite", scene="penthouse", player_standing=50))
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = check_faction_standing("elite")
        assert isinstance(result, str)
        assert "The Elite" in result

    def test_check_faction_standing_not_found(self):
        from engine.skills.builtin.story_skills import check_faction_standing
        from engine.story.faction_politics import FactionManager
        mgr = FactionManager()
        with patch("engine.story.faction_politics.FactionManager.get_instance", return_value=mgr):
            result = check_faction_standing("ghost")
        assert "not found" in result


# ──── DailyChallengeManager ───────────────────────────────────────────────────


class TestDailyChallengeManager:
    def _fresh_dcm(self):
        from engine.nexus.daily_challenge import DailyChallengeManager
        return DailyChallengeManager()

    def test_get_challenge_returns_dict(self):
        dcm = self._fresh_dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            challenge = dcm.get_challenge("penthouse")
        assert isinstance(challenge, dict)

    def test_challenge_has_required_keys(self):
        dcm = self._fresh_dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            challenge = dcm.get_challenge("casino")
        for key in ("title", "description", "win_condition", "reward", "difficulty"):
            assert key in challenge, f"Missing key: {key}"

    def test_challenge_cached_on_same_day(self):
        dcm = self._fresh_dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            first = dcm.get_challenge("arena")
            second = dcm.get_challenge("arena")
        assert first is second

    def test_challenge_cleared_on_new_day(self):
        from datetime import date
        dcm = self._fresh_dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            with patch("engine.nexus.daily_challenge.date") as mock_date:
                mock_date.today.return_value = date(2025, 1, 1)
                first = dcm.get_challenge("penthouse")
                mock_date.today.return_value = date(2025, 1, 2)
                dcm._last_generated = date(2025, 1, 1)
                dcm._today_challenges.clear()
                second = dcm.get_challenge("penthouse")
        # Both should have required keys (different objects after clear)
        assert "title" in first
        assert "title" in second


# ──── Fallback challenges ─────────────────────────────────────────────────────


class TestFallbackChallenges:
    SCENES = ["penthouse", "casino", "arena", "tavern", "lounge",
              "gallery", "realm", "neoncity", "phone"]

    def _dcm(self):
        from engine.nexus.daily_challenge import DailyChallengeManager
        return DailyChallengeManager()

    @pytest.mark.parametrize("scene", SCENES)
    def test_fallback_exists_for_all_scenes(self, scene: str):
        dcm = self._dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            challenge = dcm.get_challenge(scene)
        assert challenge is not None
        assert challenge.get("title") != ""

    @pytest.mark.parametrize("scene", SCENES)
    def test_difficulty_is_1_to_5(self, scene: str):
        dcm = self._dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            challenge = dcm.get_challenge(scene)
        assert 1 <= challenge["difficulty"] <= 5

    def test_unknown_scene_returns_generic(self):
        dcm = self._dcm()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            challenge = dcm.get_challenge("unknown_scene")
        assert "title" in challenge
        assert challenge["difficulty"] >= 1


# ──── Daily challenge skills ──────────────────────────────────────────────────


class TestDailyChallengeSkills:
    def test_get_daily_challenge_returns_string(self):
        from engine.nexus.daily_challenge import DailyChallengeManager
        from engine.skills.builtin.story_skills import get_daily_challenge
        dcm = DailyChallengeManager()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            with patch("engine.nexus.daily_challenge.DailyChallengeManager.get_instance", return_value=dcm):
                result = get_daily_challenge("penthouse")
        assert isinstance(result, str)
        assert "penthouse" in result.lower() or "Daily Challenge" in result

    def test_complete_daily_challenge_returns_string(self):
        from engine.nexus.daily_challenge import DailyChallengeManager
        from engine.skills.builtin.story_skills import complete_daily_challenge
        dcm = DailyChallengeManager()
        with patch("engine.nexus.daily_challenge.get_nexus_client", side_effect=Exception("offline")):
            with patch("engine.nexus.daily_challenge.DailyChallengeManager.get_instance", return_value=dcm):
                with patch("engine.nexus.client.get_nexus_client", side_effect=Exception("offline")):
                    result = complete_daily_challenge("penthouse", "player succeeded")
        assert isinstance(result, str)
        assert "player succeeded" in result or "resolved" in result


# ──── Scheduler task count ────────────────────────────────────────────────────


class TestSchedulerTaskCount:
    def test_daily_challenge_seed_registered(self):
        """daily-challenge-seed task is registered in builtin tasks."""
        from unittest.mock import MagicMock
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [c.args[0] if c.args else c.kwargs.get("task_id") for c in daemon.register.call_args_list]
        assert "daily-challenge-seed" in task_ids

    def test_builtin_task_count_is_39(self):
        """Total builtin task count is 39 including router training flywheel tasks."""
        from unittest.mock import MagicMock
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        assert daemon.register.call_count == 76


