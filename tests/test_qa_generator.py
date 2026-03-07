"""Tests for engine.nexus.qa_generator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engine.nexus.qa_generator import (
    _insert_qa,
    _load_entries,
    _qa_exists,
    print_stats,
    run_rule_based,
)


def _entry(
    entry_id: str,
    title: str,
    content: str,
    content_type: str = "note",
    category: str = "architecture",
) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "content": content,
        "content_type": content_type,
        "category": category,
        "tags": [],
    }


class TestLoadEntries:
    def test_load_entries_dedupes_filters_and_prioritizes(self) -> None:
        client = MagicMock()
        client.list_entries.side_effect = [
            [
                _entry(
                    "dup",
                    "Duplicate",
                    "This architecture entry explains how Nexus coordinates shared state. " * 4,
                    "document",
                    "architecture",
                ),
                _entry("short", "Short", "tiny", "document", "architecture"),
            ],
            [
                _entry(
                    "dup",
                    "Duplicate",
                    "This architecture entry explains how Nexus coordinates shared state. " * 4,
                    "research",
                    "architecture",
                ),
                _entry(
                    "low",
                    "Low Priority",
                    "Miscellaneous notes about a secondary workflow that is still long enough. " * 4,
                    "research",
                    "misc",
                ),
            ],
            [
                _entry(
                    "high",
                    "High Priority",
                    "API notes describing how the Nexus endpoint is queried and updated. " * 4,
                    "note",
                    "api",
                ),
            ],
        ]

        entries = _load_entries(
            client,
            limit=10,
            content_types=["document", "research", "note"],
        )

        ids = [entry["id"] for entry in entries]
        assert ids.count("dup") == 1
        assert "short" not in ids
        assert ids[-1] == "low"


class TestQaExists:
    def test_qa_exists_matches_client_results(self) -> None:
        client = MagicMock()
        client.find_qa.return_value = [{"question": "What is MCP?"}]

        assert _qa_exists(client, "What is MCP?")

    def test_qa_exists_returns_false_when_not_found(self) -> None:
        client = MagicMock()
        client.find_qa.return_value = [{"question": "How does Nexus work?"}]

        assert not _qa_exists(client, "What is MCP?")


class TestInsertQa:
    def test_insert_qa_uses_client_and_compounds_training(self) -> None:
        client = MagicMock()
        client.find_qa.return_value = []
        client.add_qa.return_value = "qa-1"
        flywheel = MagicMock()

        with patch(
            "engine.nexus.qa_generator._get_training_flywheel",
            return_value=flywheel,
        ):
            uid = _insert_qa(
                client,
                "What is MCP?",
                "Model Context Protocol is the shared state and tool structure.",
                category="architecture",
                source_type="rule_based",
                quality_score=0.8,
                tags=["seed"],
            )

        assert uid == "qa-1"
        call_kwargs = client.add_qa.call_args.kwargs
        assert call_kwargs["category"] == "architecture"
        assert "qa-generator" in call_kwargs["tags"]
        assert "rule_based" in call_kwargs["tags"]
        flywheel.collect_from_qa.assert_called_once()

    def test_insert_qa_skips_duplicate_questions(self) -> None:
        client = MagicMock()
        client.find_qa.return_value = [{"question": "What is MCP?"}]

        uid = _insert_qa(
            client,
            "What is MCP?",
            "Model Context Protocol is the shared state and tool structure.",
        )

        assert uid is None
        client.add_qa.assert_not_called()


class TestRunRuleBased:
    def test_run_rule_based_uses_client_backed_flow(self) -> None:
        client = MagicMock()
        client.stats.side_effect = [
            {"ok": True, "data": {"qa_pairs": 10}},
            {"ok": True, "data": {"qa_pairs": 12}},
        ]
        generated_pairs = [
            (
                "What is MCP?",
                "Model Context Protocol is the shared state and tool structure.",
                "architecture",
                0.8,
            ),
            (
                "How does Nexus work?",
                "Nexus stores knowledge entries, Q&A pairs, and rules for retrieval.",
                "system",
                0.7,
            ),
        ]

        with patch(
            "engine.nexus.qa_generator._get_nexus_client",
            return_value=client,
        ), patch(
            "engine.nexus.qa_generator._load_entries",
            return_value=[_entry("one", "One", "A" * 200)],
        ) as mock_load, patch(
            "engine.nexus.qa_generator._generate_rule_qa",
            return_value=generated_pairs,
        ), patch(
            "engine.nexus.qa_generator._insert_qa",
            side_effect=["qa-1", None],
        ), patch("engine.nexus.qa_generator.time.sleep"):
            added = run_rule_based(limit=5)

        assert added == 1
        mock_load.assert_called_once_with(client, limit=10)


class TestPrintStats:
    def test_print_stats_uses_stats_envelope(self, capsys) -> None:
        client = MagicMock()
        client.stats.return_value = {
            "ok": True,
            "data": {"qa_pairs": 7, "knowledge_entries": 42},
        }

        with patch("engine.nexus.qa_generator._get_nexus_client", return_value=client):
            print_stats()

        output = capsys.readouterr().out
        assert "7" in output
        assert "42" in output
        assert "not exposed" in output
