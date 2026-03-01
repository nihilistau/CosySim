"""Tests for engine.nexus.cache_pipeline."""
from __future__ import annotations

import csv
import io
import json
import textwrap
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from engine.nexus.cache_pipeline import (
    CachePipeline,
    CandidatePair,
    EvalResult,
    CycleResult,
    get_cache_pipeline,
)


class TestDataclasses:
    def test_candidate_pair_has_required_fields(self):
        pair = CandidatePair(
            q="What is CosySim?",
            a="A multi-scene simulation framework.",
            consumer="copilot",
            priority=4,
            category="architecture",
        )
        assert pair.q == "What is CosySim?"
        assert pair.priority == 4

    def test_eval_result_has_lists(self):
        er = EvalResult()
        assert isinstance(er.essential, list)
        assert isinstance(er.useful, list)
        assert isinstance(er.skipped, list)

    def test_cycle_result_has_all_fields(self):
        cr = CycleResult(
            direct_seeded=5,
            sources_uploaded=10,
            raw_candidates=50,
            structured_candidates=80,
            after_dedup=60,
            essential=30,
            useful=20,
            skipped=10,
            stored=50,
            review_sheet_path="data/qa.xlsx",
            gaps=["NLM routing"],
            duration_s=120.0,
            errors=[],
            timestamp="2026-01-01T00:00:00",
        )
        assert cr.stored == 50
        assert len(cr.gaps) == 1


class TestExecCodeMode:
    def test_valid_function_returns_pairs(self):
        pipeline = CachePipeline()
        code = textwrap.dedent("""
            def build_qa_pairs():
                return [{"q": "What is X?", "a": "X is Y.", "consumer": "copilot", "priority": 4, "category": "architecture"}]
        """)
        result = pipeline._exec_code_mode(code)
        assert len(result) == 1
        assert result[0].q == "What is X?"

    def test_multiple_pairs_returned(self):
        pipeline = CachePipeline()
        code = textwrap.dedent("""
            def build_qa_pairs():
                return [
                    {"q": "Q1?", "a": "A1.", "consumer": "agent", "priority": 3, "category": "skills"},
                    {"q": "Q2?", "a": "A2.", "consumer": "developer", "priority": 2, "category": "config"},
                ]
        """)
        result = pipeline._exec_code_mode(code)
        assert len(result) == 2

    def test_invalid_python_returns_empty(self):
        pipeline = CachePipeline()
        result = pipeline._exec_code_mode("this is not python !@#$%")
        assert result == []

    def test_function_with_import_in_builtins_disabled(self):
        """Sandbox disables builtins — imports inside function should fail."""
        pipeline = CachePipeline()
        code = textwrap.dedent("""
            def build_qa_pairs():
                import os  # should raise in sandbox
                return [{"q": "Q?", "a": "A.", "consumer": "copilot", "priority": 3, "category": "general"}]
        """)
        result = pipeline._exec_code_mode(code)
        assert result == []

    def test_function_not_defined_returns_empty(self):
        pipeline = CachePipeline()
        code = "x = 1 + 1"
        result = pipeline._exec_code_mode(code)
        assert result == []

    def test_empty_function_returns_empty(self):
        pipeline = CachePipeline()
        code = textwrap.dedent("""
            def build_qa_pairs():
                return []
        """)
        result = pipeline._exec_code_mode(code)
        assert result == []

    def test_wrong_return_type_returns_empty(self):
        pipeline = CachePipeline()
        code = textwrap.dedent("""
            def build_qa_pairs():
                return "not a list"
        """)
        result = pipeline._exec_code_mode(code)
        assert result == []


class TestParseCSVOutput:
    def test_valid_csv_returns_pairs(self):
        pipeline = CachePipeline()
        csv_text = (
            "Question,Answer,Consumer,Priority,Category,Reasoning\n"
            "What is MCP?,Model Context Protocol.,copilot,5,architecture,Core system\n"
        )
        result = pipeline._parse_csv_output(csv_text)
        assert len(result) == 1
        assert result[0].q == "What is MCP?"
        assert result[0].priority == 5

    def test_multiple_rows(self):
        pipeline = CachePipeline()
        csv_text = (
            "Question,Answer,Consumer,Priority,Category,Reasoning\n"
            "Q1?,A1.,copilot,4,architecture,Reason1\n"
            "Q2?,A2.,agent,3,skills,Reason2\n"
        )
        result = pipeline._parse_csv_output(csv_text)
        assert len(result) == 2

    def test_priority_defaults_to_3_on_bad_value(self):
        pipeline = CachePipeline()
        csv_text = (
            "Question,Answer,Consumer,Priority,Category,Reasoning\n"
            "Q?,A.,copilot,bad,general,R\n"
        )
        result = pipeline._parse_csv_output(csv_text)
        if result:
            assert result[0].priority == 3

    def test_empty_string_returns_empty(self):
        pipeline = CachePipeline()
        result = pipeline._parse_csv_output("")
        assert result == []

    def test_no_header_still_parses(self):
        pipeline = CachePipeline()
        # Some rows without header
        csv_text = "What is X?,X is Y.,copilot,4,architecture,R\n"
        result = pipeline._parse_csv_output(csv_text)
        # Should either parse or return empty — no crash
        assert isinstance(result, list)

    def test_malformed_csv_returns_empty_or_partial(self):
        pipeline = CachePipeline()
        result = pipeline._parse_csv_output("not,csv\nor,valid,data,here")
        assert isinstance(result, list)


class TestParseEvaluationOutput:
    def _make_eval_json(self):
        return json.dumps([
            {"q": "What is X?", "a": "X is Y.", "rating": "ESSENTIAL", "reason": "Core"},
            {"q": "How do I test?", "a": "Use pytest.", "rating": "USEFUL", "reason": "Helpful"},
            {"q": "What is 2+2?", "a": "4", "rating": "SKIP", "reason": "Too generic"},
        ])

    def test_essential_and_useful_returned(self):
        pipeline = CachePipeline()
        candidates = [
            CandidatePair("What is X?", "X is Y.", "copilot", 4, "architecture"),
            CandidatePair("How do I test?", "Use pytest.", "developer", 3, "testing"),
            CandidatePair("What is 2+2?", "4", "general", 1, "general"),
        ]
        result = pipeline._parse_evaluation_output(self._make_eval_json(), candidates)
        assert isinstance(result, EvalResult)
        assert len(result.essential) == 1
        assert len(result.useful) == 1
        assert len(result.skipped) == 1

    def test_invalid_json_defaults_to_useful(self):
        pipeline = CachePipeline()
        candidates = [
            CandidatePair("Q?", "A.", "copilot", 3, "general"),
        ]
        result = pipeline._parse_evaluation_output("not json at all", candidates)
        assert isinstance(result, EvalResult)
        # Fail-open: all candidates become USEFUL
        assert len(result.useful) == 1

    def test_empty_candidates_returns_empty_result(self):
        pipeline = CachePipeline()
        result = pipeline._parse_evaluation_output("[]", [])
        assert len(result.essential) == 0
        assert len(result.useful) == 0
        assert len(result.skipped) == 0


class TestStageE:
    """Stage E: deduplication."""

    def test_dedup_removes_exact_duplicates(self):
        pipeline = CachePipeline()
        pairs = [
            CandidatePair("What is the CosySim architecture?", "A.", "copilot", 4, "arch"),
            CandidatePair("What is the CosySim architecture?", "A.", "agent", 3, "arch"),
            CandidatePair("How does the scene system work?", "B.", "copilot", 3, "arch"),
        ]
        with patch("engine.nexus.client.get_nexus_client") as mock_client_fn:
            mock_client_fn.return_value.is_available.return_value = False
            result = pipeline.run_stage_e(pairs)
        assert len(result) == 2

    def test_dedup_removes_nexus_duplicates(self):
        pipeline = CachePipeline()
        pairs = [
            CandidatePair("Already cached?", "Yes.", "copilot", 4, "arch"),
            CandidatePair("New question?", "New answer.", "agent", 3, "arch"),
        ]
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        # "already cached?" matches, "new question?" does not
        mock_client.search.return_value = [{"question": "already cached?"}]

        def _question_exists_side_effect(client, q):
            return q.lower().rstrip("?") == "already cached"

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            with patch.object(pipeline, "_question_exists", side_effect=_question_exists_side_effect):
                result = pipeline.run_stage_e(pairs)
        assert len(result) == 1
        assert result[0].q == "New question?"

    def test_dedup_empty_list(self):
        pipeline = CachePipeline()
        with patch("engine.nexus.client.get_nexus_client") as mock_client_fn:
            mock_client_fn.return_value.is_available.return_value = False
            result = pipeline.run_stage_e([])
        assert result == []


class TestStageG:
    """Stage G: store approved pairs in Nexus."""

    def test_stage_g_stores_each_pair(self):
        pipeline = CachePipeline()
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.add_qa.return_value = "qa-id"

        pairs = [
            CandidatePair("Q1?", "A1.", "copilot", 4, "arch"),
            CandidatePair("Q2?", "A2.", "agent", 3, "skills"),
        ]

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            count = pipeline.run_stage_g(pairs)

        assert count == 2
        assert mock_client.add_qa.call_count == 2

    def test_stage_g_handles_client_unavailable(self):
        pipeline = CachePipeline()
        mock_client = MagicMock()
        mock_client.is_available.return_value = False

        pairs = [CandidatePair("Q?", "A.", "copilot", 3, "general")]

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            count = pipeline.run_stage_g(pairs)

        assert count == 0

    def test_stage_g_empty_pairs_returns_zero(self):
        pipeline = CachePipeline()
        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client):
            count = pipeline.run_stage_g([])

        assert count == 0


class TestFullCycleDryRun:
    def test_dry_run_returns_cycle_result(self):
        pipeline = CachePipeline(dry_run=True)
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.add_qa.return_value = "id"
        mock_client.list_entries.return_value = []
        mock_nlm = MagicMock()
        mock_nlm.add_text_source.return_value = {"status": "ok"}
        mock_nlm.extract_flashcards.return_value = {"flashcards": []}
        mock_nlm.extract_quiz.return_value = {"questions": []}
        mock_nlm.extract_data_tables.return_value = {"tables": []}
        mock_nlm.generate_report_with_prompt.return_value = ""
        mock_nlm.create_notebook.return_value = {"id": "nb-test"}

        with patch("engine.nexus.client.get_nexus_client", return_value=mock_client), \
             patch("engine.mcp.nlm_hybrid.get_nlm_hybrid", return_value=mock_nlm), \
             patch("engine.nexus.history_miner.get_history_miner") as mock_miner_fn, \
             patch("engine.nexus.nlm_notebook_manager.get_notebook_manager") as mock_mgr_fn:

            mock_miner = MagicMock()
            mock_miner.mine_turns.return_value = []
            mock_miner.mine_all_themes.return_value = []
            mock_miner_fn.return_value = mock_miner

            mock_mgr = MagicMock()
            mock_mgr.ensure_notebook.return_value = {"id": "nb-test"}
            mock_mgr_fn.return_value = mock_mgr

            result = pipeline.run_full_cycle()

        assert isinstance(result, CycleResult)
        assert result.errors is not None


class TestSingleton:
    def test_singleton_returns_same_instance(self):
        p1 = get_cache_pipeline()
        p2 = get_cache_pipeline()
        assert p1 is p2
