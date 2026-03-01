"""Tests for engine.nexus.consumer_briefing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from engine.nexus.consumer_briefing import (
    ConsumerBriefing,
    get_consumer_briefing,
    CSV_HEADER,
    CONSUMER_CLASSES,
)


class TestConsumerClasses:
    def test_five_consumer_classes_defined(self):
        assert len(CONSUMER_CLASSES) == 5

    def test_all_expected_classes_present(self):
        expected = {"copilot", "agent", "governance", "developer", "news"}
        for cls in CONSUMER_CLASSES:
            # Each class name should contain at least one expected word
            assert any(exp in cls for exp in expected), f"Unknown class: {cls}"


class TestBriefingDocument:
    def test_build_briefing_returns_string(self):
        cb = ConsumerBriefing()
        doc = cb.build_briefing()
        assert isinstance(doc, str)
        assert len(doc) > 100

    def test_briefing_mentions_all_consumer_classes(self):
        cb = ConsumerBriefing()
        doc = cb.build_briefing().lower()
        # Should reference at least these consumer contexts
        for keyword in ("copilot", "agent", "governance", "developer", "news"):
            assert keyword in doc, f"Briefing missing consumer keyword: {keyword}"


class TestCSVPrompt:
    def test_csv_prompt_returns_string(self):
        cb = ConsumerBriefing()
        prompt = cb.build_csv_prompt()
        assert isinstance(prompt, str)

    def test_csv_prompt_contains_header(self):
        cb = ConsumerBriefing()
        prompt = cb.build_csv_prompt()
        assert CSV_HEADER in prompt or "Question" in prompt

    def test_csv_prompt_with_consumer_focus(self):
        cb = ConsumerBriefing()
        prompt = cb.build_csv_prompt(consumer_focus="copilot")
        assert isinstance(prompt, str)
        assert "copilot" in prompt.lower()

    def test_csv_prompt_count_parameter(self):
        cb = ConsumerBriefing()
        prompt = cb.build_csv_prompt(count=50)
        assert "50" in prompt


class TestCodeGenPrompt:
    def test_code_gen_prompt_returns_string(self):
        cb = ConsumerBriefing()
        prompt = cb.build_code_gen_prompt()
        assert isinstance(prompt, str)

    def test_code_gen_prompt_contains_function_name(self):
        cb = ConsumerBriefing()
        prompt = cb.build_code_gen_prompt()
        assert "build_qa_pairs" in prompt

    def test_code_gen_prompt_contains_return_type(self):
        cb = ConsumerBriefing()
        prompt = cb.build_code_gen_prompt()
        # Should specify list[dict] return type
        assert "list" in prompt.lower() or "List" in prompt


class TestEvaluationPrompt:
    def test_evaluation_prompt_returns_string(self):
        cb = ConsumerBriefing()
        prompt = cb.build_evaluation_prompt("q,a\nWhat is X?,X is Y.")
        assert isinstance(prompt, str)

    def test_evaluation_prompt_contains_essential(self):
        cb = ConsumerBriefing()
        prompt = cb.build_evaluation_prompt("q,a\nWhat is X?,X is Y.")
        assert "ESSENTIAL" in prompt

    def test_evaluation_prompt_contains_useful(self):
        cb = ConsumerBriefing()
        prompt = cb.build_evaluation_prompt("q,a\nWhat is X?,X is Y.")
        assert "USEFUL" in prompt

    def test_evaluation_prompt_contains_skip(self):
        cb = ConsumerBriefing()
        prompt = cb.build_evaluation_prompt("q,a\nWhat is X?,X is Y.")
        assert "SKIP" in prompt

    def test_evaluation_prompt_embeds_pairs_csv(self):
        cb = ConsumerBriefing()
        csv_data = "q,a\nWhat is CosySim?,A simulation framework."
        prompt = cb.build_evaluation_prompt(csv_data)
        assert "CosySim" in prompt


class TestGapPrompt:
    def test_gap_prompt_returns_string(self):
        cb = ConsumerBriefing()
        prompt = cb.build_gap_prompt(["What is the config key?", "How do I create a scene?"])
        assert isinstance(prompt, str)

    def test_gap_prompt_includes_covered_questions(self):
        cb = ConsumerBriefing()
        covered = ["What is the config key for the bedroom port?"]
        prompt = cb.build_gap_prompt(covered)
        assert "bedroom" in prompt.lower() or "config key" in prompt.lower()

    def test_gap_prompt_with_empty_list(self):
        cb = ConsumerBriefing()
        prompt = cb.build_gap_prompt([])
        assert isinstance(prompt, str)
        assert len(prompt) > 50


class TestSchemaAndExamples:
    def test_get_schema_doc_returns_string(self):
        cb = ConsumerBriefing()
        schema = cb.get_schema_doc()
        assert isinstance(schema, str)
        assert "Question" in schema or "question" in schema.lower()

    def test_get_good_examples_returns_string(self):
        cb = ConsumerBriefing()
        examples = cb.get_good_examples()
        assert isinstance(examples, str)
        assert len(examples) > 50

    def test_get_bad_examples_returns_string(self):
        cb = ConsumerBriefing()
        bad = cb.get_bad_examples()
        assert isinstance(bad, str)
        assert len(bad) > 50

    def test_build_priority_rubric_returns_string(self):
        cb = ConsumerBriefing()
        rubric = cb.build_priority_rubric()
        assert isinstance(rubric, str)
        # Should mention all 5 priority levels
        for i in range(1, 6):
            assert str(i) in rubric


class TestNexusPersistence:
    def test_save_to_nexus_calls_client(self):
        cb = ConsumerBriefing()
        client = MagicMock()
        client.is_available.return_value = True
        client.add_entry.return_value = "entry-id-123"

        result = cb.save_to_nexus(client)
        assert client.add_entry.called or client.add_qa.called

    def test_load_from_nexus_returns_string_or_none(self):
        cb = ConsumerBriefing()
        client = MagicMock()
        client.is_available.return_value = True
        client.search.return_value = []

        result = cb.load_from_nexus(client)
        # Should return string or None
        assert result is None or isinstance(result, str)

    def test_save_to_nexus_client_unavailable(self):
        cb = ConsumerBriefing()
        client = MagicMock()
        client.is_available.return_value = False

        # Should not raise
        result = cb.save_to_nexus(client)
        assert result is None or isinstance(result, str)


class TestSingleton:
    def test_singleton_returns_same_instance(self):
        c1 = get_consumer_briefing()
        c2 = get_consumer_briefing()
        assert c1 is c2
