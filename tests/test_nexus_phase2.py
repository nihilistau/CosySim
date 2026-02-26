"""Tests for Nexus Phase 2 modules: namespaces, memory, training pipeline, workflows, control panel."""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════
#  nexus_namespaces.py Tests
# ══════════════════════════════════════════════════════════════════════


class TestNamespaceDetection:
    """Tests for detect_namespace()."""

    def test_detect_system_by_category(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("architecture", []) == "system"
        assert detect_namespace("api", []) == "system"

    def test_detect_scene_by_tag(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("game", ["scene:bedroom"]) == "scene"

    def test_detect_agent_by_tag(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        # Direct "agent" tag needed for detection
        assert detect_namespace("", ["agent"]) == "agent"
        # Also test via category
        assert detect_namespace("personality", []) == "agent"

    def test_detect_copilot_by_category(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        # copilot tag detection
        assert detect_namespace("", ["copilot"]) == "copilot"
        # copilot category-based detection
        assert detect_namespace("sessions", []) == "copilot"

    def test_detect_training_by_tag(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("", ["training"]) == "training"

    def test_detect_research_by_tag(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("", ["research"]) == "research"

    def test_detect_content_by_tag(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("", ["content"]) == "content"

    def test_default_to_system(self):
        from engine.nexus.nexus_namespaces import detect_namespace
        assert detect_namespace("", []) == "system"


class TestNamespaceValidation:
    """Tests for validate_entry()."""

    def test_valid_system_entry(self):
        from engine.nexus.nexus_namespaces import validate_entry
        result = validate_entry("Architecture Overview", "document", "architecture", ["system"])
        assert result["valid"] is True

    def test_result_has_required_keys(self):
        from engine.nexus.nexus_namespaces import validate_entry
        result = validate_entry("Test", "memory", "architecture", ["system"], namespace="system")
        assert "valid" in result
        assert "namespace" in result
        assert "errors" in result or "warnings" in result

    def test_scene_validation(self):
        from engine.nexus.nexus_namespaces import validate_entry
        result = validate_entry("Scene Doc", "document", "game", [], namespace="scene")
        assert isinstance(result, dict)


class TestNamespaceAccessControl:
    """Tests for can_access()."""

    def test_system_access(self):
        from engine.nexus.nexus_namespaces import can_access
        assert can_access("system", "system") is True

    def test_copilot_reads_system(self):
        from engine.nexus.nexus_namespaces import can_access
        assert can_access("copilot", "system") is True

    def test_agent_reads_content(self):
        from engine.nexus.nexus_namespaces import can_access
        assert can_access("agent", "content") is True

    def test_content_cannot_access_training(self):
        from engine.nexus.nexus_namespaces import can_access
        assert can_access("content", "training") is False


class TestNamespaceEnforcement:
    """Tests for enforce_namespace()."""

    def test_adds_namespace_tag(self):
        from engine.nexus.nexus_namespaces import enforce_namespace
        result = enforce_namespace(
            title="Arch Doc",
            content="Architecture overview",
            content_type="document",
            category="architecture",
            tags=[],
        )
        assert "system" in result.get("tags", [])

    def test_preserves_existing_tags(self):
        from engine.nexus.nexus_namespaces import enforce_namespace
        result = enforce_namespace(
            title="Scene Doc",
            content="Scene content",
            content_type="note",
            category="game",
            tags=["scene:bedroom", "existing"],
        )
        assert "existing" in result.get("tags", [])


class TestInteractionRules:
    """Tests for generate_interaction_rules()."""

    def test_generates_rules(self):
        from engine.nexus.nexus_namespaces import generate_interaction_rules
        rules = generate_interaction_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_rules_have_required_fields(self):
        from engine.nexus.nexus_namespaces import generate_interaction_rules
        rules = generate_interaction_rules()
        for rule in rules:
            assert "name" in rule
            assert "scope" in rule
            assert "rule_type" in rule


# ══════════════════════════════════════════════════════════════════════
#  nexus_memory.py Tests
# ══════════════════════════════════════════════════════════════════════


class TestNexusMemory:
    """Tests for NexusMemory class."""

    @patch("requests.post")
    def test_remember_stores_entry(self, mock_post):
        from engine.nexus.nexus_memory import NexusMemory
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "mem-123"}}
        )
        mem = NexusMemory(namespace="copilot", agent_id="copilot")
        result = mem.remember("Test memory content", importance=0.8, memory_type="fact")
        assert result == "mem-123"
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_remember_includes_tags(self, mock_post):
        from engine.nexus.nexus_memory import NexusMemory
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "mem-456"}}
        )
        mem = NexusMemory(namespace="agent", agent_id="lola")
        mem.remember("Lola likes tea", importance=0.6, memory_type="preference")
        call_args = mock_post.call_args
        payload = call_args[1].get("json", {})
        tags = payload.get("tags", [])
        assert "agent" in tags
        assert "agent:lola" in tags
        assert "memory" in tags

    @patch("requests.get")
    def test_recall_searches(self, mock_get):
        from engine.nexus.nexus_memory import NexusMemory
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"id": "1", "title": "Memory: test", "content": "recalled", "tags": "agent,memory,agent:copilot"}
            ]}
        )
        mem = NexusMemory(namespace="copilot", agent_id="copilot")
        results = mem.recall("test", top_k=5)
        assert isinstance(results, list)

    @patch("requests.get")
    def test_get_context_window(self, mock_get):
        from engine.nexus.nexus_memory import NexusMemory
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"id": "1", "title": "Memory: important thing", "content": "context data",
                 "tags": "agent,memory,agent:copilot,importance:0.9"}
            ]}
        )
        mem = NexusMemory(namespace="copilot", agent_id="copilot")
        context = mem.get_context_window(max_chars=500)
        assert isinstance(context, str)

    @patch("requests.delete")
    def test_forget_deletes(self, mock_delete):
        from engine.nexus.nexus_memory import NexusMemory
        mock_delete.return_value = MagicMock(ok=True)
        mem = NexusMemory(namespace="copilot", agent_id="copilot")
        result = mem.forget("mem-789")
        assert result is True

    @patch("requests.delete")
    @patch("requests.get")
    def test_compact_reduces_memories(self, mock_get, mock_delete):
        from engine.nexus.nexus_memory import NexusMemory
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"id": f"m{i}", "title": f"Memory: test {i}", "content": f"content {i}",
                 "tags": f"copilot,memory,agent:copilot,importance:{0.1 + i*0.1}"}
                for i in range(5)
            ]}
        )
        mock_delete.return_value = MagicMock(ok=True)
        mem = NexusMemory(namespace="copilot", agent_id="copilot")
        result = mem.compact(max_memories=3)
        assert isinstance(result, int)


class TestMemoryFactoryFunctions:
    """Tests for factory functions."""

    def test_get_copilot_memory(self):
        from engine.nexus.nexus_memory import get_copilot_memory
        mem = get_copilot_memory()
        assert mem._agent_id == "copilot"
        assert mem._namespace == "copilot"

    def test_get_character_memory(self):
        from engine.nexus.nexus_memory import get_character_memory
        mem = get_character_memory("lola")
        assert mem._agent_id == "lola"
        assert mem._namespace == "agent"


# ══════════════════════════════════════════════════════════════════════
#  training_pipeline.py Tests
# ══════════════════════════════════════════════════════════════════════


class TestTrainingPipeline:
    """Tests for TrainingPipeline class."""

    @patch("requests.post")
    def test_capture_interaction(self, mock_post):
        from engine.nexus.training_pipeline import TrainingPipeline
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "train-1"}}
        )
        tp = TrainingPipeline()
        entry_id = tp.capture_interaction("Hello", "Hi there!", dataset_type="conversation")
        assert entry_id == "train-1"

    @patch("requests.post")
    def test_capture_includes_metadata(self, mock_post):
        from engine.nexus.training_pipeline import TrainingPipeline
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "train-2"}}
        )
        tp = TrainingPipeline()
        tp.capture_interaction("User msg", "Agent reply",
                               dataset_type="tool_routing", quality_score=0.9,
                               character_id="lola")
        call_args = mock_post.call_args
        payload = call_args[1].get("json", {})
        tags = payload.get("tags", [])
        assert "training" in tags

    def test_generate_synthetic_tag_extraction(self):
        from engine.nexus.training_pipeline import TrainingPipeline
        tp = TrainingPipeline()
        examples = tp.generate_synthetic("tag_extraction", 3)
        assert len(examples) == 3
        for ex in examples:
            assert "user" in ex or "input" in ex

    def test_generate_synthetic_tool_routing(self):
        from engine.nexus.training_pipeline import TrainingPipeline
        tp = TrainingPipeline()
        examples = tp.generate_synthetic("tool_routing", 3)
        assert len(examples) == 3

    def test_get_stats_structure(self):
        from engine.nexus.training_pipeline import TrainingPipeline
        tp = TrainingPipeline()
        stats = tp.get_stats()
        assert "total" in stats
        assert "buffer_size" in stats
        assert "by_type" in stats

    @patch("requests.get")
    def test_export_dataset(self, mock_get):
        from engine.nexus.training_pipeline import TrainingPipeline
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"id": "1", "content": json.dumps({
                    "user": "test", "agent": "reply",
                    "quality": 0.8, "type": "conversation"
                }), "tags": "training,type:conversation"}
            ]}
        )
        tp = TrainingPipeline()
        result = tp.export_dataset("conversation", min_quality=0.5)
        assert isinstance(result, dict)


class TestTrainingPipelineSingleton:
    """Tests for singleton access."""

    def test_get_training_pipeline(self):
        from engine.nexus.training_pipeline import get_training_pipeline
        tp1 = get_training_pipeline()
        tp2 = get_training_pipeline()
        assert tp1 is tp2


# ══════════════════════════════════════════════════════════════════════
#  workflows.py Tests
# ══════════════════════════════════════════════════════════════════════


class TestContentWorkflow:
    """Tests for ContentWorkflow."""

    @patch("requests.post")
    def test_generate_greetings(self, mock_post):
        from engine.nexus.workflows import ContentWorkflow
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "cw-1"}}
        )
        cw = ContentWorkflow()
        ids = cw.generate_greetings("lola", personality_tags=["flirty"])
        assert len(ids) > 0

    @patch("requests.post")
    def test_generate_reactions(self, mock_post):
        from engine.nexus.workflows import ContentWorkflow
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "cw-2"}}
        )
        cw = ContentWorkflow()
        ids = cw.generate_reactions("viktor")
        assert len(ids) > 0

    @patch("requests.post")
    def test_generate_scene_descriptions(self, mock_post):
        from engine.nexus.workflows import ContentWorkflow
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "cw-3"}}
        )
        cw = ContentWorkflow()
        ids = cw.generate_scene_descriptions("bedroom")
        assert len(ids) > 0

    @patch("requests.get")
    def test_lookup_content(self, mock_get):
        from engine.nexus.workflows import ContentWorkflow
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"id": "1", "content": '{"greetings": ["hi"]}', "tags": "content,character:lola"}
            ]}
        )
        cw = ContentWorkflow()
        results = cw.lookup_content("lola", "greetings")
        assert isinstance(results, list)


class TestResearchWorkflow:
    """Tests for ResearchWorkflow."""

    @patch("requests.get")
    def test_research_finds_existing(self, mock_get):
        from engine.nexus.workflows import ResearchWorkflow
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": [
                {"question": "How does X work?", "answer": "X works by...", "id": "qa-1"}
            ]}
        )
        rw = ResearchWorkflow()
        result = rw.research("How does X work?", depth="shallow")
        assert result.get("answer") is not None

    @patch("requests.get")
    def test_research_uses_fts_fallback(self, mock_get):
        from engine.nexus.workflows import ResearchWorkflow
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": []}
        )
        rw = ResearchWorkflow()
        result = rw.research("Unknown topic", depth="shallow")
        assert isinstance(result, dict)

    @patch("requests.post")
    def test_store_findings(self, mock_post):
        from engine.nexus.workflows import ResearchWorkflow
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "r-1"}}
        )
        rw = ResearchWorkflow()
        result = rw.store_findings({
            "question": "Topic",
            "answer": "Findings content",
            "depth": "shallow",
        })
        assert result is not None


class TestNotebookWorkflow:
    """Tests for NotebookWorkflow."""

    @patch("requests.get")
    def test_check_nlm_status(self, mock_get):
        from engine.nexus.workflows import NotebookWorkflow
        mock_get.return_value = MagicMock(ok=False)
        nw = NotebookWorkflow()
        status = nw.check_nlm_status()
        assert isinstance(status, dict)
        assert "http" in status

    @patch("requests.post")
    def test_seed_notebook_knowledge_all(self, mock_post):
        from engine.nexus.workflows import NotebookWorkflow
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "nb-1"}}
        )
        nw = NotebookWorkflow()
        result = nw.seed_notebook_knowledge("all")
        assert isinstance(result, dict)
        assert "entries_created" in result


# ══════════════════════════════════════════════════════════════════════
#  MCP Tool Tests (new tools)
# ══════════════════════════════════════════════════════════════════════


class TestMCPMemoryTools:
    """Tests for memory MCP tools in cosysim_server."""

    @patch("requests.post")
    def test_nexus_remember_tool(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "mem-tool-1"}}
        )
        from engine.mcp.cosysim_server import nexus_remember
        fn = nexus_remember.fn if hasattr(nexus_remember, "fn") else nexus_remember
        result = json.loads(fn("Test memory", agent_id="copilot"))
        assert result["status"] == "ok"
        assert result["entry_id"] == "mem-tool-1"

    @patch("requests.get")
    def test_nexus_recall_tool(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": []}
        )
        from engine.mcp.cosysim_server import nexus_recall
        fn = nexus_recall.fn if hasattr(nexus_recall, "fn") else nexus_recall
        result = json.loads(fn("test query", agent_id="copilot"))
        assert result["status"] == "ok"

    @patch("requests.get")
    def test_nexus_memory_context_tool(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"data": []}
        )
        from engine.mcp.cosysim_server import nexus_memory_context
        fn = nexus_memory_context.fn if hasattr(nexus_memory_context, "fn") else nexus_memory_context
        result = json.loads(fn(agent_id="copilot"))
        assert result["status"] == "ok"

    @patch("requests.post")
    def test_capture_training_data_tool(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "train-tool-1"}}
        )
        from engine.mcp.cosysim_server import capture_training_data
        fn = capture_training_data.fn if hasattr(capture_training_data, "fn") else capture_training_data
        result = json.loads(fn("Hello", "Hi there!"))
        assert result["status"] == "ok"

    @patch("requests.post")
    def test_generate_content_tool(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "gen-1"}}
        )
        from engine.mcp.cosysim_server import generate_content
        fn = generate_content.fn if hasattr(generate_content, "fn") else generate_content
        result = json.loads(fn("lola", "greetings"))
        assert result["status"] == "ok"


# ══════════════════════════════════════════════════════════════════════
#  Control Panel Helpers
# ══════════════════════════════════════════════════════════════════════


class TestControlPanelHelpers:
    """Tests for control_panel.py helper functions (non-Streamlit parts)."""

    @patch("requests.get")
    def test_api_get_returns_data(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True, json=lambda: {"data": [{"id": 1}]}
        )
        from engine.nexus.control_panel import api_get
        result = api_get("/api/entries")
        assert result == [{"id": 1}]

    @patch("requests.get")
    def test_api_get_handles_error(self, mock_get):
        mock_get.side_effect = ConnectionError("down")
        from engine.nexus.control_panel import api_get
        result = api_get("/api/entries")
        assert result == []

    @patch("requests.post")
    def test_api_post_returns_json(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True, json=lambda: {"data": {"id": "new-1"}}
        )
        from engine.nexus.control_panel import api_post
        result = api_post("/api/entries", {"title": "test"})
        assert "data" in result

    @patch("requests.delete")
    def test_api_delete_returns_bool(self, mock_delete):
        mock_delete.return_value = MagicMock(ok=True)
        from engine.nexus.control_panel import api_delete
        result = api_delete("/api/entries/123")
        assert result is True
