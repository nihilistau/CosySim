"""Tests for NLM chain-prompting engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.nlm_chain import (
    ChainResult,
    ChainStep,
    NLMChainEngine,
    NotebookSpec,
    get_all_notebook_specs,
    get_batch_config,
    get_chain_config,
    get_chain_engine,
    get_fleet_defaults,
    get_notebook_spec,
    reset_chain_engine,
    reset_fleet_config,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset singletons between tests."""
    reset_fleet_config()
    reset_chain_engine()
    yield
    reset_fleet_config()
    reset_chain_engine()


# ──── Config Loading ──────────────────────────────────────────

class TestFleetConfig:
    """Test fleet configuration loading from YAML."""

    def test_load_defaults(self):
        defaults = get_fleet_defaults()
        assert isinstance(defaults, dict)
        assert "tier_marker" in defaults
        assert defaults["tier_marker"] == 2

    def test_get_notebook_spec_control(self):
        spec = get_notebook_spec("control")
        assert spec is not None
        assert spec.key == "control"
        assert spec.name == "copilot-system-control"
        assert spec.purpose
        assert len(spec.distillation_questions) >= 4

    def test_get_notebook_spec_coding(self):
        spec = get_notebook_spec("coding")
        assert spec is not None
        assert spec.key == "coding"
        assert "coding" in spec.name.lower() or "pattern" in spec.name.lower()

    def test_get_notebook_spec_nonexistent(self):
        spec = get_notebook_spec("nonexistent_notebook")
        assert spec is None

    def test_get_all_notebook_specs(self):
        specs = get_all_notebook_specs()
        assert len(specs) >= 7
        keys = {s.key for s in specs}
        assert "control" in keys
        assert "documentation" in keys
        assert "rules" in keys
        assert "coding" in keys
        assert "planning" in keys
        assert "training" in keys
        assert "news" in keys

    def test_get_chain_config(self):
        chain = get_chain_config("double_prompt")
        assert chain is not None
        assert "steps" in chain
        assert len(chain["steps"]) >= 2

    def test_get_chain_config_research(self):
        chain = get_chain_config("research_deep")
        assert chain is not None
        assert len(chain["steps"]) >= 3

    def test_get_chain_config_nonexistent(self):
        chain = get_chain_config("nonexistent_chain")
        assert chain is None

    def test_get_batch_config(self):
        batch = get_batch_config("daily_refresh")
        assert batch is not None
        assert "notebooks" in batch
        assert len(batch["notebooks"]) >= 2

    def test_get_batch_config_weekly(self):
        batch = get_batch_config("weekly_deep")
        assert batch is not None
        assert "chain" in batch

    def test_notebook_spec_has_url_for_control(self):
        spec = get_notebook_spec("control")
        assert spec is not None
        assert spec.url is not None
        assert "notebooklm.google.com" in spec.url

    def test_notebook_spec_refresh_intervals(self):
        control = get_notebook_spec("control")
        news = get_notebook_spec("news")
        assert control is not None
        assert news is not None
        assert news.refresh_interval_hours < control.refresh_interval_hours


# ──── Data Classes ────────────────────────────────────────────

class TestDataClasses:
    """Test chain result data classes."""

    def test_chain_step_defaults(self):
        step = ChainStep(name="test", prompt_template="prompt")
        assert step.result is None
        assert step.elapsed_ms == 0.0
        assert step.output_as_source is False

    def test_chain_result_defaults(self):
        result = ChainResult(chain_name="test")
        assert result.success is False
        assert result.error is None
        assert result.steps == []
        assert result.artifacts == []

    def test_chain_result_to_dict(self):
        result = ChainResult(
            chain_name="test",
            notebook_id="nb123",
            steps=[ChainStep(name="s1", prompt_template="p1", result="answer", elapsed_ms=100)],
            total_elapsed_ms=150,
            success=True,
        )
        d = result.to_dict()
        assert d["chain_name"] == "test"
        assert d["notebook_id"] == "nb123"
        assert d["success"] is True
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "s1"
        assert d["steps"][0]["result_length"] == 6

    def test_notebook_spec(self):
        spec = NotebookSpec(
            key="test",
            name="Test Notebook",
            purpose="Testing",
            url="https://notebooklm.google.com/notebook/abc123",
        )
        assert spec.key == "test"
        assert spec.refresh_interval_hours == 168


# ──── Chain Engine ────────────────────────────────────────────

class TestChainEngine:
    """Test the NLM chain-prompting engine."""

    def _make_engine(self, ask_responses=None):
        """Create engine with mocked clients."""
        nlm_client = MagicMock()
        nexus_client = MagicMock()

        if ask_responses:
            nlm_client.ask_notebook.side_effect = ask_responses
        else:
            nlm_client.ask_notebook.return_value = {"answer": "Test answer"}

        nexus_client.add_entry.return_value = {"id": "entry123"}
        nexus_client.add_qa.return_value = {"id": "qa123"}

        return NLMChainEngine(nlm_client=nlm_client, nexus_client=nexus_client)

    def test_execute_chain_success(self):
        engine = self._make_engine(ask_responses=[
            {"answer": "Step 1 result with enough content to store"},
            {"answer": "Step 2 refined result with enough content to store"},
        ])
        result = engine.execute_chain(
            chain_name="double_prompt",
            notebook_id="nb123",
            variables={"artifact_type": "plan", "topic": "testing"},
            store_results=False,
        )
        assert result.success is True
        assert len(result.steps) == 2
        assert result.steps[0].result == "Step 1 result with enough content to store"

    def test_execute_chain_unknown(self):
        engine = self._make_engine()
        result = engine.execute_chain(
            chain_name="nonexistent",
            notebook_id="nb123",
        )
        assert result.success is False
        assert "not found" in result.error

    def test_execute_chain_stores_in_nexus(self):
        engine = self._make_engine(ask_responses=[
            {"answer": "Overview of the topic with substantial content for storage"},
            {"answer": "Detailed implementation notes with code examples and patterns"},
            {"answer": "Production-ready code examples following our conventions properly"},
            {"answer": "Missing areas and potential pitfalls to watch out for in production"},
        ])
        result = engine.execute_chain(
            chain_name="research_deep",
            notebook_id="nb123",
            variables={"topic": "MCP skills"},
            store_results=True,
        )
        assert result.success is True
        assert engine._nexus_client.add_entry.called
        assert engine._nexus_client.add_qa.called

    def test_execute_chain_handles_error(self):
        engine = self._make_engine()
        engine._nlm_client.ask_notebook.side_effect = Exception("NLM down")
        result = engine.execute_chain(
            chain_name="double_prompt",
            notebook_id="nb123",
            variables={"artifact_type": "plan", "topic": "test"},
            store_results=False,
        )
        assert result.success is False
        assert any("[ERROR" in (s.result or "") for s in result.steps)

    def test_distill_notebook(self):
        engine = self._make_engine(ask_responses=[
            {"answer": f"Answer {i}"} for i in range(6)
        ])
        results = engine.distill_notebook(
            notebook_key="control",
            store_results=True,
        )
        assert len(results) >= 4
        assert all(r["answer"].startswith("Answer") for r in results)
        assert engine._nexus_client.add_qa.called

    def test_distill_notebook_no_spec(self):
        engine = self._make_engine()
        results = engine.distill_notebook(notebook_key="nonexistent")
        assert results == []

    def test_distill_notebook_custom_questions(self):
        engine = self._make_engine(ask_responses=[
            {"answer": "Custom answer 1"},
            {"answer": "Custom answer 2"},
        ])
        results = engine.distill_notebook(
            notebook_key="control",
            questions=["Q1?", "Q2?"],
            store_results=False,
        )
        assert len(results) == 2
        assert results[0]["question"] == "Q1?"

    def test_run_batch(self):
        engine = self._make_engine(ask_responses=[
            {"answer": f"A{i}"} for i in range(30)
        ])
        result = engine.run_batch("daily_refresh")
        assert "batch_name" in result
        assert result["notebooks_processed"] >= 2

    def test_run_batch_unknown(self):
        engine = self._make_engine()
        result = engine.run_batch("nonexistent_batch")
        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("engine.nexus.nlm_chain.get_notebook_spec")
    def test_generate_action_manifest(self, mock_spec):
        mock_spec.return_value = NotebookSpec(
            key="planning", name="planning", purpose="p",
            url="https://notebooklm.google.com/notebook/plan123",
        )
        manifest_json = json.dumps({
            "milestones": [{"name": "M1", "steps": [{"title": "Step 1"}]}],
        })
        engine = self._make_engine(ask_responses=[
            {"answer": "Task analysis: requires 3 steps"},
            {"answer": "Decomposed steps: 1. do X, 2. do Y, 3. do Z"},
            {"answer": manifest_json},
        ])
        manifest = engine.generate_action_manifest(
            task_description="Build a new MCP skill",
            store_result=False,
        )
        assert manifest is not None
        assert "milestones" in manifest

    @patch("engine.nexus.nlm_chain.get_notebook_spec")
    def test_generate_action_manifest_unparseable(self, mock_spec):
        mock_spec.return_value = NotebookSpec(
            key="planning", name="planning", purpose="p",
            url="https://notebooklm.google.com/notebook/plan123",
        )
        engine = self._make_engine(ask_responses=[
            {"answer": "Analysis"},
            {"answer": "Steps"},
            {"answer": "Not valid JSON but useful text"},
        ])
        manifest = engine.generate_action_manifest(
            task_description="Test task",
            store_result=False,
        )
        assert manifest is not None
        assert manifest.get("parsed") is False
        assert "raw_output" in manifest


# ──── Singleton ───────────────────────────────────────────────

class TestSingleton:
    """Test singleton management."""

    def test_get_chain_engine_returns_same_instance(self):
        e1 = get_chain_engine()
        e2 = get_chain_engine()
        assert e1 is e2

    def test_reset_chain_engine(self):
        e1 = get_chain_engine()
        reset_chain_engine()
        e2 = get_chain_engine()
        assert e1 is not e2


# ──── Integration Patterns ────────────────────────────────────

class TestIntegrationPatterns:
    """Test patterns that chain engine exposes for system integration."""

    def test_chain_with_variable_substitution(self):
        engine = self._make_engine(ask_responses=[
            {"answer": "Artifact about MCP patterns"},
            {"answer": "Refined tasks for MCP patterns"},
        ])
        result = engine.execute_chain(
            chain_name="double_prompt",
            notebook_id="nb123",
            variables={"artifact_type": "code_review", "topic": "MCP patterns"},
            store_results=False,
        )
        assert result.success is True

    @staticmethod
    def _make_engine(ask_responses=None):
        nlm_client = MagicMock()
        nexus_client = MagicMock()
        if ask_responses:
            nlm_client.ask_notebook.side_effect = ask_responses
        else:
            nlm_client.ask_notebook.return_value = {"answer": "Test answer"}
        nexus_client.add_entry.return_value = {"id": "entry123"}
        nexus_client.add_qa.return_value = {"id": "qa123"}
        return NLMChainEngine(nlm_client=nlm_client, nexus_client=nexus_client)

    def test_all_configured_chains_have_steps(self):
        for chain_name in ["double_prompt", "research_deep", "knowledge_distill",
                           "task_decompose", "code_review"]:
            chain = get_chain_config(chain_name)
            assert chain is not None, f"Chain '{chain_name}' missing"
            assert len(chain.get("steps", [])) >= 2, f"Chain '{chain_name}' has <2 steps"

    def test_all_configured_batches_reference_valid_notebooks(self):
        for batch_name in ["full_distillation", "daily_refresh", "weekly_deep"]:
            batch = get_batch_config(batch_name)
            assert batch is not None, f"Batch '{batch_name}' missing"
            for nb_key in batch.get("notebooks", []):
                spec = get_notebook_spec(nb_key)
                assert spec is not None, f"Batch '{batch_name}' references unknown notebook '{nb_key}'"
