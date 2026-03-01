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

    def test_har_ingest_no_file(self, client):
        """POST /api/ingest/har without file returns 400."""
        c, _ = client
        resp = c.post("/api/ingest/har")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_har_commit_starts_job(self, client):
        """POST /api/ingest/har/commit returns job_id immediately."""
        c, scene = client
        with patch("engine.nexus.har_extractor.HARExtractor") as mock_ext_cls:
            mock_ext = MagicMock()
            mock_ext_cls.return_value = mock_ext
            mock_ext.extract.return_value = []
            resp = c.post(
                "/api/ingest/har/commit",
                json={"tmp_path": "/tmp/test.har", "items": ["sources"]},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "running"

    def test_har_status_unknown_job(self, client):
        """GET /api/ingest/har/status/<unknown> returns 404."""
        c, _ = client
        resp = c.get("/api/ingest/har/status/nonexistent_job")
        assert resp.status_code == 404

    def test_har_status_known_job(self, client):
        """GET /api/ingest/har/status/<id> returns job state."""
        c, scene = client
        scene._ingest_jobs["test_job_123"] = {"status": "done", "results": [], "error": None}
        resp = c.get("/api/ingest/har/status/test_job_123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"


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

    # ── librarian_ask smart routing ───────────────────────────────────────

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_ask_low_confidence_escalates_to_nlm(
        self, mock_client_fn, mock_bridge_fn, mock_hybrid_fn
    ):
        """When Nexus confidence is below threshold, escalate to NLM."""
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_ask
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "", "source": "cache", "confidence": 0.1}
        mock_client_fn.return_value = mock_nx

        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.return_value = [{"notebook_id": "nb-1", "title": "Main"}]
        mock_bridge_fn.return_value = mock_bridge

        mock_hybrid = MagicMock()
        mock_hybrid.ask.return_value = {"answer": "NLM says: X works by Y."}
        mock_hybrid_fn.return_value = mock_hybrid

        result = librarian_ask("How does X work?")
        assert "NLM says" in result
        assert "Routed to NLM" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_ask_high_confidence_uses_nexus(self, mock_client_fn):
        """When Nexus confidence >= threshold, use Nexus answer directly."""
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_ask
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "Nexus knows this.", "source": "fts", "confidence": 0.8}
        mock_client_fn.return_value = mock_nx

        result = librarian_ask("What is the MCP?")
        assert "Nexus knows this." in result
        assert "fts" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_ask_nlm_stores_answer_in_nexus(
        self, mock_client_fn, mock_bridge_fn, mock_hybrid_fn
    ):
        """NLM escalation stores the answer back in Nexus for future cache hits."""
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_ask
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "", "source": "cache", "confidence": 0.0}
        mock_client_fn.return_value = mock_nx

        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.return_value = [{"notebook_id": "nb-1"}]
        mock_bridge_fn.return_value = mock_bridge

        mock_hybrid = MagicMock()
        mock_hybrid.ask.return_value = {"answer": "The answer is 42."}
        mock_hybrid_fn.return_value = mock_hybrid

        librarian_ask("What is the meaning?")
        mock_nx.add_qa.assert_called_once()

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_ask_nlm_failure_falls_back_gracefully(
        self, mock_client_fn, mock_bridge_fn, mock_hybrid_fn
    ):
        """If NLM escalation throws, return Nexus result regardless."""
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_ask
        mock_nx = MagicMock()
        mock_nx.ask.return_value = {"answer": "", "source": "cache", "confidence": 0.0}
        mock_client_fn.return_value = mock_nx

        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.side_effect = RuntimeError("NLM offline")
        mock_bridge_fn.return_value = mock_bridge
        mock_hybrid_fn.return_value = MagicMock()

        result = librarian_ask("What is X?")
        assert "No answer found" in result or "Source" in result  # graceful fallback

    # ── librarian_route_stats ─────────────────────────────────────────────

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    def test_librarian_route_stats_no_router(self, _mock):
        """Returns graceful message when query_router is unavailable."""
        from content.scenes.nexus_panel.nexus_panel_skills import librarian_route_stats
        with patch("engine.nexus.query_router.get_query_router", side_effect=ImportError):
            result = librarian_route_stats()
        assert "stats" in result.lower() or "routing" in result.lower()

    # ── NLM panel skills ──────────────────────────────────────────────────

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    def test_nlm_panel_list_notebooks_returns_names(self, mock_bridge_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_list_notebooks
        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.return_value = [
            {"notebook_id": "nb-1", "title": "News Intelligence", "source_count": 5},
            {"notebook_id": "nb-2", "title": "Architecture", "source_count": 12},
        ]
        mock_bridge_fn.return_value = mock_bridge

        result = nlm_panel_list_notebooks()
        assert "nb-1" in result
        assert "News Intelligence" in result
        assert "nb-2" in result
        assert "12" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    def test_nlm_panel_list_notebooks_empty(self, mock_bridge_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_list_notebooks
        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.return_value = []
        mock_bridge_fn.return_value = mock_bridge

        result = nlm_panel_list_notebooks()
        assert "No notebooks" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_node_bridge")
    def test_nlm_panel_list_notebooks_error(self, mock_bridge_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_list_notebooks
        mock_bridge = MagicMock()
        mock_bridge.list_notebooks.side_effect = RuntimeError("Connection refused")
        mock_bridge_fn.return_value = mock_bridge

        result = nlm_panel_list_notebooks()
        assert "Error" in result

    def test_nlm_panel_distill_calls_forge(self):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_distill
        mock_result = MagicMock()
        mock_result.qa_pairs = [{"q": "Q1", "a": "A1"}, {"q": "Q2", "a": "A2"}]
        mock_result.nexus_ids = ["id1", "id2"]
        with patch("engine.nexus.knowledge_forge.get_knowledge_forge") as mock_forge_fn:
            mock_forge = MagicMock()
            mock_forge.distill.return_value = mock_result
            mock_forge_fn.return_value = mock_forge
            result = nlm_panel_distill("nb-1", topic="MCP", count=20)
        assert "2" in result
        assert "nb-1" in result
        assert "MCP" in result

    def test_nlm_panel_distill_error(self):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_distill
        with patch("engine.nexus.knowledge_forge.get_knowledge_forge",
                   side_effect=RuntimeError("NLM offline")):
            result = nlm_panel_distill("nb-1")
        assert "failed" in result.lower()

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_audio_success(self, mock_hybrid_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_audio
        mock_hybrid = MagicMock()
        mock_hybrid.generate_audio.return_value = {"status": "generating", "audio_url": ""}
        mock_hybrid_fn.return_value = mock_hybrid

        result = nlm_panel_audio("nb-1")
        assert "generating" in result or "pending" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_audio_error(self, mock_hybrid_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_audio
        mock_hybrid = MagicMock()
        mock_hybrid.generate_audio.return_value = {"error": "Quota exceeded"}
        mock_hybrid_fn.return_value = mock_hybrid

        result = nlm_panel_audio("nb-1")
        assert "failed" in result.lower() or "Quota" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_bulk_ask_returns_answers(self, mock_hybrid_fn, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_bulk_ask
        mock_hybrid = MagicMock()
        mock_hybrid.ask_batch.return_value = [
            {"answer": "Answer 1"},
            {"answer": "Answer 2"},
        ]
        mock_hybrid_fn.return_value = mock_hybrid
        mock_client_fn.return_value = MagicMock()

        result = nlm_panel_bulk_ask("nb-1", "Q1\nQ2", store_to_nexus=False)
        assert "Q1" in result
        assert "Answer 1" in result
        assert "Q2" in result
        assert "Answer 2" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_client")
    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_bulk_ask_stores_to_nexus(self, mock_hybrid_fn, mock_client_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_bulk_ask
        mock_hybrid = MagicMock()
        mock_hybrid.ask_batch.return_value = [{"answer": "Great answer."}]
        mock_hybrid_fn.return_value = mock_hybrid
        mock_nx = MagicMock()
        mock_client_fn.return_value = mock_nx

        nlm_panel_bulk_ask("nb-1", "What is X?", store_to_nexus=True)
        mock_nx.add_qa.assert_called_once()

    def test_nlm_panel_bulk_ask_empty_questions(self):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_bulk_ask
        result = nlm_panel_bulk_ask("nb-1", "   \n  ", store_to_nexus=False)
        assert "No questions" in result

    def test_nlm_panel_news_digest_calls_pipeline(self):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_news_digest
        with patch("engine.nexus.news_nlm_pipeline.get_news_nlm_pipeline") as mock_pl_fn:
            mock_pl = MagicMock()
            mock_pl.run.return_value = {
                "notebook_id": "nb-news-1",
                "uploaded": True,
                "qa_count": 10,
                "stored": 8,
            }
            mock_pl_fn.return_value = mock_pl
            result = nlm_panel_news_digest(max_articles=15)
        assert "nb-news-1" in result
        assert "10" in result
        assert "8" in result

    def test_nlm_panel_news_digest_error(self):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_news_digest
        with patch("engine.nexus.news_nlm_pipeline.get_news_nlm_pipeline",
                   side_effect=RuntimeError("NLM offline")):
            result = nlm_panel_news_digest()
        assert "failed" in result.lower()

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_setup_auth_success(self, mock_hybrid_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_setup_auth
        mock_hybrid = MagicMock()
        mock_hybrid.setup_auth.return_value = {"status": "authenticated", "message": "Browser opened."}
        mock_hybrid_fn.return_value = mock_hybrid

        result = nlm_panel_setup_auth()
        assert "authenticated" in result

    @patch("content.scenes.nexus_panel.nexus_panel_skills._get_hybrid")
    def test_nlm_panel_setup_auth_error(self, mock_hybrid_fn):
        from content.scenes.nexus_panel.nexus_panel_skills import nlm_panel_setup_auth
        mock_hybrid = MagicMock()
        mock_hybrid.setup_auth.return_value = {"error": "Browser launch failed"}
        mock_hybrid_fn.return_value = mock_hybrid

        result = nlm_panel_setup_auth()
        assert "failed" in result.lower() or "Browser launch" in result
