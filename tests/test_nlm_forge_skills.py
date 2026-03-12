"""
Tests for NLM Forge Skills — engine/skills/builtin/nlm_forge_skills.py

Validates all 10 NLM forge skills (ask, batch_ask, create_notebook,
add_codebase, generate_doc, distill, decompose, analyze, solve,
build_topic) with mocked NLMEngine, KnowledgeForge, and NLMRouter.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# PATCH TARGETS — patch at the source module where lazy imports resolve
# ═══════════════════════════════════════════════════════════════════

_ENGINE_PATH = "engine.nexus.nlm_engine.get_nlm_engine"
_FORGE_PATH = "engine.nexus.knowledge_forge.get_knowledge_forge"
_ROUTER_PATH = "engine.nexus.nlm_router.get_nlm_router"


# ═══════════════════════════════════════════════════════════════════
# HELPERS — build realistic mock objects with sensible defaults
# ═══════════════════════════════════════════════════════════════════

def _mock_route_result(**overrides: Any) -> MagicMock:
    """Build a mock NLMRouter route result."""
    result = MagicMock()
    result.to_dict.return_value = {
        "answer": overrides.get("answer", "Mocked NLM answer"),
        "source_tier": overrides.get("source_tier", "nexus_cache"),
        "confidence": overrides.get("confidence", 0.95),
        "savings": overrides.get("savings", {"tokens_saved": 500}),
    }
    return result


def _mock_forge_result(**overrides: Any) -> MagicMock:
    """Build a mock KnowledgeForge result with standard fields."""
    result = MagicMock()
    result.success = overrides.get("success", True)
    result.errors = overrides.get("errors", [])
    result.duration_seconds = overrides.get("duration_seconds", 1.5)
    result.documents = overrides.get("documents", ["# Generated Doc"])
    result.steps = overrides.get("steps", [
        {"step": 1, "file": "main.py", "change": "Add import"},
    ])
    result.notebook_id = overrides.get("notebook_id", "nb-abcdef12")
    result.nexus_ids = overrides.get("nexus_ids", ["nex-001", "nex-002"])
    # qa_pairs — each item has .to_dict()
    qa_pairs = overrides.get("qa_pairs", None)
    if qa_pairs is None:
        pair = MagicMock()
        pair.to_dict.return_value = {
            "question": "How does X work?",
            "answer": "X works by doing Y.",
        }
        qa_pairs = [pair]
    result.qa_pairs = qa_pairs
    return result


# ═══════════════════════════════════════════════════════════════════
# SKILL IMPORT & REGISTRATION
# ═══════════════════════════════════════════════════════════════════

class TestSkillRegistration:
    """Verify all NLM forge skills are importable and registered."""

    def test_import_module(self):
        """Module imports without errors."""
        from engine.skills.builtin import nlm_forge_skills
        assert nlm_forge_skills is not None

    def test_all_skills_callable(self):
        """Every public skill function is callable."""
        from engine.skills.builtin.nlm_forge_skills import (
            nlm_ask,
            nlm_batch_ask,
            nlm_create_notebook,
            nlm_add_codebase,
            nlm_generate_doc,
            nlm_distill,
            nlm_decompose,
            nlm_analyze,
            nlm_solve,
            nlm_build_topic,
        )
        for fn in [
            nlm_ask, nlm_batch_ask, nlm_create_notebook, nlm_add_codebase,
            nlm_generate_doc, nlm_distill, nlm_decompose, nlm_analyze,
            nlm_solve, nlm_build_topic,
        ]:
            assert callable(fn)

    def test_skills_registered_in_registry(self):
        """All 10 NLM forge skills appear in the SKILL_REGISTRY."""
        from engine.skills.registry import SKILL_REGISTRY
        expected = [
            "nlm_ask", "nlm_batch_ask", "nlm_create_notebook",
            "nlm_add_codebase", "nlm_generate_doc", "nlm_distill",
            "nlm_decompose", "nlm_analyze", "nlm_solve", "nlm_build_topic",
        ]
        for name in expected:
            assert SKILL_REGISTRY.get_skill(name) is not None, (
                f"{name} not in SKILL_REGISTRY"
            )


# ═══════════════════════════════════════════════════════════════════
# nlm_ask
# ═══════════════════════════════════════════════════════════════════

class TestNlmAsk:
    """Tests for the nlm_ask skill."""

    @patch(_ROUTER_PATH)
    def test_success_returns_routed_answer(self, mock_get_router):
        """Successful route returns JSON with answer and source_tier."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result(
            answer="The interceptor pipeline processes events in order.",
            source_tier="nlm",
            confidence=0.88,
        )
        mock_get_router.return_value = mock_router

        result = nlm_ask("How does the interceptor pipeline work?")
        data = json.loads(result)

        assert data["answer"] == "The interceptor pipeline processes events in order."
        assert data["source_tier"] == "nlm"
        assert data["confidence"] == 0.88
        assert "savings" in data
        mock_router.route.assert_called_once_with(
            "How does the interceptor pipeline work?", notebook_id="",
        )

    @patch(_ROUTER_PATH)
    def test_success_with_notebook_id(self, mock_get_router):
        """Optional notebook_id is forwarded to the router."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        result = nlm_ask("What is X?", notebook_id="nb-123")
        data = json.loads(result)

        assert "error" not in data
        mock_router.route.assert_called_once_with("What is X?", notebook_id="nb-123")

    @patch(_ROUTER_PATH)
    def test_exception_returns_error_json(self, mock_get_router):
        """Router failure returns JSON with error key."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_get_router.side_effect = RuntimeError("Router unavailable")

        result = nlm_ask("broken question")
        data = json.loads(result)

        assert "error" in data
        assert "Router unavailable" in data["error"]

    @patch(_ROUTER_PATH)
    def test_route_exception_returns_error_json(self, mock_get_router):
        """Exception during route() call returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.side_effect = ValueError("bad question format")
        mock_get_router.return_value = mock_router

        result = nlm_ask("??? malformed")
        data = json.loads(result)

        assert "error" in data
        assert "bad question format" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_batch_ask
# ═══════════════════════════════════════════════════════════════════

class TestNlmBatchAsk:
    """Tests for the nlm_batch_ask skill."""

    @patch(_ROUTER_PATH)
    def test_success_with_json_string_input(self, mock_get_router):
        """JSON string array of questions returns array of results."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        questions_json = json.dumps(["Q1?", "Q2?", "Q3?"])
        result = nlm_batch_ask(questions_json)
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 3
        assert mock_router.route.call_count == 3

    @patch(_ROUTER_PATH)
    def test_success_with_list_input(self, mock_get_router):
        """List input (non-string) is accepted directly."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        result = nlm_batch_ask(["Q1?", "Q2?"])
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 2

    @patch(_ROUTER_PATH)
    def test_each_result_has_expected_keys(self, mock_get_router):
        """Each result dict contains answer, source_tier, confidence."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result(
            answer="Batch answer", source_tier="fts",
        )
        mock_get_router.return_value = mock_router

        result = nlm_batch_ask(json.dumps(["Q1?"]))
        data = json.loads(result)

        assert data[0]["answer"] == "Batch answer"
        assert data[0]["source_tier"] == "fts"

    @patch(_ROUTER_PATH)
    def test_notebook_id_forwarded(self, mock_get_router):
        """notebook_id is passed through to each route call."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        nlm_batch_ask(json.dumps(["Q1?"]), notebook_id="nb-555")
        mock_router.route.assert_called_once_with("Q1?", notebook_id="nb-555")

    @patch(_ROUTER_PATH)
    def test_exception_returns_error_json(self, mock_get_router):
        """Router failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_get_router.side_effect = ConnectionError("network down")

        result = nlm_batch_ask(json.dumps(["Q1?"]))
        data = json.loads(result)

        assert "error" in data
        assert "network down" in data["error"]

    @patch(_ROUTER_PATH)
    def test_invalid_json_input_returns_error(self, mock_get_router):
        """Malformed JSON string returns error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask

        result = nlm_batch_ask("not valid json [[[")
        data = json.loads(result)

        assert "error" in data

    @patch(_ROUTER_PATH)
    def test_empty_list_returns_empty_array(self, mock_get_router):
        """Empty question list returns empty JSON array."""
        from engine.skills.builtin.nlm_forge_skills import nlm_batch_ask
        mock_router = MagicMock()
        mock_get_router.return_value = mock_router

        result = nlm_batch_ask(json.dumps([]))
        data = json.loads(result)

        assert data == []
        mock_router.route.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# nlm_create_notebook
# ═══════════════════════════════════════════════════════════════════

class TestNlmCreateNotebook:
    """Tests for the nlm_create_notebook skill."""

    @patch("engine.nexus.nlm_notebook_factory.get_notebook_factory")
    def test_success_without_sources(self, mock_get_factory):
        """Create notebook without sources returns result JSON."""
        from engine.skills.builtin.nlm_forge_skills import nlm_create_notebook
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = "nb-new-001"
        mock_get_factory.return_value = mock_factory

        result = nlm_create_notebook("Test NB")
        data = json.loads(result)

        assert data["notebook_id"] == "nb-new-001"
        assert data["name"] == "Test NB"
        mock_factory.get_or_create.assert_called_once()

    @patch("engine.nexus.nlm_notebook_factory.get_notebook_factory")
    def test_success_with_sources(self, mock_get_factory):
        """Create notebook with JSON source array passes sources through."""
        from engine.skills.builtin.nlm_forge_skills import nlm_create_notebook
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = "nb-002"
        mock_get_factory.return_value = mock_factory

        sources = json.dumps(["https://example.com/doc.md", "https://other.com"])
        result = nlm_create_notebook("My NB", sources=sources)
        data = json.loads(result)

        assert data["notebook_id"] == "nb-002"
        mock_factory.get_or_create.assert_called_once()

    @patch("engine.nexus.nlm_notebook_factory.get_notebook_factory")
    def test_empty_sources_string_passes_none(self, mock_get_factory):
        """Empty string sources treated as None — factory still called."""
        from engine.skills.builtin.nlm_forge_skills import nlm_create_notebook
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = "nb-003"
        mock_get_factory.return_value = mock_factory

        result = nlm_create_notebook("Empty Sources NB", sources="")
        data = json.loads(result)
        assert data["notebook_id"] == "nb-003"
        mock_factory.get_or_create.assert_called_once()

    @patch("engine.nexus.nlm_notebook_factory.get_notebook_factory")
    def test_exception_returns_error_json(self, mock_get_factory):
        """Factory failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_create_notebook
        mock_get_factory.side_effect = RuntimeError("NLM engine not ready")

        result = nlm_create_notebook("Broken NB")
        data = json.loads(result)

        assert "error" in data
        assert "NLM engine not ready" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_add_codebase
# ═══════════════════════════════════════════════════════════════════

class TestNlmAddCodebase:
    """Tests for the nlm_add_codebase skill."""

    @patch(_ENGINE_PATH)
    def test_success_with_json_string_paths(self, mock_get_engine):
        """JSON string paths are parsed and forwarded to create_from_files."""
        from engine.skills.builtin.nlm_forge_skills import nlm_add_codebase
        mock_engine = MagicMock()
        mock_engine.create_from_files.return_value = {
            "notebook_id": "nb-code-001",
            "sources_added": 3,
        }
        mock_get_engine.return_value = mock_engine

        paths = json.dumps(["src/main.py", "src/utils.py", "src/config.py"])
        result = nlm_add_codebase("nb-abcdef12", paths)
        data = json.loads(result)

        assert data["notebook_id"] == "nb-code-001"
        assert data["sources_added"] == 3
        mock_engine.create_from_files.assert_called_once_with(
            ["src/main.py", "src/utils.py", "src/config.py"],
            "Codebase: nb-abcde",
        )

    @patch(_ENGINE_PATH)
    def test_success_with_list_paths(self, mock_get_engine):
        """List input is accepted directly without JSON parsing."""
        from engine.skills.builtin.nlm_forge_skills import nlm_add_codebase
        mock_engine = MagicMock()
        mock_engine.create_from_files.return_value = {"notebook_id": "nb-002"}
        mock_get_engine.return_value = mock_engine

        result = nlm_add_codebase("nb-12345678", ["a.py", "b.py"])
        data = json.loads(result)

        assert "error" not in data
        mock_engine.create_from_files.assert_called_once_with(
            ["a.py", "b.py"], "Codebase: nb-12345",
        )

    @patch(_ENGINE_PATH)
    def test_notebook_id_prefix_in_name(self, mock_get_engine):
        """The created notebook name uses first 8 chars of notebook_id."""
        from engine.skills.builtin.nlm_forge_skills import nlm_add_codebase
        mock_engine = MagicMock()
        mock_engine.create_from_files.return_value = {}
        mock_get_engine.return_value = mock_engine

        nlm_add_codebase("abcdefgh-rest-of-id", json.dumps(["x.py"]))
        call_args = mock_engine.create_from_files.call_args
        assert call_args[0][1] == "Codebase: abcdefgh"

    @patch(_ENGINE_PATH)
    def test_exception_returns_error_json(self, mock_get_engine):
        """Engine failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_add_codebase
        mock_get_engine.side_effect = OSError("file not found")

        result = nlm_add_codebase("nb-123", json.dumps(["bad.py"]))
        data = json.loads(result)

        assert "error" in data
        assert "file not found" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_generate_doc
# ═══════════════════════════════════════════════════════════════════

class TestNlmGenerateDoc:
    """Tests for the nlm_generate_doc skill."""

    @patch(_FORGE_PATH)
    def test_success_returns_document_json(self, mock_get_forge):
        """Successful generate_doc returns documents, success, duration."""
        from engine.skills.builtin.nlm_forge_skills import nlm_generate_doc
        mock_forge = MagicMock()
        mock_forge.generate_doc.return_value = _mock_forge_result(
            documents=["# Study Guide\n\nTopic overview..."],
        )
        mock_get_forge.return_value = mock_forge

        result = nlm_generate_doc("nb-123", doc_type="study_guide")
        data = json.loads(result)

        assert data["success"] is True
        assert len(data["documents"]) == 1
        assert "Study Guide" in data["documents"][0]
        assert data["errors"] == []
        assert data["duration_seconds"] == 1.5

    @patch(_FORGE_PATH)
    def test_default_doc_type(self, mock_get_forge):
        """Default doc_type is 'study_guide'."""
        from engine.skills.builtin.nlm_forge_skills import nlm_generate_doc
        mock_forge = MagicMock()
        mock_forge.generate_doc.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_generate_doc("nb-123")
        mock_forge.generate_doc.assert_called_once_with("nb-123", "study_guide", "")

    @patch(_FORGE_PATH)
    def test_custom_instructions_forwarded(self, mock_get_forge):
        """Custom instructions are passed to forge.generate_doc."""
        from engine.skills.builtin.nlm_forge_skills import nlm_generate_doc
        mock_forge = MagicMock()
        mock_forge.generate_doc.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_generate_doc("nb-123", doc_type="faq", instructions="Focus on errors")
        mock_forge.generate_doc.assert_called_once_with(
            "nb-123", "faq", "Focus on errors",
        )

    @patch(_FORGE_PATH)
    def test_failure_result_with_errors(self, mock_get_forge):
        """Forge returning success=False with errors is serialized."""
        from engine.skills.builtin.nlm_forge_skills import nlm_generate_doc
        mock_forge = MagicMock()
        mock_forge.generate_doc.return_value = _mock_forge_result(
            success=False, documents=[], errors=["Notebook not found"],
        )
        mock_get_forge.return_value = mock_forge

        result = nlm_generate_doc("nb-missing")
        data = json.loads(result)

        assert data["success"] is False
        assert "Notebook not found" in data["errors"]

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge exception returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_generate_doc
        mock_get_forge.side_effect = TimeoutError("NLM timed out")

        result = nlm_generate_doc("nb-123")
        data = json.loads(result)

        assert "error" in data
        assert "NLM timed out" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_distill
# ═══════════════════════════════════════════════════════════════════

class TestNlmDistill:
    """Tests for the nlm_distill skill."""

    @patch(_FORGE_PATH)
    def test_success_with_topic(self, mock_get_forge):
        """Distill with topic returns qa_pairs and nexus_ids."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        mock_forge = MagicMock()
        mock_forge.distill.return_value = _mock_forge_result(
            nexus_ids=["nex-d01", "nex-d02"],
        )
        mock_get_forge.return_value = mock_forge

        result = nlm_distill("nb-123", topic="MCP state")
        data = json.loads(result)

        assert data["success"] is True
        assert data["qa_count"] == 1
        assert len(data["qa_pairs"]) == 1
        assert data["qa_pairs"][0]["question"] == "How does X work?"
        assert data["nexus_ids"] == ["nex-d01", "nex-d02"]
        mock_forge.distill.assert_called_once_with(
            "nb-123", topics=["MCP state"], count=20,
        )

    @patch(_FORGE_PATH)
    def test_empty_topic_passes_none(self, mock_get_forge):
        """Empty topic string sends topics=None to forge."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        mock_forge = MagicMock()
        mock_forge.distill.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_distill("nb-123", topic="")
        mock_forge.distill.assert_called_once_with(
            "nb-123", topics=None, count=20,
        )

    @patch(_FORGE_PATH)
    def test_custom_count(self, mock_get_forge):
        """Custom count is forwarded to forge.distill."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        mock_forge = MagicMock()
        mock_forge.distill.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_distill("nb-123", topic="test", count=50)
        mock_forge.distill.assert_called_once_with(
            "nb-123", topics=["test"], count=50,
        )

    @patch(_FORGE_PATH)
    def test_multiple_qa_pairs(self, mock_get_forge):
        """Multiple qa_pairs each get to_dict() serialized."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        pair1 = MagicMock()
        pair1.to_dict.return_value = {"question": "Q1", "answer": "A1"}
        pair2 = MagicMock()
        pair2.to_dict.return_value = {"question": "Q2", "answer": "A2"}
        mock_forge = MagicMock()
        mock_forge.distill.return_value = _mock_forge_result(qa_pairs=[pair1, pair2])
        mock_get_forge.return_value = mock_forge

        result = nlm_distill("nb-123")
        data = json.loads(result)

        assert data["qa_count"] == 2
        assert data["qa_pairs"][0]["question"] == "Q1"
        assert data["qa_pairs"][1]["question"] == "Q2"

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        mock_get_forge.side_effect = RuntimeError("distill failed")

        result = nlm_distill("nb-123")
        data = json.loads(result)

        assert "error" in data
        assert "distill failed" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_decompose
# ═══════════════════════════════════════════════════════════════════

class TestNlmDecompose:
    """Tests for the nlm_decompose skill."""

    @patch(_FORGE_PATH)
    def test_success_returns_steps(self, mock_get_forge):
        """Successful decompose returns steps with step_count."""
        from engine.skills.builtin.nlm_forge_skills import nlm_decompose
        steps = [
            {"step": 1, "file": "a.py", "change": "Add import"},
            {"step": 2, "file": "b.py", "change": "Update function"},
        ]
        mock_forge = MagicMock()
        mock_forge.decompose.return_value = _mock_forge_result(steps=steps)
        mock_get_forge.return_value = mock_forge

        result = nlm_decompose("Refactor the auth module")
        data = json.loads(result)

        assert data["success"] is True
        assert data["step_count"] == 2
        assert len(data["steps"]) == 2
        assert data["steps"][0]["file"] == "a.py"
        assert data["duration_seconds"] == 1.5

    @patch(_FORGE_PATH)
    def test_default_arguments(self, mock_get_forge):
        """Default notebook_id and model_size are forwarded."""
        from engine.skills.builtin.nlm_forge_skills import nlm_decompose
        mock_forge = MagicMock()
        mock_forge.decompose.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_decompose("Add logging")
        mock_forge.decompose.assert_called_once_with(
            "Add logging", notebook_id="", model_size="9b",
        )

    @patch(_FORGE_PATH)
    def test_custom_model_size(self, mock_get_forge):
        """Custom model_size is forwarded to forge.decompose."""
        from engine.skills.builtin.nlm_forge_skills import nlm_decompose
        mock_forge = MagicMock()
        mock_forge.decompose.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_decompose("Plan X", notebook_id="nb-ctx", model_size="3b")
        mock_forge.decompose.assert_called_once_with(
            "Plan X", notebook_id="nb-ctx", model_size="3b",
        )

    @patch(_FORGE_PATH)
    def test_empty_steps(self, mock_get_forge):
        """No steps produces step_count of 0."""
        from engine.skills.builtin.nlm_forge_skills import nlm_decompose
        mock_forge = MagicMock()
        mock_forge.decompose.return_value = _mock_forge_result(steps=[])
        mock_get_forge.return_value = mock_forge

        result = nlm_decompose("trivial task")
        data = json.loads(result)

        assert data["step_count"] == 0
        assert data["steps"] == []

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_decompose
        mock_get_forge.side_effect = RuntimeError("decompose crashed")

        result = nlm_decompose("bad plan")
        data = json.loads(result)

        assert "error" in data
        assert "decompose crashed" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_analyze
# ═══════════════════════════════════════════════════════════════════

class TestNlmAnalyze:
    """Tests for the nlm_analyze skill."""

    @patch(_FORGE_PATH)
    def test_success_with_json_string_files(self, mock_get_forge):
        """JSON string file paths are parsed and analyzed."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        mock_forge = MagicMock()
        mock_forge.analyze.return_value = _mock_forge_result(
            notebook_id="nb-analysis-01",
        )
        mock_get_forge.return_value = mock_forge

        result = nlm_analyze(json.dumps(["engine/main.py", "engine/config.py"]))
        data = json.loads(result)

        assert data["success"] is True
        assert data["notebook_id"] == "nb-analysis-01"
        assert len(data["insights"]) == 1
        assert data["insights"][0]["question"] == "How does X work?"
        mock_forge.analyze.assert_called_once_with(
            ["engine/main.py", "engine/config.py"], questions=None,
        )

    @patch(_FORGE_PATH)
    def test_success_with_list_files(self, mock_get_forge):
        """List input is accepted directly."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        mock_forge = MagicMock()
        mock_forge.analyze.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        result = nlm_analyze(["a.py", "b.py"])
        data = json.loads(result)

        assert "error" not in data
        mock_forge.analyze.assert_called_once_with(
            ["a.py", "b.py"], questions=None,
        )

    @patch(_FORGE_PATH)
    def test_with_custom_questions(self, mock_get_forge):
        """Custom questions JSON array is forwarded to forge.analyze."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        mock_forge = MagicMock()
        mock_forge.analyze.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        questions = json.dumps(["What patterns are used?", "Any bugs?"])
        nlm_analyze(json.dumps(["x.py"]), questions=questions)
        mock_forge.analyze.assert_called_once_with(
            ["x.py"], questions=["What patterns are used?", "Any bugs?"],
        )

    @patch(_FORGE_PATH)
    def test_empty_questions_passes_none(self, mock_get_forge):
        """Empty questions string passes None to forge."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        mock_forge = MagicMock()
        mock_forge.analyze.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_analyze(json.dumps(["x.py"]), questions="")
        mock_forge.analyze.assert_called_once_with(["x.py"], questions=None)

    @patch(_FORGE_PATH)
    def test_insights_use_to_dict(self, mock_get_forge):
        """Each qa_pair.to_dict() is called and serialized as insights."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        pair = MagicMock()
        pair.to_dict.return_value = {"question": "Design?", "answer": "MVC pattern"}
        mock_forge = MagicMock()
        mock_forge.analyze.return_value = _mock_forge_result(qa_pairs=[pair])
        mock_get_forge.return_value = mock_forge

        result = nlm_analyze(json.dumps(["x.py"]))
        data = json.loads(result)

        assert data["insights"][0]["answer"] == "MVC pattern"
        pair.to_dict.assert_called_once()

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_analyze
        mock_get_forge.side_effect = FileNotFoundError("no such file")

        result = nlm_analyze(json.dumps(["missing.py"]))
        data = json.loads(result)

        assert "error" in data
        assert "no such file" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_solve
# ═══════════════════════════════════════════════════════════════════

class TestNlmSolve:
    """Tests for the nlm_solve skill."""

    @patch(_FORGE_PATH)
    def test_success_returns_solution(self, mock_get_forge):
        """Successful solve returns solution dict."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        pair = MagicMock()
        pair.to_dict.return_value = {
            "question": "How to fix the auth bug?",
            "answer": "Check token expiry logic in middleware.",
        }
        mock_forge = MagicMock()
        mock_forge.solve.return_value = _mock_forge_result(qa_pairs=[pair])
        mock_get_forge.return_value = mock_forge

        result = nlm_solve("How to fix the auth bug?")
        data = json.loads(result)

        assert data["success"] is True
        assert data["solution"]["answer"] == "Check token expiry logic in middleware."
        assert data["errors"] == []
        assert data["duration_seconds"] == 1.5

    @patch(_FORGE_PATH)
    def test_no_qa_pairs_returns_none_solution(self, mock_get_forge):
        """Empty qa_pairs returns solution=None."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        mock_forge = MagicMock()
        mock_forge.solve.return_value = _mock_forge_result(qa_pairs=[])
        mock_get_forge.return_value = mock_forge

        result = nlm_solve("unanswerable question")
        data = json.loads(result)

        assert data["solution"] is None

    @patch(_FORGE_PATH)
    def test_with_context_files(self, mock_get_forge):
        """Context JSON array is forwarded to forge.solve."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        mock_forge = MagicMock()
        mock_forge.solve.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        context = json.dumps(["auth.py", "middleware.py"])
        nlm_solve("Fix auth", context=context)
        mock_forge.solve.assert_called_once_with(
            "Fix auth",
            context_files=["auth.py", "middleware.py"],
            notebook_id="",
        )

    @patch(_FORGE_PATH)
    def test_empty_context_passes_none(self, mock_get_forge):
        """Empty context string passes context_files=None."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        mock_forge = MagicMock()
        mock_forge.solve.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_solve("question", context="")
        mock_forge.solve.assert_called_once_with(
            "question", context_files=None, notebook_id="",
        )

    @patch(_FORGE_PATH)
    def test_with_notebook_id(self, mock_get_forge):
        """notebook_id is forwarded to forge.solve."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        mock_forge = MagicMock()
        mock_forge.solve.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_solve("question", notebook_id="nb-ctx-999")
        mock_forge.solve.assert_called_once_with(
            "question", context_files=None, notebook_id="nb-ctx-999",
        )

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_solve
        mock_get_forge.side_effect = RuntimeError("solver exploded")

        result = nlm_solve("kaboom")
        data = json.loads(result)

        assert "error" in data
        assert "solver exploded" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# nlm_build_topic
# ═══════════════════════════════════════════════════════════════════

class TestNlmBuildTopic:
    """Tests for the nlm_build_topic skill."""

    @patch(_FORGE_PATH)
    def test_success_returns_topic_data(self, mock_get_forge):
        """Successful build_topic returns notebook_id, qa_count, nexus_ids."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        mock_forge = MagicMock()
        mock_forge.build_topic.return_value = _mock_forge_result(
            notebook_id="nb-topic-01",
            nexus_ids=["nex-t01", "nex-t02", "nex-t03"],
        )
        mock_get_forge.return_value = mock_forge

        result = nlm_build_topic("MCP Architecture")
        data = json.loads(result)

        assert data["success"] is True
        assert data["notebook_id"] == "nb-topic-01"
        assert data["qa_count"] == 1
        assert len(data["nexus_ids"]) == 3
        assert data["errors"] == []
        assert data["duration_seconds"] == 1.5

    @patch(_FORGE_PATH)
    def test_default_arguments(self, mock_get_forge):
        """Default sources=None and question_count=30."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        mock_forge = MagicMock()
        mock_forge.build_topic.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_build_topic("Interceptors")
        mock_forge.build_topic.assert_called_once_with(
            "Interceptors", sources=None, question_count=30,
        )

    @patch(_FORGE_PATH)
    def test_with_sources_and_custom_count(self, mock_get_forge):
        """Sources JSON array and custom question_count are forwarded."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        mock_forge = MagicMock()
        mock_forge.build_topic.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        sources = json.dumps(["https://docs.example.com/mcp"])
        nlm_build_topic("MCP", sources=sources, question_count=10)
        mock_forge.build_topic.assert_called_once_with(
            "MCP",
            sources=["https://docs.example.com/mcp"],
            question_count=10,
        )

    @patch(_FORGE_PATH)
    def test_empty_sources_passes_none(self, mock_get_forge):
        """Empty sources string passes None."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        mock_forge = MagicMock()
        mock_forge.build_topic.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_build_topic("Topic", sources="")
        mock_forge.build_topic.assert_called_once_with(
            "Topic", sources=None, question_count=30,
        )

    @patch(_FORGE_PATH)
    def test_qa_count_matches_qa_pairs_length(self, mock_get_forge):
        """qa_count reflects actual number of qa_pairs."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        pairs = []
        for i in range(5):
            p = MagicMock()
            p.to_dict.return_value = {"q": f"Q{i}", "a": f"A{i}"}
            pairs.append(p)
        mock_forge = MagicMock()
        mock_forge.build_topic.return_value = _mock_forge_result(qa_pairs=pairs)
        mock_get_forge.return_value = mock_forge

        result = nlm_build_topic("Big Topic")
        data = json.loads(result)

        assert data["qa_count"] == 5

    @patch(_FORGE_PATH)
    def test_exception_returns_error_json(self, mock_get_forge):
        """Forge failure returns JSON error."""
        from engine.skills.builtin.nlm_forge_skills import nlm_build_topic
        mock_get_forge.side_effect = RuntimeError("topic build failed")

        result = nlm_build_topic("broken topic")
        data = json.loads(result)

        assert "error" in data
        assert "topic build failed" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# CROSS-CUTTING CONCERNS
# ═══════════════════════════════════════════════════════════════════

class TestJsonSerialization:
    """Verify all skills return valid JSON and handle unicode."""

    @patch(_ROUTER_PATH)
    def test_nlm_ask_returns_valid_json(self, mock_get_router):
        """Return value is always parseable JSON."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        result = nlm_ask("test")
        assert isinstance(result, str)
        json.loads(result)  # should not raise

    @patch(_ROUTER_PATH)
    def test_nlm_ask_unicode_preserved(self, mock_get_router):
        """Unicode characters are preserved (ensure_ascii=False)."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result(
            answer="日本語の回答です — CosySim™",
        )
        mock_get_router.return_value = mock_router

        result = nlm_ask("日本語の質問")
        data = json.loads(result)

        assert "日本語の回答です" in data["answer"]
        assert "™" in data["answer"]

    @patch(_ROUTER_PATH)
    def test_error_json_is_valid(self, mock_get_router):
        """Even error responses are valid JSON."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_get_router.side_effect = Exception("fail")

        result = nlm_ask("test")
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "error" in data


class TestLazyLoading:
    """Verify lazy-load helpers are called correctly."""

    @patch(_ROUTER_PATH)
    def test_get_router_called_on_ask(self, mock_get_router):
        """_get_router() is invoked when nlm_ask is called."""
        from engine.skills.builtin.nlm_forge_skills import nlm_ask
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_route_result()
        mock_get_router.return_value = mock_router

        nlm_ask("test")
        mock_get_router.assert_called_once()

    @patch("engine.nexus.nlm_notebook_factory.get_notebook_factory")
    def test_get_factory_called_on_create_notebook(self, mock_get_factory):
        """get_notebook_factory() is invoked when nlm_create_notebook is called."""
        from engine.skills.builtin.nlm_forge_skills import nlm_create_notebook
        mock_factory = MagicMock()
        mock_factory.get_or_create.return_value = "nb-1"
        mock_get_factory.return_value = mock_factory

        nlm_create_notebook("Test")
        mock_get_factory.assert_called_once()

    @patch(_FORGE_PATH)
    def test_get_forge_called_on_distill(self, mock_get_forge):
        """_get_forge() is invoked when nlm_distill is called."""
        from engine.skills.builtin.nlm_forge_skills import nlm_distill
        mock_forge = MagicMock()
        mock_forge.distill.return_value = _mock_forge_result()
        mock_get_forge.return_value = mock_forge

        nlm_distill("nb-123")
        mock_get_forge.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# NLM MEDIA SKILLS — audio, video, data_tables, chat_history
# ═══════════════════════════════════════════════════════════════════

_HYBRID_PATH = "engine.mcp.nlm_hybrid.get_nlm_hybrid"
_NODE_BRIDGE_PATH = "engine.mcp.nlm_node_bridge.get_nlm_node_bridge"


class TestNlmAudio:
    @patch(_HYBRID_PATH)
    def test_nlm_audio_returns_result(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_audio
        mock_hybrid = MagicMock()
        mock_hybrid.generate_audio.return_value = {"status": "generated", "audio_url": "https://nlm.example/audio.mp3"}
        mock_get_hybrid.return_value = mock_hybrid

        raw = nlm_audio("nb-abc")
        result = json.loads(raw)
        assert result["status"] == "generated"
        mock_hybrid.generate_audio.assert_called_once_with("nb-abc", style="standard")

    @patch(_HYBRID_PATH)
    def test_nlm_audio_custom_style(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_audio
        mock_hybrid = MagicMock()
        mock_hybrid.generate_audio.return_value = {"status": "ok"}
        mock_get_hybrid.return_value = mock_hybrid

        nlm_audio("nb-abc", style="deep_dive")
        mock_hybrid.generate_audio.assert_called_once_with("nb-abc", style="deep_dive")

    @patch(_HYBRID_PATH)
    def test_nlm_audio_handles_exception(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_audio
        mock_get_hybrid.side_effect = RuntimeError("hybrid offline")

        raw = nlm_audio("nb-abc")
        result = json.loads(raw)
        assert "error" in result
        assert "hybrid offline" in result["error"]


class TestNlmVideo:
    @patch(_HYBRID_PATH)
    def test_nlm_video_returns_result(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_video
        mock_hybrid = MagicMock()
        mock_hybrid.generate_video.return_value = {"status": "queued", "video_id": "vid-123"}
        mock_get_hybrid.return_value = mock_hybrid

        raw = nlm_video("nb-abc")
        result = json.loads(raw)
        assert result["video_id"] == "vid-123"
        mock_hybrid.generate_video.assert_called_once_with("nb-abc", style="cinematic")

    @patch(_HYBRID_PATH)
    def test_nlm_video_custom_style(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_video
        mock_hybrid = MagicMock()
        mock_hybrid.generate_video.return_value = {"status": "ok"}
        mock_get_hybrid.return_value = mock_hybrid

        nlm_video("nb-abc", style="tutorial")
        mock_hybrid.generate_video.assert_called_once_with("nb-abc", style="tutorial")

    @patch(_HYBRID_PATH)
    def test_nlm_video_error_propagated(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_video
        mock_get_hybrid.side_effect = ConnectionError("node bridge down")

        raw = nlm_video("nb-abc")
        result = json.loads(raw)
        assert "error" in result


class TestNlmDataTables:
    @patch(_HYBRID_PATH)
    def test_nlm_data_tables_returns_tables(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_data_tables
        mock_hybrid = MagicMock()
        mock_hybrid.extract_tables.return_value = {"tables": [{"headers": ["A", "B"], "rows": [["1", "2"]]}]}
        mock_get_hybrid.return_value = mock_hybrid

        raw = nlm_data_tables("nb-abc")
        result = json.loads(raw)
        assert "tables" in result
        assert len(result["tables"]) == 1
        mock_hybrid.extract_tables.assert_called_once_with("nb-abc", query="")

    @patch(_HYBRID_PATH)
    def test_nlm_data_tables_passes_query(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_data_tables
        mock_hybrid = MagicMock()
        mock_hybrid.extract_tables.return_value = {"tables": []}
        mock_get_hybrid.return_value = mock_hybrid

        nlm_data_tables("nb-abc", query="performance benchmarks")
        mock_hybrid.extract_tables.assert_called_once_with("nb-abc", query="performance benchmarks")

    @patch(_HYBRID_PATH)
    def test_nlm_data_tables_error_json(self, mock_get_hybrid):
        from engine.skills.builtin.nlm_forge_skills import nlm_data_tables
        mock_get_hybrid.side_effect = Exception("tables unavailable")

        raw = nlm_data_tables("nb-abc")
        result = json.loads(raw)
        assert "error" in result


class TestNlmChatHistory:
    @patch(_NODE_BRIDGE_PATH)
    def test_nlm_chat_history_returns_list(self, mock_get_bridge):
        from engine.skills.builtin.nlm_forge_skills import nlm_chat_history
        mock_bridge = MagicMock()
        mock_bridge.get_chat_history.return_value = [
            {"question": "Q1?", "answer": "A1"},
            {"question": "Q2?", "answer": "A2"},
        ]
        mock_get_bridge.return_value = mock_bridge

        raw = nlm_chat_history("nb-abc")
        result = json.loads(raw)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["question"] == "Q1?"
        mock_bridge.get_chat_history.assert_called_once_with("nb-abc")

    @patch(_NODE_BRIDGE_PATH)
    def test_nlm_chat_history_empty(self, mock_get_bridge):
        from engine.skills.builtin.nlm_forge_skills import nlm_chat_history
        mock_bridge = MagicMock()
        mock_bridge.get_chat_history.return_value = []
        mock_get_bridge.return_value = mock_bridge

        raw = nlm_chat_history("nb-abc")
        result = json.loads(raw)
        assert result == []

    @patch(_NODE_BRIDGE_PATH)
    def test_nlm_chat_history_error_propagated(self, mock_get_bridge):
        from engine.skills.builtin.nlm_forge_skills import nlm_chat_history
        mock_get_bridge.side_effect = RuntimeError("node bridge error")

        raw = nlm_chat_history("nb-abc")
        result = json.loads(raw)
        assert "error" in result
        assert "node bridge error" in result["error"]
