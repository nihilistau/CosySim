"""Tests for the Nexus Control Panel scene."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── Scene class tests ────────────────────────────────────────────────────

class TestNexusPanelScene:
    """Test NexusPanelScene initialisation and metadata."""

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_scene_init(self, mock_nexus_init):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        assert scene.scene_name == "nexus_panel"
        # Port may be overridden by config, so just verify it's set
        assert isinstance(scene.port, int)
        assert scene.app is not None
        mock_nexus_init.assert_called_once_with("nexus_panel")

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_scene_metadata(self, mock_nexus_init):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        info = scene.get_plugin_info()
        assert info["name"] == "nexus_panel"
        assert info["type"] == "admin"
        assert "librarian agent" in info["features"]

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_activity_logging(self, mock_nexus_init):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        scene._log_activity("test_action", "test detail", "test_source")
        activity = scene._get_activity(10)
        assert len(activity) == 1
        assert activity[0]["action"] == "test_action"
        assert activity[0]["detail"] == "test detail"
        assert activity[0]["source"] == "test_source"

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_activity_ring_buffer(self, mock_nexus_init):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        for i in range(10):
            scene._log_activity(f"action_{i}")
        activity = scene._get_activity(5)
        assert len(activity) == 5
        # Most recent first
        assert activity[0]["action"] == "action_9"

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_stats_tracking(self, mock_nexus_init):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        assert scene._stats["api_calls"] == 0
        scene._log_activity("test")
        assert scene._stats["api_calls"] == 1

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_flush")
    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init")
    def test_stop_flushes_nexus(self, mock_nexus_init, mock_nexus_flush):
        from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
        scene = NexusPanelScene(port=15570)
        scene.stop()
        mock_nexus_flush.assert_called_once()


# ── Flask route tests ────────────────────────────────────────────────────

class TestNexusPanelRoutes:
    """Test Flask API routes."""

    @pytest.fixture
    def client(self):
        with patch("content.scenes.nexus_panel.nexus_panel_scene.NexusSceneMixin.nexus_init"):
            from content.scenes.nexus_panel.nexus_panel_scene import NexusPanelScene
            scene = NexusPanelScene(port=15570)
            scene.app.config["TESTING"] = True
            with scene.app.test_client() as client:
                yield client, scene

    def test_health_endpoint(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["scene"] == "nexus_panel"

    def test_index_renders(self, client):
        c, _ = client
        resp = c.get("/")
        assert resp.status_code == 200
        assert b"NEXUS" in resp.data

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_stats_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.is_available.return_value = True
        mock_nx.stats.return_value = {"total_entries": 42, "total_qa": 10}
        mock_client_fn.return_value = mock_nx
        # Need to rebind the closure
        scene._get_client = lambda: mock_nx

        resp = c.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["nexus_available"] is True

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_search_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.search.return_value = [{"title": "Test", "content": "hello"}]
        scene._get_client = lambda: mock_nx

        resp = c.get("/api/search?q=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["title"] == "Test"

    def test_search_no_query(self, client):
        c, _ = client
        resp = c.get("/api/search")
        assert resp.status_code == 200
        assert resp.get_json() == []

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_add_entry_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.add_entry.return_value = {"id": "new-1"}
        scene._get_client = lambda: mock_nx

        resp = c.post("/api/entry", json={
            "title": "Test Entry",
            "content": "Test content",
            "content_type": "note",
        })
        assert resp.status_code == 200
        mock_nx.add_entry.assert_called_once()

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_ask_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "42", "source": "cache", "confidence": 1.0}
        scene._get_client = lambda: mock_nx

        resp = c.post("/api/ask", json={"question": "meaning of life?"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["answer"] == "42"

    def test_ask_no_question(self, client):
        c, _ = client
        resp = c.post("/api/ask", json={})
        assert resp.status_code == 400

    @patch("engine.nexus.self_maintenance.nexus_health_report")
    def test_maintain_health(self, mock_health, client):
        c, _ = client
        mock_health.return_value = {"status": "healthy", "metrics": {}}
        resp = c.post("/api/maintain/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_maintain_unknown_action(self, client):
        c, _ = client
        resp = c.post("/api/maintain/bogus")
        assert resp.status_code == 400

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_librarian_chat(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.is_available.return_value = True
        mock_nx.ask.return_value = {
            "answer": "The interceptor pipeline governs agent behavior.",
            "source": "fts",
            "confidence": 0.8,
            "sources": [],
        }
        scene._get_client = lambda: mock_nx

        resp = c.post("/api/librarian/chat", json={"message": "How does the interceptor work?"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "interceptor" in data["response"].lower()
        assert data["source"] == "fts"

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_librarian_offline(self, mock_client_fn, client):
        c, scene = client
        scene._get_client = lambda: None

        resp = c.post("/api/librarian/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "offline"

    def test_librarian_no_message(self, client):
        c, _ = client
        resp = c.post("/api/librarian/chat", json={})
        assert resp.status_code == 400

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_delete_entry(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        scene._get_client = lambda: mock_nx

        resp = c.delete("/api/entry/abc-123")
        assert resp.status_code == 200
        mock_nx.delete_entry.assert_called_once_with("abc-123")

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_prompts_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.get_prompts.return_value = [{"title": "System Prompt", "category": "system"}]
        scene._get_client = lambda: mock_nx

        resp = c.get("/api/prompts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_sessions_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.list_sessions.return_value = [{"project": "CosySim", "status": "active"}]
        scene._get_client = lambda: mock_nx

        resp = c.get("/api/sessions")
        assert resp.status_code == 200

    @patch("content.scenes.nexus_panel.nexus_panel_scene.NexusPanelScene._get_client")
    def test_rules_endpoint(self, mock_client_fn, client):
        c, scene = client
        mock_nx = MagicMock()
        mock_nx.get_rules.return_value = []
        scene._get_client = lambda: mock_nx

        resp = c.get("/api/rules")
        assert resp.status_code == 200


# ── Skills tests ─────────────────────────────────────────────────────────

class TestNexusPanelSkills:
    """Test nexus_panel skills."""

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_search(self, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_search
        mock_nx = MagicMock()
        mock_nx.search.return_value = [{"title": "MCP Framework", "content": "The MCP..."}]
        mock_client_fn.return_value = mock_nx

        result = librarian_search("MCP")
        assert "MCP Framework" in result
        assert "1 results" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_search_empty(self, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_search
        mock_nx = MagicMock()
        mock_nx.search.return_value = []
        mock_client_fn.return_value = mock_nx

        result = librarian_search("nonexistent")
        assert "No results" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_ask(self, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_ask
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "It works by...", "source": "cache", "confidence": 0.9}
        mock_client_fn.return_value = mock_nx

        result = librarian_ask("How does it work?")
        assert "It works by..." in result
        assert "cache" in result
        assert "90%" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_store(self, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_store
        mock_nx = MagicMock()
        mock_nx.add_entry.return_value = {"id": "new-1"}
        mock_client_fn.return_value = mock_nx

        result = librarian_store("Test", "Content here", "note", "general")
        assert "Test" in result
        mock_nx.add_entry.assert_called_once()

    @patch("engine.nexus.self_maintenance.nexus_health_report")
    def test_librarian_maintain(self, mock_health):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_maintain
        mock_health.return_value = {"status": "healthy"}

        result = librarian_maintain("health")
        assert "healthy" in result

    def test_librarian_maintain_unknown(self):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_maintain
        result = librarian_maintain("bogus")
        assert "Unknown action" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_stats(self, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_stats
        mock_nx = MagicMock()
        mock_nx.stats.return_value = {"total_entries": 100}
        mock_nx.health.return_value = {"status": "ok"}
        mock_client_fn.return_value = mock_nx

        result = librarian_stats()
        assert "total_entries" in result
        assert "100" in result
