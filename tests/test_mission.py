"""Tests for engine/world/mission.py — MissionManager."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_manager(tmp_path):
    from engine.world.mission import MissionManager, reset_mission_manager
    MissionManager._SAVE_PATH = tmp_path / "missions_test.json"
    reset_mission_manager()
    yield
    reset_mission_manager()


@pytest.fixture()
def mgr():
    from engine.world.mission import get_mission_manager
    return get_mission_manager()


@pytest.fixture()
def mock_player_state():
    ps = MagicMock()
    ps.skills = {"hacking": 1}
    ps.active_location = "NEON CITY"
    with patch("engine.world.mission.get_player_state", return_value=ps):
        yield ps


# ---------------------------------------------------------------------------
# TestMissionSeeding
# ---------------------------------------------------------------------------

class TestMissionSeeding:
    def test_builtin_missions_seeded(self, mgr):
        available = mgr.list_available()
        assert len(available) == 15

    def test_all_types_present(self, mgr):
        types = {m["type"] for m in mgr.list_available()}
        assert "recon" in types
        assert "heist" in types
        assert "deal" in types
        assert "extraction" in types
        assert "hit" in types

    def test_mission_has_required_keys(self, mgr):
        m = mgr.list_available()[0]
        for key in ("id", "title", "description", "type", "giver", "location",
                    "difficulty", "reward", "objectives", "status"):
            assert key in m, f"Missing key: {key}"

    def test_all_missions_available_initially(self, mgr):
        available = mgr.list_available()
        assert all(m["status"] == "available" for m in available)


# ---------------------------------------------------------------------------
# TestMissionFiltering
# ---------------------------------------------------------------------------

class TestMissionFiltering:
    def test_filter_by_location(self, mgr):
        missions = mgr.list_available(location="SIGNAL")
        assert all(m["location"].upper() == "SIGNAL" for m in missions)
        assert len(missions) >= 1

    def test_filter_by_type(self, mgr):
        missions = mgr.list_available(mission_type="recon")
        assert all(m["type"] == "recon" for m in missions)

    def test_filter_by_max_difficulty(self, mgr):
        missions = mgr.list_available(max_difficulty=2)
        assert all(m["difficulty"] <= 2 for m in missions)

    def test_combined_filter(self, mgr):
        missions = mgr.list_available(mission_type="heist", max_difficulty=4)
        assert all(m["type"] == "heist" and m["difficulty"] <= 4 for m in missions)

    def test_sorted_by_difficulty(self, mgr):
        missions = mgr.list_available()
        diffs = [m["difficulty"] for m in missions]
        assert diffs == sorted(diffs)


# ---------------------------------------------------------------------------
# TestMissionAccept
# ---------------------------------------------------------------------------

class TestMissionAccept:
    def test_accept_available_mission(self, mgr):
        result = mgr.accept("recon_corp_signal")
        assert result["success"] is True
        active = mgr.list_active()
        ids = [m["id"] for m in active]
        assert "recon_corp_signal" in ids

    def test_accept_unknown_mission_fails(self, mgr):
        result = mgr.accept("nonexistent_mission")
        assert result["success"] is False

    def test_accept_already_active_fails(self, mgr):
        mgr.accept("recon_corp_signal")
        result = mgr.accept("recon_corp_signal")
        assert result["success"] is False

    def test_accepted_mission_has_started_at(self, mgr):
        mgr.accept("recon_corp_signal")
        status = mgr.get_status("recon_corp_signal")
        assert status is not None
        assert status["started_at"] is not None


# ---------------------------------------------------------------------------
# TestObjectiveCompletion
# ---------------------------------------------------------------------------

class TestObjectiveCompletion:
    def test_complete_objective(self, mgr):
        mgr.accept("recon_corp_signal")
        result = mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        assert result["success"] is True
        assert result["progress"]["done"] >= 1

    def test_complete_objective_not_active_fails(self, mgr):
        result = mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        assert result["success"] is False

    def test_complete_unknown_objective_fails(self, mgr):
        mgr.accept("recon_corp_signal")
        result = mgr.complete_objective("recon_corp_signal", "nonexistent_obj")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestMissionComplete
# ---------------------------------------------------------------------------

class TestMissionComplete:
    def test_complete_requires_all_objectives(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        # Only complete one of two required objectives
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        result = mgr.complete("recon_corp_signal")
        assert result["success"] is False
        assert "Incomplete" in result["message"]

    def test_complete_with_all_objectives_done(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        result = mgr.complete("recon_corp_signal")
        assert result["success"] is True
        assert "rewards" in result

    def test_complete_applies_credits(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        mgr.complete("recon_corp_signal")
        mock_player_state.earn_credits.assert_called()

    def test_complete_applies_reputation(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        mgr.complete("recon_corp_signal")
        mock_player_state.adjust_reputation.assert_called()

    def test_complete_not_active_fails(self, mgr, mock_player_state):
        result = mgr.complete("recon_corp_signal")
        assert result["success"] is False

    def test_completed_mission_not_in_available(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        mgr.complete("recon_corp_signal")
        available_ids = [m["id"] for m in mgr.list_available()]
        assert "recon_corp_signal" not in available_ids


# ---------------------------------------------------------------------------
# TestMissionAbandon
# ---------------------------------------------------------------------------

class TestMissionAbandon:
    def test_abandon_active_mission(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        result = mgr.abandon("recon_corp_signal")
        assert result["success"] is True

    def test_abandon_applies_rep_penalty(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        mgr.abandon("recon_corp_signal")
        mock_player_state.adjust_reputation.assert_called()

    def test_abandon_not_active_fails(self, mgr, mock_player_state):
        result = mgr.abandon("recon_corp_signal")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestMissionCrewAssignment
# ---------------------------------------------------------------------------

class TestMissionCrewAssignment:
    def test_assign_crew_to_active_mission(self, mgr):
        mgr.accept("recon_corp_signal")
        result = mgr.assign_crew("recon_corp_signal", ["viktor", "lola"])
        assert result["success"] is True
        assert "viktor" in result["assigned_crew"]
        assert "lola" in result["assigned_crew"]

    def test_assign_crew_no_duplicates(self, mgr):
        mgr.accept("recon_corp_signal")
        mgr.assign_crew("recon_corp_signal", ["viktor"])
        mgr.assign_crew("recon_corp_signal", ["viktor", "lola"])
        status = mgr.get_status("recon_corp_signal")
        assert status["assigned_crew"].count("viktor") == 1

    def test_assign_crew_not_active_fails(self, mgr):
        result = mgr.assign_crew("recon_corp_signal", ["viktor"])
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestCustomMissionCreation
# ---------------------------------------------------------------------------

class TestCustomMissionCreation:
    def test_create_custom_mission(self, mgr):
        result = mgr.create(
            title="Test Job",
            description="A test mission.",
            mission_type="recon",
            giver_npc="aria",
            location="SIGNAL",
            difficulty=2,
            reward_credits=500,
            reward_xp=25,
            objectives=["Do the thing", "Come back alive"],
        )
        assert result["success"] is True
        assert "mission_id" in result
        mid = result["mission_id"]
        assert mid.startswith("custom_")

    def test_created_mission_appears_on_board(self, mgr):
        result = mgr.create(
            title="Test Job",
            description="Test",
            mission_type="deal",
            giver_npc="lola",
            location="THE VELVET PIT",
        )
        mid = result["mission_id"]
        status = mgr.get_status(mid)
        assert status is not None
        assert status["status"] == "available"

    def test_create_with_invalid_type_fails(self, mgr):
        result = mgr.create(
            title="Bad Type",
            description="Test",
            mission_type="unknown_type",
            giver_npc="aria",
            location="SIGNAL",
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestMissionBoardSnapshot
# ---------------------------------------------------------------------------

class TestMissionBoardSnapshot:
    def test_to_dict_has_all_keys(self, mgr):
        d = mgr.to_dict()
        assert "available" in d
        assert "active" in d
        assert "completed" in d

    def test_board_counts_match(self, mgr, mock_player_state):
        mgr.accept("recon_corp_signal")
        d = mgr.to_dict()
        available_ids = [m["id"] for m in d["available"]]
        active_ids = [m["id"] for m in d["active"]]
        assert "recon_corp_signal" not in available_ids
        assert "recon_corp_signal" in active_ids


# ---------------------------------------------------------------------------
# TestMissionObjectiveOptional
# ---------------------------------------------------------------------------

class TestMissionObjectiveOptional:
    def test_optional_objective_not_required_for_completion(self, mgr, mock_player_state):
        """recon_corp_signal has scan_terminal_2 as optional — skip it and still complete."""
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        # NOT completing optional scan_terminal_2
        result = mgr.complete("recon_corp_signal")
        assert result["success"] is True

    def test_is_complete_true_when_optional_skipped(self, mgr):
        mgr.accept("recon_corp_signal")
        mgr.complete_objective("recon_corp_signal", "scan_terminal_1")
        mgr.complete_objective("recon_corp_signal", "extract_clean")
        m = mgr.get_mission("recon_corp_signal")
        assert m is not None
        assert m.is_complete is True
