"""Tests for engine.world.npc_state and engine.agents.npc_scheduler."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ──── NPCState ────


class TestNPCState:
    """Tests for the NPCState dataclass."""

    def test_creation_with_defaults(self) -> None:
        """NPCState has expected default field values."""
        from engine.world.npc_state import NPCState

        state = NPCState(character_id="lola")
        assert state.character_id == "lola"
        assert state.location == "unknown"
        assert state.activity == "idle"
        assert state.last_action == ""
        assert state.mood == "neutral"
        assert state.is_busy is False
        assert state.last_action_time > 0

    def test_to_dict_is_serializable(self) -> None:
        """NPCState.to_dict() returns a plain dict with all fields."""
        import json
        from engine.world.npc_state import NPCState

        state = NPCState(
            character_id="viktor",
            location="lounge",
            activity="watching the door",
            mood="tense",
            is_busy=True,
        )
        d = state.to_dict()
        assert d["character_id"] == "viktor"
        assert d["location"] == "lounge"
        assert d["activity"] == "watching the door"
        assert d["mood"] == "tense"
        assert d["is_busy"] is True
        # Must round-trip through JSON
        json.dumps(d)

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict() includes every NPCState field."""
        from engine.world.npc_state import NPCState

        state = NPCState(character_id="aria")
        keys = set(state.to_dict().keys())
        expected = {"character_id", "location", "activity", "last_action",
                    "last_action_time", "mood", "is_busy"}
        assert expected == keys


# ──── NPCStateRegistry ────


class TestNPCStateRegistry:
    """Tests for the NPCStateRegistry singleton."""

    def _fresh_registry(self):
        """Return an isolated NPCStateRegistry (bypasses singleton)."""
        from engine.world.npc_state import NPCStateRegistry
        return NPCStateRegistry()

    def test_get_returns_none_for_unknown(self) -> None:
        reg = self._fresh_registry()
        assert reg.get("nobody") is None

    def test_update_creates_new_state(self) -> None:
        """update() on an unknown NPC creates a new NPCState."""
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            state = reg.update("lola", location="penthouse", activity="dealing cards")
        assert state.character_id == "lola"
        assert state.location == "penthouse"
        assert state.activity == "dealing cards"

    def test_update_returns_same_object_on_repeat(self) -> None:
        """update() modifies the existing state in place."""
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            s1 = reg.update("lola", mood="happy")
            s2 = reg.update("lola", mood="tense")
        assert s1 is s2
        assert s2.mood == "tense"

    def test_get_all_returns_registered_states(self) -> None:
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            reg.update("lola")
            reg.update("viktor")
        all_states = reg.get_all()
        ids = {s.character_id for s in all_states}
        assert {"lola", "viktor"} == ids

    def test_list_busy_filters_correctly(self) -> None:
        """list_busy() returns only NPCs where is_busy=True."""
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            reg.update("lola", is_busy=True)
            reg.update("viktor", is_busy=False)
            reg.update("aria", is_busy=True)
        busy_ids = {s.character_id for s in reg.list_busy()}
        assert busy_ids == {"lola", "aria"}

    def test_to_dict_is_serializable(self) -> None:
        """to_dict() produces a JSON-serializable mapping."""
        import json
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            reg.update("lola", location="penthouse")
        d = reg.to_dict()
        assert "lola" in d
        json.dumps(d)

    def test_update_ignores_unknown_fields(self) -> None:
        """Unknown kwargs are silently logged, not raised."""
        reg = self._fresh_registry()
        with patch.object(reg, "_fire_event"):
            state = reg.update("lola", nonexistent_field="oops")
        assert state.character_id == "lola"

    def test_singleton_returns_same_instance(self) -> None:
        from engine.world.npc_state import get_npc_state_registry
        r1 = get_npc_state_registry()
        r2 = get_npc_state_registry()
        assert r1 is r2


# ──── NPCScheduler ────


class TestNPCSchedulerInstantiation:
    """Tests for NPCScheduler basic construction and status."""

    def test_instantiation(self) -> None:
        """NPCScheduler can be created without errors."""
        from engine.agents.npc_scheduler import NPCScheduler
        sched = NPCScheduler(tick_interval=120.0)
        assert sched is not None

    def test_get_status_returns_expected_keys(self) -> None:
        """get_status() returns the four required keys."""
        from engine.agents.npc_scheduler import NPCScheduler
        sched = NPCScheduler(tick_interval=120.0)
        status = sched.get_status()
        assert set(status.keys()) == {"running", "tick_interval", "last_tick_at", "npcs_active"}

    def test_initial_status_not_running(self) -> None:
        from engine.agents.npc_scheduler import NPCScheduler
        sched = NPCScheduler()
        status = sched.get_status()
        assert status["running"] is False
        assert status["last_tick_at"] is None
        assert status["npcs_active"] == 0

    def test_singleton_returns_same_instance(self) -> None:
        from engine.agents.npc_scheduler import get_npc_scheduler
        s1 = get_npc_scheduler()
        s2 = get_npc_scheduler()
        assert s1 is s2


# ──── NPCScheduler tick ────


class TestNPCSchedulerTick:
    """Tests for NPCScheduler.tick() — mocked external dependencies."""

    def _make_scheduler(self) -> Any:
        """Return a fresh NPCScheduler (bypasses singleton)."""
        from engine.agents.npc_scheduler import NPCScheduler
        return NPCScheduler(tick_interval=60.0)

    @patch("engine.agents.npc_scheduler.NPCScheduler._get_idle_npcs")
    @patch("engine.agents.npc_scheduler.NPCScheduler._emit_socket_event")
    @patch("engine.world.npc_state.get_npc_state_registry")
    def test_tick_updates_npc_state(
        self,
        mock_registry_getter,
        mock_emit,
        mock_get_idle,
    ) -> None:
        """tick() calls registry.update for each processed NPC."""
        mock_get_idle.return_value = [
            {"id": "lola", "name": "Lola", "location": "penthouse"},
        ]
        mock_registry = MagicMock()
        mock_registry_getter.return_value = mock_registry

        sched = self._make_scheduler()
        with patch.object(sched, "_generate_activity", return_value="dealing cards"):
            sched.tick()

        mock_registry.update.assert_called_once()
        call_kwargs = mock_registry.update.call_args
        assert call_kwargs.args[0] == "lola" or call_kwargs[0][0] == "lola"

    @patch("engine.agents.npc_scheduler.NPCScheduler._get_idle_npcs")
    def test_tick_with_lmstudio_mocked(self, mock_get_idle) -> None:
        """tick() calls LMStudio and stores the response as activity."""
        mock_get_idle.return_value = [
            {"id": "viktor", "name": "Viktor", "location": "bar"},
        ]
        mock_response = MagicMock()
        mock_response.content = "Viktor is nursing a whisky at the far end of the bar."

        sched = self._make_scheduler()
        with patch("engine.world.npc_state.get_npc_state_registry") as mock_reg_getter, \
             patch("engine.lmstudio.lms_client.get_lms_client") as mock_client_getter:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_response
            mock_client_getter.return_value = mock_client
            mock_registry = MagicMock()
            mock_reg_getter.return_value = mock_registry

            sched._emit_socket_event = MagicMock()
            sched.tick()

        mock_registry.update.assert_called_once()
        call_kwargs = mock_registry.update.call_args
        assert "Viktor is nursing" in call_kwargs[1].get("activity", "")

    @patch("engine.agents.npc_scheduler.NPCScheduler._get_idle_npcs")
    def test_tick_degrades_gracefully_when_lmstudio_unavailable(self, mock_get_idle) -> None:
        """tick() falls back to ACTIVITY_POOL when LMStudio raises."""
        from engine.agents.npc_scheduler import ACTIVITY_POOL

        mock_get_idle.return_value = [
            {"id": "aria", "name": "Aria", "location": "everywhere"},
        ]

        sched = self._make_scheduler()
        with patch("engine.world.npc_state.get_npc_state_registry") as mock_reg_getter, \
             patch("engine.lmstudio.lms_client.get_lms_client", side_effect=Exception("LMS offline")):
            mock_registry = MagicMock()
            mock_reg_getter.return_value = mock_registry
            sched._emit_socket_event = MagicMock()
            # Must not raise
            sched.tick()

        mock_registry.update.assert_called_once()
        call_kwargs = mock_registry.update.call_args
        activity_used = call_kwargs[1].get("activity", "")
        assert activity_used in ACTIVITY_POOL

    def test_tick_with_no_idle_npcs_does_nothing(self) -> None:
        """tick() handles an empty NPC list without crashing."""
        sched = self._make_scheduler()
        with patch.object(sched, "_get_idle_npcs", return_value=[]):
            sched.tick()  # must not raise
        assert sched._npcs_active == 0

    def test_tick_never_raises_on_exception(self) -> None:
        """tick() swallows all exceptions from _process_npc."""
        sched = self._make_scheduler()
        with patch.object(sched, "_get_idle_npcs", return_value=[{"id": "x", "name": "X", "location": "y"}]):
            with patch.object(sched, "_process_npc", side_effect=RuntimeError("explode")):
                sched.tick()  # must not raise


# ──── Scheduler task registration ────


class TestNPCWorldTickTask:
    """Verifies the npc-world-tick task is registered in the daemon."""

    def test_npc_world_tick_task_exists(self) -> None:
        """npc-world-tick is present in _register_builtin_tasks output."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [call.args[0] for call in daemon.register.call_args_list]
        assert "npc-world-tick" in task_ids

    def test_npc_world_tick_callback_runs(self) -> None:
        """_npc_world_tick_callback delegates to NPCScheduler.tick()."""
        from engine.nexus.scheduler_daemon import _npc_world_tick_callback
        with patch("engine.agents.npc_scheduler.get_npc_scheduler") as mock_get:
            mock_sched = MagicMock()
            mock_get.return_value = mock_sched
            result = _npc_world_tick_callback()
        mock_sched.tick.assert_called_once()
        assert result["status"] == "ok"

    def test_npc_world_tick_callback_degrades_gracefully(self) -> None:
        """_npc_world_tick_callback handles exceptions gracefully."""
        from engine.nexus.scheduler_daemon import _npc_world_tick_callback
        with patch("engine.agents.npc_scheduler.get_npc_scheduler", side_effect=Exception("oops")):
            result = _npc_world_tick_callback()
        assert result["status"] == "skipped"
        assert "reason" in result


# ──── NPC skills ────


class TestNPCSkills:
    """Tests for npc_skills.py skill registration and metadata."""

    def test_npc_skills_importable(self) -> None:
        """engine.skills.builtin.npc_skills is importable."""
        from engine.skills.builtin import npc_skills  # noqa: F401

    def test_get_npc_state_skill_has_correct_metadata(self) -> None:
        """get_npc_state skill is registered in SKILL_REGISTRY under pack 'npc'."""
        from engine.skills import SKILL_REGISTRY
        metas = SKILL_REGISTRY.get_pack_metas("npc")
        names = [m.name for m in metas]
        assert "get_npc_state" in names

    def test_list_active_npcs_skill_registered(self) -> None:
        from engine.skills import SKILL_REGISTRY
        metas = SKILL_REGISTRY.get_pack_metas("npc")
        names = [m.name for m in metas]
        assert "list_active_npcs" in names

    def test_set_npc_activity_skill_registered(self) -> None:
        from engine.skills import SKILL_REGISTRY
        metas = SKILL_REGISTRY.get_pack_metas("npc")
        names = [m.name for m in metas]
        assert "set_npc_activity" in names

    def test_get_npc_state_returns_not_found_for_unknown(self) -> None:
        """get_npc_state returns a friendly message when NPC is not in registry."""
        from engine.skills.builtin.npc_skills import get_npc_state
        with patch("engine.world.npc_state.get_npc_state_registry") as mock_getter:
            mock_getter.return_value.get.return_value = None
            result = get_npc_state("nobody")
        assert "not found" in result.lower() or "no recorded state" in result.lower()

    def test_list_active_npcs_empty(self) -> None:
        from engine.skills.builtin.npc_skills import list_active_npcs
        with patch("engine.world.npc_state.get_npc_state_registry") as mock_getter:
            mock_getter.return_value.list_busy.return_value = []
            result = list_active_npcs()
        assert "no npcs" in result.lower()

    def test_set_npc_activity_calls_registry(self) -> None:
        from engine.skills.builtin.npc_skills import set_npc_activity
        from engine.world.npc_state import NPCState

        fake_state = NPCState(character_id="lola", location="penthouse", activity="dealing cards")
        with patch("engine.world.npc_state.get_npc_state_registry") as mock_getter:
            mock_getter.return_value.update.return_value = fake_state
            result = set_npc_activity("lola", "dealing cards", "penthouse")
        assert "lola" in result
        assert "dealing cards" in result
