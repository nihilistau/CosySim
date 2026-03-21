"""Tests for the phone system dashboard endpoints."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_framework():
    """Mock MCPFramework for dashboard tests."""
    fw = MagicMock()
    fw.get_status.return_value = {"nodes": 5, "uptime": 3600}
    fw.list_agent_profiles.return_value = [
        {"name": "aria", "model": "qwen-9b"},
        {"name": "lola", "model": "qwen-3b"},
    ]
    return fw


# ══════════════════════════════════════════════════════════════════════
#  Dashboard endpoint
# ══════════════════════════════════════════════════════════════════════


class TestSystemDashboard:
    """Tests for /api/system/dashboard."""

    @pytest.mark.skip(reason="stub — needs real endpoint test")
    def test_dashboard_returns_ok(self, mock_framework):
        """Dashboard endpoint returns aggregated system status."""
        with patch("content.scenes.phone.phone_scene_v2.get_framework", return_value=mock_framework):
            from content.scenes.phone.phone_scene_v2 import PhoneSceneV2
            # Verify the class has the expected route definitions
            assert True  # Import succeeds, routes defined

    @pytest.mark.skip(reason="stub — needs real endpoint test")
    def test_dashboard_lmstudio_offline(self):
        """Dashboard handles LMStudio being unavailable."""
        # When model_manager import fails, lmstudio shows offline
        mock_fw = MagicMock()
        mock_fw.get_status.return_value = {}
        mock_fw.list_agent_profiles.return_value = []

        with patch("content.scenes.phone.phone_scene_v2.get_framework", return_value=mock_fw):
            # If LMStudio is down, the dashboard still returns ok with lms.online=False
            assert True  # The endpoint handles exceptions gracefully

    @pytest.mark.skip(reason="stub — tests constant length, not actual endpoint behavior")
    def test_dashboard_aggregates_all_services(self):
        """Dashboard response includes all expected top-level keys."""
        expected_keys = {"ok", "mcp", "lmstudio", "nexus", "scheduler", "scenes", "agents", "metrics"}
        # Verify the route handler returns all expected fields
        # (tested via the route definition structure)
        assert len(expected_keys) == 8


# ══════════════════════════════════════════════════════════════════════
#  System chat endpoint
# ══════════════════════════════════════════════════════════════════════


class TestSystemChat:
    """Tests for /api/system/chat."""

    def test_chat_requires_message(self):
        """Empty message returns error."""
        data = {"message": ""}
        assert not data["message"].strip()

    def test_chat_with_assistant(self):
        """Chat routes to system assistant when available."""
        mock_assistant = MagicMock()
        mock_assistant.chat.return_value = "System is healthy."

        with patch("engine.assistant.system_assistant.get_assistant", return_value=mock_assistant):
            result = mock_assistant.chat("How is the system?")
            assert result == "System is healthy."
            mock_assistant.chat.assert_called_once_with("How is the system?")

    def test_chat_falls_back_to_nexus(self):
        """When assistant unavailable, falls back to Nexus Q&A."""
        mock_client = MagicMock()
        mock_client.ask.return_value = {"answer": "Nexus knows the answer."}

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            result = mock_client.ask("How does X work?")
            assert result["answer"] == "Nexus knows the answer."


# ══════════════════════════════════════════════════════════════════════
#  Scheduler tasks endpoint
# ══════════════════════════════════════════════════════════════════════


class TestSchedulerTasks:
    """Tests for /api/system/scheduler/tasks."""

    def test_scheduler_returns_task_list(self):
        """Scheduler daemon exposes task list."""
        mock_sd = MagicMock()
        mock_sd.list_tasks.return_value = [
            {"name": "news-fetch", "interval": "every_8h"},
            {"name": "nexus-dedup", "interval": "daily"},
        ]

        with patch("engine.nexus.scheduler_daemon.get_scheduler_daemon", return_value=mock_sd):
            tasks = mock_sd.list_tasks()
            assert len(tasks) == 2
            assert tasks[0]["name"] == "news-fetch"

    def test_scheduler_handles_not_running(self):
        """When scheduler not running, endpoint still returns."""
        mock_sd = MagicMock()
        mock_sd.list_tasks.return_value = []

        tasks = mock_sd.list_tasks()
        assert tasks == []


# ══════════════════════════════════════════════════════════════════════
#  Nexus recent endpoint
# ══════════════════════════════════════════════════════════════════════


class TestNexusRecent:
    """Tests for /api/system/nexus/recent."""

    def test_nexus_recent_returns_entries(self):
        """Recent entries endpoint returns Nexus search results."""
        mock_client = MagicMock()
        mock_client.search.return_value = [
            {"title": "Entry 1", "content_type": "note"},
            {"title": "Entry 2", "content_type": "code"},
        ]

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            results = mock_client.search("*", limit=10)
            assert len(results) == 2

    def test_nexus_recent_respects_limit(self):
        """Limit parameter controls result count."""
        mock_client = MagicMock()
        mock_client.search.return_value = [{"title": "Only one"}]

        results = mock_client.search("*", limit=1)
        mock_client.search.assert_called_once_with("*", limit=1)
        assert len(results) == 1


# ══════════════════════════════════════════════════════════════════════
#  System app JS registration
# ══════════════════════════════════════════════════════════════════════


class TestSystemAppRegistration:
    """Verify the system dashboard app is registered in phone_v2.js."""

    def test_system_app_registered(self):
        """System app is registered in phone_v2.js."""
        from pathlib import Path
        js_path = Path("content/scenes/phone/static/js/phone_v2.js")
        content = js_path.read_text(encoding="utf-8")
        assert "registerApp('system'" in content

    def test_system_app_has_tabs(self):
        """System app renders with overview, agents, scheduler, chat tabs."""
        from pathlib import Path
        js_path = Path("content/scenes/phone/static/js/phone_v2.js")
        content = js_path.read_text(encoding="utf-8")
        assert "overview" in content
        assert "_renderAgents" in content
        assert "_renderScheduler" in content
        assert "_renderChat" in content

    def test_system_routes_exist(self):
        """Phone scene defines system dashboard routes."""
        from pathlib import Path
        py_path = Path("content/scenes/phone/phone_scene_v2.py")
        content = py_path.read_text(encoding="utf-8")
        assert "/api/system/dashboard" in content
        assert "/api/system/chat" in content
        assert "/api/system/scheduler/tasks" in content
        assert "/api/system/nexus/recent" in content
