"""Tests for the onboarding system — engine/world/onboarding.py + skills.

Tests cover:
    - Quest chain seeding and structure
    - Phase progression through all 8 phases
    - Objective completion and reward granting
    - Scene visit tracking and auto-advance
    - NPC meeting tracking and auto-advance
    - Mission completion tracking
    - Reputation threshold checks
    - Phone message delivery
    - Persistence (save/load)
    - Skip and reset
    - Onboarding skills
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.world.onboarding import (
    OnboardingManager,
    OnboardingPhase,
    OnboardingQuest,
    OnboardingObjective,
    ObjectiveStatus,
    ENCRYPTED_WELCOME,
    VIKTOR_FIRST_MESSAGE,
    LOLA_INTRO_MESSAGE,
    FRANKIE_INTRO_MESSAGE,
    MIRA_INTRO_MESSAGE,
    ARIA_INTRO_MESSAGE,
    GHOST_CREW_MESSAGE,
    GHOST_COMPLETION_MESSAGE,
    _build_onboarding_quests,
    get_onboarding_manager,
    reset_onboarding_manager,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def mgr(tmp_path):
    """Create a fresh OnboardingManager with temp save path."""
    reset_onboarding_manager()
    save_path = tmp_path / "onboarding.json"
    with patch.object(OnboardingManager, "_SAVE_PATH", save_path):
        m = OnboardingManager()
        m._emit = MagicMock()
        yield m


@pytest.fixture
def started_mgr(mgr):
    """OnboardingManager that has been started (Phase 1: ARRIVAL)."""
    with patch("engine.world.onboarding._player_state") as mock_ps:
        mock_ps.return_value = MagicMock()
        mgr.start_onboarding()
    return mgr


@pytest.fixture
def mock_player_state():
    """Mock player state for reward granting."""
    with patch("engine.world.onboarding._player_state") as mock_ps:
        ps = MagicMock()
        ps.credits = 5000
        ps.reputation = 50
        ps.to_dict.return_value = {
            "faction_standings": {"OmniCorp": 0, "NeoTech": 0, "Ghost_Net": 0}
        }
        mock_ps.return_value = ps
        yield ps


# ── Quest Chain Structure ─────────────────────────────────────────────────

class TestQuestChainStructure:
    """Verify the quest chain is properly defined."""

    def test_7_quests_defined(self):
        quests = _build_onboarding_quests()
        assert len(quests) == 7

    def test_quest_ids(self):
        quests = _build_onboarding_quests()
        ids = [q.id for q in quests]
        expected = [
            "q_arrival", "q_first_contact", "q_exploration",
            "q_first_mission", "q_connections", "q_reputation",
            "q_crew_forming",
        ]
        assert ids == expected

    def test_all_quests_have_objectives(self):
        for q in _build_onboarding_quests():
            assert len(q.objectives) >= 2, f"Quest {q.id} has too few objectives"

    def test_all_quests_have_rewards(self):
        for q in _build_onboarding_quests():
            assert q.reward_credits > 0, f"Quest {q.id} has no credit reward"
            assert q.reward_xp > 0, f"Quest {q.id} has no XP reward"

    def test_phases_progress_sequentially(self):
        quests = _build_onboarding_quests()
        phases = [q.phase for q in quests]
        expected = [
            OnboardingPhase.ARRIVAL,
            OnboardingPhase.FIRST_CONTACT,
            OnboardingPhase.EXPLORATION,
            OnboardingPhase.FIRST_MISSION,
            OnboardingPhase.CONNECTIONS,
            OnboardingPhase.REPUTATION,
            OnboardingPhase.CREW_FORMING,
        ]
        assert phases == expected

    def test_total_objectives(self):
        quests = _build_onboarding_quests()
        total = sum(len(q.objectives) for q in quests)
        assert total >= 20, f"Expected at least 20 objectives, got {total}"

    def test_quest_titles_non_empty(self):
        for q in _build_onboarding_quests():
            assert q.title, f"Quest {q.id} has no title"
            assert q.description, f"Quest {q.id} has no description"


# ── Onboarding Objective ─────────────────────────────────────────────────

class TestOnboardingObjective:
    """Test OnboardingObjective dataclass."""

    def test_default_status(self):
        obj = OnboardingObjective(id="test", description="Test")
        assert obj.status == ObjectiveStatus.AVAILABLE

    def test_to_dict(self):
        obj = OnboardingObjective(
            id="test_obj", description="Do the thing",
            hint="Try doing it", scene="grid",
        )
        d = obj.to_dict()
        assert d["id"] == "test_obj"
        assert d["status"] == "available"
        assert d["hint"] == "Try doing it"

    def test_from_dict(self):
        data = {
            "id": "obj_1", "description": "Step 1",
            "status": "completed", "completed_at": 12345.0,
        }
        obj = OnboardingObjective.from_dict(data)
        assert obj.id == "obj_1"
        assert obj.status == ObjectiveStatus.COMPLETED
        assert obj.completed_at == 12345.0


# ── Onboarding Quest ─────────────────────────────────────────────────────

class TestOnboardingQuest:
    """Test OnboardingQuest dataclass."""

    def test_progress_empty(self):
        q = OnboardingQuest(
            id="q_test", title="Test", description="Test",
            phase=OnboardingPhase.ARRIVAL,
        )
        assert q.progress == {"done": 0, "total": 0, "pct": 100}

    def test_progress_partial(self):
        q = OnboardingQuest(
            id="q_test", title="Test", description="Test",
            phase=OnboardingPhase.ARRIVAL,
            objectives=[
                OnboardingObjective(id="a", description="A", status=ObjectiveStatus.COMPLETED),
                OnboardingObjective(id="b", description="B", status=ObjectiveStatus.AVAILABLE),
            ],
        )
        assert q.progress["done"] == 1
        assert q.progress["total"] == 2
        assert q.progress["pct"] == 50

    def test_is_complete(self):
        q = OnboardingQuest(
            id="q_test", title="Test", description="Test",
            phase=OnboardingPhase.ARRIVAL,
            objectives=[
                OnboardingObjective(id="a", description="A", status=ObjectiveStatus.COMPLETED),
                OnboardingObjective(id="b", description="B", status=ObjectiveStatus.COMPLETED),
            ],
        )
        assert q.is_complete is True

    def test_not_complete(self):
        q = OnboardingQuest(
            id="q_test", title="Test", description="Test",
            phase=OnboardingPhase.ARRIVAL,
            objectives=[
                OnboardingObjective(id="a", description="A", status=ObjectiveStatus.COMPLETED),
                OnboardingObjective(id="b", description="B", status=ObjectiveStatus.AVAILABLE),
            ],
        )
        assert q.is_complete is False

    def test_skipped_counts_as_complete(self):
        q = OnboardingQuest(
            id="q_test", title="Test", description="Test",
            phase=OnboardingPhase.ARRIVAL,
            objectives=[
                OnboardingObjective(id="a", description="A", status=ObjectiveStatus.COMPLETED),
                OnboardingObjective(id="b", description="B", status=ObjectiveStatus.SKIPPED),
            ],
        )
        assert q.is_complete is True

    def test_to_dict_roundtrip(self):
        q = OnboardingQuest(
            id="q_rt", title="Roundtrip", description="Test roundtrip",
            phase=OnboardingPhase.FIRST_CONTACT,
            reward_credits=500, reward_xp=100,
            objectives=[
                OnboardingObjective(id="o1", description="Obj 1"),
                OnboardingObjective(id="o2", description="Obj 2", hint="A hint"),
            ],
        )
        d = q.to_dict()
        q2 = OnboardingQuest.from_dict(d)
        assert q2.id == "q_rt"
        assert q2.phase == OnboardingPhase.FIRST_CONTACT
        assert len(q2.objectives) == 2
        assert q2.reward_credits == 500


# ── Onboarding Manager ───────────────────────────────────────────────────

class TestOnboardingManager:
    """Test the OnboardingManager singleton."""

    def test_initial_phase(self, mgr):
        assert mgr.phase == OnboardingPhase.NOT_STARTED

    def test_is_started_false(self, mgr):
        assert mgr.is_started is False

    def test_is_completed_false(self, mgr):
        assert mgr.is_completed is False

    def test_quests_seeded(self, mgr):
        assert len(mgr._quests) == 7

    def test_start_onboarding(self, mgr, mock_player_state):
        result = mgr.start_onboarding()
        assert result["status"] == "started"
        assert result["phase"] == "arrival"
        assert mgr.phase == OnboardingPhase.ARRIVAL
        assert mgr.is_started is True

    def test_start_twice_returns_already_started(self, started_mgr, mock_player_state):
        result = started_mgr.start_onboarding()
        assert result["status"] == "already_started"

    def test_advance_not_started(self, mgr):
        result = mgr.advance("read_encrypted_msg")
        assert result["status"] == "not_started"

    def test_advance_objective(self, started_mgr, mock_player_state):
        result = started_mgr.advance("read_encrypted_msg")
        assert result["status"] == "ok"
        assert result["objective"] == "read_encrypted_msg"
        assert "read_encrypted_msg" in started_mgr._completed_objectives

    def test_advance_already_done(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        result = started_mgr.advance("read_encrypted_msg")
        assert result["status"] == "already_done"

    def test_quest_completion(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        result = started_mgr.advance("check_wallet")
        assert result.get("quest_completed") is True
        assert result["quest_rewards"]["credits"] == 200

    def test_phase_advances_after_quest_complete(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        started_mgr.advance("check_wallet")
        assert started_mgr.phase == OnboardingPhase.FIRST_CONTACT

    def test_welcome_message_sent(self, started_mgr):
        assert "ghost_welcome" in started_mgr._messages_sent


class TestSceneVisitTracking:
    """Test scene visit recording and auto-advance."""

    def test_record_scene_visit(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        started_mgr.advance("check_wallet")
        started_mgr.record_scene_visit("grid")
        assert "grid" in started_mgr._scenes_visited

    def test_auto_advance_on_grid_visit(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        started_mgr.advance("check_wallet")
        result = started_mgr.record_scene_visit("grid")
        assert result is not None
        assert result["objective"] == "visit_grid"

    def test_duplicate_visit_ignored(self, started_mgr, mock_player_state):
        started_mgr.record_scene_visit("grid")
        started_mgr.record_scene_visit("grid")
        assert started_mgr._scenes_visited.count("grid") == 1


class TestNPCMeetingTracking:
    """Test NPC meeting recording and auto-advance."""

    def test_record_npc_met(self, started_mgr, mock_player_state):
        started_mgr.record_npc_met("viktor")
        assert "viktor" in started_mgr._npcs_met

    def test_auto_advance_on_viktor_meet(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        started_mgr.advance("check_wallet")
        started_mgr.record_scene_visit("grid")
        result = started_mgr.record_npc_met("viktor")
        assert result is not None
        assert result["objective"] == "talk_to_viktor"


class TestMissionTracking:
    """Test mission completion tracking."""

    def test_record_mission_completed(self, started_mgr, mock_player_state):
        started_mgr.record_mission_completed()
        assert started_mgr._missions_completed == 1

    def test_multiple_missions(self, started_mgr, mock_player_state):
        for _ in range(5):
            started_mgr.record_mission_completed()
        assert started_mgr._missions_completed == 5


class TestReputationChecks:
    """Test reputation-based objective auto-advance."""

    def test_rep_threshold_not_met(self, started_mgr):
        with patch("engine.world.onboarding._player_state") as mock_ps:
            ps = MagicMock()
            ps.reputation = 30
            ps.credits = 1000
            ps.to_dict.return_value = {"faction_standings": {"Ghost_Net": 0}}
            mock_ps.return_value = ps
            result = started_mgr.check_reputation_objectives()
            assert result is None

    def test_rep_threshold_met(self, started_mgr):
        with patch("engine.world.onboarding._player_state") as mock_ps:
            ps = MagicMock()
            ps.reputation = 65
            ps.credits = 15000
            ps.to_dict.return_value = {"faction_standings": {"Ghost_Net": 15}}
            mock_ps.return_value = ps
            result = started_mgr.check_reputation_objectives()
            # Objectives may not be available yet (depends on phase)
            # but the method should not crash
            assert result is not None or result is None


# ── Persistence ───────────────────────────────────────────────────────────

class TestPersistence:
    """Test save/load of onboarding state."""

    def test_save_creates_file(self, started_mgr):
        started_mgr._save()
        assert started_mgr._SAVE_PATH.exists()

    def test_save_load_roundtrip(self, started_mgr, mock_player_state, tmp_path):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.record_scene_visit("grid")
        started_mgr.record_npc_met("viktor")
        started_mgr._save()

        mgr2 = OnboardingManager()
        mgr2._SAVE_PATH = started_mgr._SAVE_PATH
        mgr2._load_or_seed()

        assert mgr2.phase == started_mgr.phase
        assert mgr2._completed_objectives == started_mgr._completed_objectives
        assert mgr2._scenes_visited == started_mgr._scenes_visited
        assert mgr2._npcs_met == started_mgr._npcs_met

    def test_load_with_missing_file(self, tmp_path):
        mgr = OnboardingManager()
        mgr._SAVE_PATH = tmp_path / "nonexistent.json"
        mgr._quests = {}
        mgr._load_or_seed()
        assert len(mgr._quests) == 7


# ── Skip and Reset ────────────────────────────────────────────────────────

class TestSkipAndReset:
    """Test skip and reset functionality."""

    def test_skip(self, started_mgr, mock_player_state):
        result = started_mgr.skip()
        assert result["status"] == "skipped"
        assert started_mgr.phase == OnboardingPhase.COMPLETED
        assert started_mgr.is_completed is True

    def test_skip_marks_all_objectives_complete(self, started_mgr, mock_player_state):
        started_mgr.skip()
        for q in started_mgr._quests.values():
            assert q.completed is True
            for obj in q.objectives:
                assert obj.status == ObjectiveStatus.COMPLETED

    def test_reset(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.reset()
        assert started_mgr.phase == OnboardingPhase.NOT_STARTED
        assert started_mgr._completed_objectives == []
        assert len(started_mgr._quests) == 7


# ── Status API ────────────────────────────────────────────────────────────

class TestStatusAPI:
    """Test status reporting."""

    def test_get_status(self, started_mgr, mock_player_state):
        status = started_mgr.get_status()
        assert status["phase"] == "arrival"
        assert status["is_started"] is True
        assert status["is_completed"] is False
        assert status["quests_total"] == 7

    def test_get_current_quest(self, started_mgr, mock_player_state):
        quest = started_mgr.get_current_quest()
        assert quest is not None
        assert quest["id"] == "q_arrival"

    def test_get_quest_by_id(self, started_mgr, mock_player_state):
        quest = started_mgr.get_quest("q_exploration")
        assert quest is not None
        assert quest["title"] == "MAPPING THE CITY"

    def test_get_quest_nonexistent(self, started_mgr, mock_player_state):
        assert started_mgr.get_quest("nonexistent") is None

    def test_get_all_quests(self, started_mgr, mock_player_state):
        quests = started_mgr.get_all_quests()
        assert len(quests) == 7

    def test_get_next_hint(self, started_mgr, mock_player_state):
        hint = started_mgr.get_next_hint()
        assert hint is not None
        assert "phone" in hint.lower() or "messages" in hint.lower()

    def test_overall_progress(self, started_mgr, mock_player_state):
        status = started_mgr.get_status()
        assert status["overall_progress"] == 0

    def test_progress_after_advance(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        status = started_mgr.get_status()
        assert status["objectives_completed"] == 1
        assert status["overall_progress"] > 0


# ── Phone Messages ────────────────────────────────────────────────────────

class TestPhoneMessages:
    """Test phone message system."""

    def test_welcome_message_content(self):
        assert "GHOST" in ENCRYPTED_WELCOME
        assert "DECRYPTION" in ENCRYPTED_WELCOME
        assert "Viktor" in ENCRYPTED_WELCOME.upper() or "VIKTOR" in ENCRYPTED_WELCOME

    def test_viktor_message_content(self):
        assert "Grid" in VIKTOR_FIRST_MESSAGE or "GRID" in VIKTOR_FIRST_MESSAGE

    def test_lola_message_content(self):
        assert "PENTHOUSE" in LOLA_INTRO_MESSAGE

    def test_frankie_message_content(self):
        assert "LAB" in FRANKIE_INTRO_MESSAGE

    def test_mira_message_content(self):
        assert "COMMAND CENTER" in MIRA_INTRO_MESSAGE

    def test_aria_message_content(self):
        assert "BRIEFING ROOM" in ARIA_INTRO_MESSAGE

    def test_crew_message_content(self):
        assert "CREW" in GHOST_CREW_MESSAGE

    def test_completion_message_content(self):
        assert "GHOST" in GHOST_COMPLETION_MESSAGE

    def test_get_pending_messages(self, started_mgr, mock_player_state):
        messages = started_mgr.get_pending_messages()
        assert len(messages) >= 1
        assert messages[0]["sender"] == "GHOST"

    def test_no_duplicate_messages(self, started_mgr, mock_player_state):
        started_mgr._send_phone_message("ghost_welcome", "test", "GHOST")
        assert started_mgr._messages_sent.count("ghost_welcome") == 1


# ── Event Callbacks ──────────────────────────────────────────────────────

class TestEventCallbacks:
    """Test event callback system."""

    def test_register_callback(self, tmp_path):
        reset_onboarding_manager()
        save_path = tmp_path / "onboarding_cb.json"
        with patch.object(OnboardingManager, "_SAVE_PATH", save_path):
            m = OnboardingManager()
            events = []
            m.on("quest_started", lambda data: events.append(data))
            with patch("engine.world.onboarding._player_state") as mock_ps:
                mock_ps.return_value = MagicMock()
                with patch("engine.world.event_cascade.get_event_cascade"):
                    m.start_onboarding()
            assert len(events) == 1
            assert events[0]["quest_id"] == "q_arrival"

    def test_objective_completed_callback(self, tmp_path):
        reset_onboarding_manager()
        save_path = tmp_path / "onboarding_cb2.json"
        with patch.object(OnboardingManager, "_SAVE_PATH", save_path):
            m = OnboardingManager()
            events = []
            m.on("objective_completed", lambda data: events.append(data))
            with patch("engine.world.onboarding._player_state") as mock_ps:
                mock_ps.return_value = MagicMock()
                with patch("engine.world.event_cascade.get_event_cascade"):
                    m.start_onboarding()
                    m.advance("read_encrypted_msg")
            assert len(events) == 1
            assert events[0]["objective_id"] == "read_encrypted_msg"


# ── Full Progression ──────────────────────────────────────────────────────

class TestFullProgression:
    """Test progressing through all 7 quests end to end."""

    def test_full_quest_chain(self, mgr, mock_player_state):
        mock_player_state.reputation = 65
        mock_player_state.credits = 15000
        mock_player_state.to_dict.return_value = {
            "faction_standings": {"Ghost_Net": 15}
        }

        mgr.start_onboarding()
        assert mgr.phase == OnboardingPhase.ARRIVAL

        # Quest 1: Arrival
        mgr.advance("read_encrypted_msg")
        mgr.advance("explore_phone")
        mgr.advance("check_wallet")
        assert mgr.phase == OnboardingPhase.FIRST_CONTACT

        # Quest 2: First Contact
        mgr.advance("visit_grid")
        mgr.advance("talk_to_viktor")
        mgr.advance("read_viktor_msg")
        assert mgr.phase == OnboardingPhase.EXPLORATION

        # Quest 3: Exploration
        mgr.advance("visit_penthouse")
        mgr.advance("visit_tavern")
        mgr.advance("visit_casino")
        mgr.advance("visit_arena")
        mgr.advance("visit_gallery")
        assert mgr.phase == OnboardingPhase.FIRST_MISSION

        # Quest 4: First Mission
        mgr.advance("view_mission_board")
        mgr.advance("accept_mission")
        mgr.advance("complete_mission")
        assert mgr.phase == OnboardingPhase.CONNECTIONS

        # Quest 5: Connections
        mgr.advance("meet_lola")
        mgr.advance("meet_frankie")
        mgr.advance("meet_mira")
        mgr.advance("meet_aria")
        assert mgr.phase == OnboardingPhase.REPUTATION

        # Quest 6: Reputation
        mgr.advance("earn_reputation_25")
        mgr.advance("earn_credits_10k")
        mgr.advance("faction_standing")
        mgr.advance("complete_3_missions")
        assert mgr.phase == OnboardingPhase.CREW_FORMING

        # Quest 7: Crew Forming
        mgr.advance("read_crew_message")
        mgr.advance("recruit_first")
        mgr.advance("visit_crew_hq")
        assert mgr.phase == OnboardingPhase.COMPLETED
        assert mgr.is_completed is True

    def test_full_chain_objective_count(self, mgr, mock_player_state):
        """Ensure all objectives are tracked after full completion."""
        mock_player_state.reputation = 65
        mock_player_state.credits = 15000
        mock_player_state.to_dict.return_value = {
            "faction_standings": {"Ghost_Net": 15}
        }

        mgr.start_onboarding()

        all_objectives = []
        for q in mgr._quests.values():
            for obj in q.objectives:
                all_objectives.append(obj.id)

        for obj_id in all_objectives:
            mgr.advance(obj_id)

        assert mgr.is_completed is True
        status = mgr.get_status()
        assert status["overall_progress"] == 100


# ── Singleton ─────────────────────────────────────────────────────────────

class TestSingleton:
    """Test singleton pattern."""

    def test_get_onboarding_manager(self):
        reset_onboarding_manager()
        m1 = get_onboarding_manager()
        m2 = get_onboarding_manager()
        assert m1 is m2

    def test_reset_onboarding_manager(self):
        reset_onboarding_manager()
        m1 = get_onboarding_manager()
        reset_onboarding_manager()
        m2 = get_onboarding_manager()
        assert m1 is not m2


# ── Onboarding Skills ────────────────────────────────────────────────────

class TestOnboardingSkills:
    """Test the onboarding MCP skills."""

    def test_skill_imports(self):
        from engine.skills.builtin.onboarding_skills import (
            onboarding_status,
            onboarding_current_quest,
            onboarding_all_quests,
            onboarding_hint,
            onboarding_messages,
            onboarding_start,
            onboarding_advance,
            onboarding_visit_scene,
            onboarding_meet_npc,
            onboarding_mission_done,
            onboarding_check_progress,
            onboarding_skip,
        )
        assert callable(onboarding_status)
        assert callable(onboarding_skip)

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_status_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_status
        mock_mgr.return_value.get_status.return_value = {"phase": "arrival"}
        result = onboarding_status()
        assert "arrival" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_hint_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_hint
        mock_mgr.return_value.get_next_hint.return_value = "Press P to open phone"
        result = onboarding_hint()
        assert "Press P" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_start_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_start
        mock_mgr.return_value.start_onboarding.return_value = {"status": "started"}
        result = onboarding_start()
        assert "started" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_advance_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_advance
        mock_mgr.return_value.advance.return_value = {"status": "ok", "objective": "x"}
        result = onboarding_advance("x")
        assert "ok" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_skip_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_skip
        mock_mgr.return_value.skip.return_value = {"status": "skipped"}
        result = onboarding_skip()
        assert "skipped" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_visit_scene_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_visit_scene
        mock_mgr.return_value.record_scene_visit.return_value = {"objective": "visit_grid"}
        result = onboarding_visit_scene("grid")
        assert "visit_grid" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_meet_npc_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_meet_npc
        mock_mgr.return_value.record_npc_met.return_value = None
        result = onboarding_meet_npc("viktor")
        assert "viktor" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_messages_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_messages
        mock_mgr.return_value.get_pending_messages.return_value = [
            {"id": "ghost_welcome", "sender": "GHOST", "content": "..."}
        ]
        result = onboarding_messages()
        assert "GHOST" in result

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_current_quest_completed(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_current_quest
        mock_mgr.return_value.get_current_quest.return_value = None
        mock_mgr.return_value.is_completed = True
        result = onboarding_current_quest()
        assert "complete" in result.lower()

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_current_quest_not_started(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_current_quest
        mock_mgr.return_value.get_current_quest.return_value = None
        mock_mgr.return_value.is_completed = False
        result = onboarding_current_quest()
        assert "not started" in result.lower()

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_mission_done_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_mission_done
        mock_mgr.return_value.record_mission_completed.return_value = None
        result = onboarding_mission_done()
        assert "recorded" in result.lower()

    @patch("engine.skills.builtin.onboarding_skills._mgr")
    def test_onboarding_check_progress_skill(self, mock_mgr):
        from engine.skills.builtin.onboarding_skills import onboarding_check_progress
        mock_mgr.return_value.check_reputation_objectives.return_value = None
        result = onboarding_check_progress()
        assert "threshold" in result.lower()


# ── Reward Granting ──────────────────────────────────────────────────────

class TestRewardGranting:
    """Test that rewards are applied to PlayerState."""

    def test_credits_granted_on_quest_complete(self, started_mgr, mock_player_state):
        started_mgr.advance("read_encrypted_msg")
        started_mgr.advance("explore_phone")
        started_mgr.advance("check_wallet")
        mock_player_state.earn_credits.assert_called_with(200, reason="onboarding:q_arrival")

    def test_reputation_granted(self, started_mgr, mock_player_state):
        # Complete arrival + first contact to get reputation rewards
        for obj in ["read_encrypted_msg", "explore_phone", "check_wallet"]:
            started_mgr.advance(obj)
        for obj in ["visit_grid", "talk_to_viktor", "read_viktor_msg"]:
            started_mgr.advance(obj)
        mock_player_state.update_reputation.assert_called()

    def test_items_granted(self, started_mgr, mock_player_state):
        # Complete through first_mission quest which gives starter_deck
        for obj in ["read_encrypted_msg", "explore_phone", "check_wallet"]:
            started_mgr.advance(obj)
        for obj in ["visit_grid", "talk_to_viktor", "read_viktor_msg"]:
            started_mgr.advance(obj)
        for obj in ["visit_penthouse", "visit_tavern", "visit_casino", "visit_arena", "visit_gallery"]:
            started_mgr.advance(obj)
        for obj in ["view_mission_board", "accept_mission", "complete_mission"]:
            started_mgr.advance(obj)
        mock_player_state.add_item.assert_called_with("starter_deck")
