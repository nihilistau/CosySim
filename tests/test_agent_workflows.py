"""Tests for agent workflow orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.workflows.agent_workflows import (
    WorkflowResult,
    knowledge_distill,
    dataset_curate,
    metrics_extract,
    quality_audit,
    research_pipeline,
    run_all,
    WORKFLOWS,
    _extract_test_metrics,
    _extract_codebase_metrics,
    _extract_training_metrics,
)


# ── WorkflowResult ───────────────────────────────────────────────

class TestWorkflowResult:
    def test_to_dict(self):
        r = WorkflowResult(workflow="test", status="success", items_processed=10)
        d = r.to_dict()
        assert d["workflow"] == "test"
        assert d["status"] == "success"
        assert d["items_processed"] == 10

    def test_summary_success(self):
        r = WorkflowResult(workflow="test", status="success")
        assert "✅" in r.summary()

    def test_summary_failed(self):
        r = WorkflowResult(workflow="test", status="failed", errors=["boom"])
        s = r.summary()
        assert "❌" in s
        assert "boom" in s

    def test_default_status(self):
        r = WorkflowResult(workflow="test")
        assert r.status == "pending"


# ── Metrics Extraction ───────────────────────────────────────────

class TestMetricsExtract:
    def test_extracts_test_metrics(self):
        m = _extract_test_metrics()
        assert "test_files" in m
        assert m["test_files"] > 0
        assert m["total_tests"] > 100

    def test_extracts_codebase_metrics(self):
        m = _extract_codebase_metrics()
        assert m["total_files"] > 0
        assert m["total_lines"] > 0
        assert "engine" in m["by_directory"]

    def test_extracts_training_metrics(self):
        m = _extract_training_metrics()
        assert "datasets" in m
        assert m["total_examples"] > 0

    def test_full_workflow(self, tmp_path):
        out = str(tmp_path / "metrics.json")
        r = metrics_extract(scope="all", output_path=out)
        assert r.status == "success"
        assert Path(out).exists()
        data = json.loads(Path(out).read_text())
        assert "tests" in data
        assert "codebase" in data

    def test_scoped_tests_only(self, tmp_path):
        out = str(tmp_path / "test_metrics.json")
        r = metrics_extract(scope="tests", output_path=out)
        assert r.status == "success"
        data = json.loads(Path(out).read_text())
        assert "tests" in data
        assert "codebase" not in data


# ── Quality Audit ────────────────────────────────────────────────

class TestQualityAudit:
    def test_full_audit(self, tmp_path):
        out = str(tmp_path / "audit.json")
        r = quality_audit(scope="all", output_path=out)
        assert r.status == "success"
        data = json.loads(Path(out).read_text())
        assert data["functions"]["total"] > 100
        assert 0 <= data["functions"]["docstring_coverage"] <= 100

    def test_engine_only(self, tmp_path):
        out = str(tmp_path / "engine_audit.json")
        r = quality_audit(scope="engine", output_path=out)
        assert r.status == "success"
        assert r.items_processed > 0

    def test_antipatterns_detected(self, tmp_path):
        out = str(tmp_path / "audit.json")
        r = quality_audit(scope="all", output_path=out)
        data = json.loads(Path(out).read_text())
        assert "antipattern_count" in data


# ── Knowledge Distill (mocked Nexus) ─────────────────────────────

class TestKnowledgeDistill:
    def test_with_mocked_nexus(self, tmp_path):
        mock_qa = [
            {"question": "What is MCP?", "answer": "Model Context Protocol framework.", "category": "architecture"},
            {"question": "How do skills work?", "answer": "Skills are decorated functions registered as tools.", "category": "api"},
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = mock_qa

        out = str(tmp_path / "distilled.jsonl")
        with patch("requests.get", return_value=mock_resp):
            r = knowledge_distill(output_path=out, nexus_url="http://fake:8700")

        assert r.status == "success"
        assert r.items_output == 2
        lines = Path(out).read_text().strip().split("\n")
        assert len(lines) == 2

    def test_with_topic_filter(self, tmp_path):
        mock_qa_resp = MagicMock()
        mock_qa_resp.ok = True
        mock_qa_resp.json.return_value = []

        mock_search_resp = MagicMock()
        mock_search_resp.ok = True
        mock_search_resp.json.return_value = {
            "results": [
                {"title": "Interceptor Pipeline", "content": "The interceptor pipeline processes requests through hooks. " * 3, "category": "architecture"},
            ]
        }

        out = str(tmp_path / "distilled.jsonl")
        with patch("requests.get", side_effect=[mock_qa_resp, mock_search_resp]):
            r = knowledge_distill(topic="interceptor", output_path=out)

        assert r.status == "success"
        assert r.items_output >= 1

    def test_nexus_unreachable(self, tmp_path):
        out = str(tmp_path / "distilled.jsonl")
        with patch("requests.get", side_effect=Exception("Connection refused")):
            r = knowledge_distill(output_path=out)

        assert r.status in ("partial", "failed")
        assert len(r.errors) > 0


# ── Dataset Curate (mocked) ──────────────────────────────────────

class TestDatasetCurate:
    def test_with_mocked_curator(self, tmp_path):
        out = str(tmp_path / "curated")
        mock_stats = MagicMock()
        mock_stats.exported = 5
        mock_stats.to_dict.return_value = {"exported": 5}

        with patch("engine.nexus.dataset_curator.DatasetCurator") as MockCurator:
            MockCurator.return_value.export_qa_dataset.return_value = mock_stats
            MockCurator.return_value.export_instruction_dataset.return_value = mock_stats
            r = dataset_curate(output_dir=out)

        assert r.status == "success"
        assert r.items_output == 10


# ── Research Pipeline (mocked) ───────────────────────────────────

class TestResearchPipeline:
    def test_with_mocked_nexus(self, tmp_path):
        mock_qa_resp = MagicMock()
        mock_qa_resp.ok = True
        mock_qa_resp.json.return_value = {"answer": "MCP manages state.", "confidence": 0.9}

        mock_search_resp = MagicMock()
        mock_search_resp.ok = True
        mock_search_resp.json.return_value = [
            {"title": "MCP Guide", "content": "Full guide here..."},
        ]

        mock_store_resp = MagicMock()
        mock_store_resp.ok = True

        out = str(tmp_path / "research.json")
        with patch("requests.get", side_effect=[mock_qa_resp, mock_search_resp]):
            with patch("requests.post", return_value=mock_store_resp):
                r = research_pipeline(question="What is MCP?", output_path=out)

        assert r.status == "success"
        assert r.items_output >= 1


# ── Registry ─────────────────────────────────────────────────────

class TestRegistry:
    def test_all_workflows_registered(self):
        assert len(WORKFLOWS) == 5
        assert "distill" in WORKFLOWS
        assert "curate" in WORKFLOWS
        assert "research" in WORKFLOWS
        assert "metrics" in WORKFLOWS
        assert "audit" in WORKFLOWS

    def test_all_workflows_callable(self):
        for name, fn in WORKFLOWS.items():
            assert callable(fn), f"{name} is not callable"
