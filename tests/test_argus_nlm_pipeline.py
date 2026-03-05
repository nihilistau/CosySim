"""Tests for ArgusNLMPipeline — discovery doc building and pipeline orchestration.

All external dependencies (NLM, Nexus, registry) are mocked — no network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch, call

import pytest


# ──── Helpers ────────────────────────────────────────────────────────────────

def _make_pipeline(tmp_path: Path) -> Any:
    """Create an ArgusNLMPipeline with state file redirected to tmp dir."""
    with patch("scripts.argus.nlm_pipeline._STATE_FILE", new=tmp_path / "state.json"):
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()
        return p


def _mock_registry() -> MagicMock:
    reg = MagicMock()
    reg.get_stats.return_value = {
        "nlm_rpcids_seen": 12,
        "nlm_rpcids_total": 25,
        "gemini_rpcids_seen": 8,
        "gemini_rpcids_total": 17,
        "aistudio_methods_seen": 10,
        "aistudio_methods_total": 20,
    }
    reg.get_full_data.return_value = {
        "nlm_rpcids": {"XqA3Tb": {"seen": 5, "last": "2025-01-01"}},
        "gemini_rpcids": {"boq_assistant-bard-web-server_20250101.00_p0": {"seen": 3, "last": "2025-01-02"}},
        "aistudio_methods": {},
    }
    return reg


# ──── State save / load ───────────────────────────────────────────────────────

class TestState:
    def test_state_persists_notebook_id(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import _save_state, _load_state
        state_file = tmp_path / "state.json"
        with patch("scripts.argus.nlm_pipeline._STATE_FILE", new=state_file):
            _save_state({"argus_notebook_nlm_2025-W01": "nb-abc123"})
            loaded = _load_state()
        assert loaded["argus_notebook_nlm_2025-W01"] == "nb-abc123"

    def test_load_state_returns_empty_dict_on_missing(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import _load_state
        missing = tmp_path / "nonexistent.json"
        with patch("scripts.argus.nlm_pipeline._STATE_FILE", new=missing):
            result = _load_state()
        assert result == {}

    def test_load_state_returns_empty_on_corrupt_json(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import _load_state
        bad = tmp_path / "bad.json"
        bad.write_text("{{broken}", encoding="utf-8")
        with patch("scripts.argus.nlm_pipeline._STATE_FILE", new=bad):
            result = _load_state()
        assert result == {}


# ──── ArgusDocBuilder ─────────────────────────────────────────────────────────

class TestArgusDocBuilder:
    def _build(self, target=None):
        from scripts.argus.nlm_pipeline import ArgusDocBuilder
        builder = ArgusDocBuilder()

        nlm_rpcids = {"XqA3Tb": "GetNotebooks", "YrB4Uc": "CreateNotebook"}
        gemini_rpcids = {"GemRpc1": "StartConversation"}
        aistudio_methods = {
            "AppletService/GetModel": {"service": "AppletService", "method": "GetModel"},
        }
        mock_reg = _mock_registry()

        with (
            patch("scripts.argus.nlm_pipeline.ArgusDocBuilder._load_recent_scan_summary", return_value=[]),
            patch("scripts.argus.config.NLM_RPCIDS", nlm_rpcids, create=True),
            patch("scripts.argus.config.GEMINI_RPCIDS", gemini_rpcids, create=True),
            patch("scripts.argus.config.AISTUDIO_METHODS", aistudio_methods, create=True),
            patch("scripts.argus.discovery.endpoint_registry.get_registry", return_value=mock_reg),
        ):
            return builder.build(target=target)

    def test_build_all_contains_all_sections(self) -> None:
        doc = self._build()
        assert "NotebookLM API" in doc
        assert "Gemini API" in doc
        assert "AI Studio API" in doc

    def test_build_nlm_only(self) -> None:
        doc = self._build(target="nlm")
        assert "NotebookLM API" in doc
        assert "Gemini API" not in doc
        assert "AI Studio API" not in doc

    def test_build_gemini_only(self) -> None:
        doc = self._build(target="gemini")
        assert "Gemini API" in doc
        assert "NotebookLM API" not in doc

    def test_build_aistudio_only(self) -> None:
        doc = self._build(target="aistudio")
        assert "AI Studio API" in doc
        assert "AppletService" in doc

    def test_build_contains_rpcids(self) -> None:
        doc = self._build(target="nlm")
        assert "XqA3Tb" in doc
        assert "GetNotebooks" in doc

    def test_build_fallback_on_registry_error(self) -> None:
        """Builder should return a valid (minimal) doc even if registry import fails."""
        from scripts.argus.nlm_pipeline import ArgusDocBuilder
        builder = ArgusDocBuilder()
        with (
            patch("scripts.argus.nlm_pipeline.ArgusDocBuilder._load_recent_scan_summary", return_value=[]),
            patch.dict("sys.modules", {"scripts.argus.config": None}),
        ):
            doc = builder.build(target="nlm")
        # Should not raise, returns partial or empty doc
        assert isinstance(doc, str)

    def test_build_includes_protocol_info(self) -> None:
        doc = self._build(target="nlm")
        assert "batchexecute" in doc
        assert "__Secure-1PSID" in doc

    def test_build_aistudio_groups_by_service(self) -> None:
        doc = self._build(target="aistudio")
        assert "AppletService" in doc
        assert "GetModel" in doc


# ──── _get_or_create_notebook ─────────────────────────────────────────────────

class TestGetOrCreateNotebook:
    def test_returns_cached_notebook_id(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({"argus_notebook_nlm_2025-W01": "existing-nb"}),
            encoding="utf-8",
        )
        mock_bridge = MagicMock()
        with (
            patch("scripts.argus.nlm_pipeline._STATE_FILE", new=state_file),
            patch("scripts.argus.nlm_pipeline._week_label", return_value="2025-W01"),
            patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge),
        ):
            from scripts.argus.nlm_pipeline import ArgusNLMPipeline
            p = ArgusNLMPipeline()
            result = p._get_or_create_notebook("nlm")

        assert result == "existing-nb"
        mock_bridge.create_notebook.assert_not_called()

    def test_creates_new_notebook_and_caches(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        mock_bridge = MagicMock()
        mock_bridge.create_notebook.return_value = {"notebook_id": "new-nb-456"}

        with (
            patch("scripts.argus.nlm_pipeline._STATE_FILE", new=state_file),
            patch("scripts.argus.nlm_pipeline._week_label", return_value="2025-W42"),
            patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge),
        ):
            from scripts.argus.nlm_pipeline import ArgusNLMPipeline
            p = ArgusNLMPipeline()
            result = p._get_or_create_notebook("gemini")

        assert result == "new-nb-456"
        assert p._state.get("argus_notebook_gemini_2025-W42") == "new-nb-456"

    def test_returns_none_on_bridge_failure(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        with patch("scripts.argus.nlm_pipeline._STATE_FILE", new=state_file):
            from scripts.argus.nlm_pipeline import ArgusNLMPipeline
            p = ArgusNLMPipeline()

        mock_bridge = MagicMock()
        mock_bridge.create_notebook.side_effect = RuntimeError("NLM offline")

        with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge):
            result = p._get_or_create_notebook("nlm")

        assert result is None


# ──── _upload_discovery_doc ──────────────────────────────────────────────────

class TestUploadDiscoveryDoc:
    def test_returns_true_on_success(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_bridge = MagicMock()
        mock_bridge.add_source.return_value = {"source_id": "src-1"}

        with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge):
            result = p._upload_discovery_doc("nb-123", "API doc content", "nlm")

        assert result is True
        mock_bridge.add_source.assert_called_once()
        _, kwargs = mock_bridge.add_source.call_args
        assert "nb-123" in mock_bridge.add_source.call_args[0] or kwargs

    def test_returns_false_on_bridge_error(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_bridge = MagicMock()
        mock_bridge.add_source.side_effect = RuntimeError("upload failed")

        with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge):
            result = p._upload_discovery_doc("nb-123", "content", "gemini")

        assert result is False

    def test_returns_false_on_error_in_response(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_bridge = MagicMock()
        mock_bridge.add_source.return_value = {"error": "quota exceeded"}

        with patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge):
            result = p._upload_discovery_doc("nb-123", "content", "aistudio")

        assert result is False


# ──── _run_distillation ───────────────────────────────────────────────────────

class TestRunDistillation:
    def test_returns_qa_pairs(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_hybrid = MagicMock()
        mock_hybrid.ask_batch.return_value = [
            {"answer": "Answer to question 1"},
            {"answer": "Answer to question 2"},
            "Short answer",  # str format
        ] + [{"answer": f"Answer {i}"}for i in range(20)]

        with patch.object(p, "_get_hybrid", return_value=mock_hybrid):
            result = p._run_distillation("nb-abc", "nlm")

        assert isinstance(result, list)
        assert all("question" in r and "answer" in r for r in result)

    def test_filters_empty_answers(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_hybrid = MagicMock()
        # Mix of empty + valid answers
        mock_hybrid.ask_batch.return_value = [
            {"answer": ""},
            {"answer": "Valid answer here with enough content"},
            {"answer": "error: something went wrong"},
        ] + [{"answer": ""}] * 20

        with patch.object(p, "_get_hybrid", return_value=mock_hybrid):
            result = p._run_distillation("nb-abc", "gemini")

        # Only "Valid answer here..." passes (non-empty, doesn't start with "error")
        assert len(result) == 1
        assert result[0]["answer"] == "Valid answer here with enough content"

    def test_returns_empty_on_bridge_failure(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_hybrid = MagicMock()
        mock_hybrid.ask_batch.side_effect = RuntimeError("NLM timeout")

        with patch.object(p, "_get_hybrid", return_value=mock_hybrid):
            result = p._run_distillation("nb-abc", "aistudio")

        assert result == []


# ──── _store_qa_to_nexus ──────────────────────────────────────────────────────

class TestStoreQAToNexus:
    def test_stores_all_pairs(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_nexus = MagicMock()
        qa_pairs = [
            {"question": "What is rpcid XqA3Tb?", "answer": "It is GetNotebooks."},
            {"question": "What auth is needed?", "answer": "Session cookies."},
        ]

        with patch.object(p, "_get_nexus", return_value=mock_nexus):
            stored = p._store_qa_to_nexus(qa_pairs, "nlm")

        assert stored == 2
        assert mock_nexus.add_qa.call_count == 2
        # Questions should be prefixed with [ARGUS:NLM]
        first_call = mock_nexus.add_qa.call_args_list[0]
        assert "[ARGUS:NLM]" in first_call[0][0]

    def test_handles_nexus_failure_gracefully(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_nexus = MagicMock()
        mock_nexus.add_qa.side_effect = RuntimeError("DB error")

        qa_pairs = [{"question": "Q?", "answer": "A."}]
        with patch.object(p, "_get_nexus", return_value=mock_nexus):
            stored = p._store_qa_to_nexus(qa_pairs, "gemini")

        assert stored == 0


# ──── run() — dry run ─────────────────────────────────────────────────────────

class TestRunDryRun:
    def test_dry_run_builds_doc_no_writes(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_nexus = MagicMock()
        mock_bridge = MagicMock()

        with (
            patch.object(p._doc_builder, "build", return_value="# Discovery Doc\n\nContent here."),
            patch.object(p, "_get_nexus", return_value=mock_nexus),
            patch("engine.mcp.nlm_node_bridge.get_nlm_node_bridge", return_value=mock_bridge),
        ):
            result = p.run(target="nlm", dry_run=True)

        assert result["dry_run"] is True
        assert result["total_qa"] == 0
        assert result["total_stored"] == 0
        mock_nexus.add_qa.assert_not_called()
        mock_bridge.add_source.assert_not_called()
        mock_bridge.create_notebook.assert_not_called()


# ──── run() — NLM offline ─────────────────────────────────────────────────────

class TestRunNLMOffline:
    def test_run_skips_gracefully_when_nlm_unavailable(self, tmp_path: Path) -> None:
        from scripts.argus.nlm_pipeline import ArgusNLMPipeline
        p = ArgusNLMPipeline()

        mock_nexus = MagicMock()

        with (
            patch.object(p._doc_builder, "build", return_value="# Doc"),
            patch.object(p, "_get_nexus", return_value=mock_nexus),
            patch.object(p, "_get_or_create_notebook", return_value=None),
        ):
            result = p.run(target="nlm")

        run = result["runs"][0]
        assert run["notebook_id"] is None
        assert "error" in run
        assert run["stored"] == 0


# ──── DISTILLATION_QUESTIONS content check ────────────────────────────────────

class TestDistillationQuestions:
    def test_all_targets_have_questions(self) -> None:
        from scripts.argus.nlm_pipeline import DISTILLATION_QUESTIONS
        for target in ["nlm", "gemini", "aistudio", "general"]:
            assert target in DISTILLATION_QUESTIONS
            assert len(DISTILLATION_QUESTIONS[target]) >= 5

    def test_nlm_questions_mention_rpcid(self) -> None:
        from scripts.argus.nlm_pipeline import DISTILLATION_QUESTIONS
        combined = " ".join(DISTILLATION_QUESTIONS["nlm"])
        assert "rpcid" in combined.lower()

    def test_aistudio_questions_mention_grpc(self) -> None:
        from scripts.argus.nlm_pipeline import DISTILLATION_QUESTIONS
        combined = " ".join(DISTILLATION_QUESTIONS["aistudio"]).lower()
        assert "grpc" in combined or "service" in combined
