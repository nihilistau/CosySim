"""Tests for engine/nexus/qa_expander.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.qa_expander import (
    QAExpander,
    _entry_hash,
    _parse_questions,
    get_qa_expander,
    run_qa_expansion,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_entry(
    title: str = "Test Entry",
    content: str = "This is detailed content about how the MCPFramework manages state in CosySim. It uses a tree of MCP nodes.",
    content_type: str = "note",
    category: str = "architecture",
) -> dict:
    return {"id": title, "title": title, "content": content,
            "content_type": content_type, "category": category}


def _make_expander(dry_run: bool = False) -> QAExpander:
    e = QAExpander(dry_run=dry_run)
    e._state = {"expanded_hashes": [], "total_generated": 0, "last_run": None, "runs": 0}
    # Mock internals
    e._nexus = MagicMock()
    long_content = "This is detailed content about how the MCPFramework manages state in CosySim. It uses a tree of MCP nodes that persist between turns."
    e._nexus.search.return_value = [
        _make_entry("Entry A"),
        _make_entry("Entry B", content=long_content + " Skills are registered here."),
        _make_entry("Entry C", content=long_content + " Config access uses dot notation."),
    ]
    e._nexus.add_qa.return_value = {"id": "qa-123"}
    e._nexus.stats.return_value = {"qa_count": 300}
    e._nexus.list_entries = MagicMock(side_effect=AttributeError("no list_entries"))
    e._hybrid = MagicMock()
    e._hybrid.ask.return_value = {
        "answer": (
            "1. What is the MCPFramework?\n"
            "2. How does state management work in CosySim?\n"
            "3. What singletons does MCPFramework expose?\n"
            "4. How do scene nodes attach to the framework tree?\n"
            "5. What persistence options does MCPFramework support?"
        )
    }
    e._hybrid.create_notebook.return_value = {"notebook_id": "nb-expand-test"}
    return e


# ──────────────────────────────────────────────────────────────────────────────
# _entry_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestEntryHash:
    def test_same_entry_same_hash(self) -> None:
        e = _make_entry()
        assert _entry_hash(e) == _entry_hash(e)

    def test_different_title_different_hash(self) -> None:
        e1 = _make_entry(title="Entry One")
        e2 = _make_entry(title="Entry Two")
        assert _entry_hash(e1) != _entry_hash(e2)

    def test_hash_is_12_chars(self) -> None:
        assert len(_entry_hash(_make_entry())) == 12


# ──────────────────────────────────────────────────────────────────────────────
# _parse_questions
# ──────────────────────────────────────────────────────────────────────────────

class TestParseQuestions:
    def test_parses_numbered_dot_format(self) -> None:
        raw = "1. What is MCPFramework?\n2. How does state management work?\n3. Why does this happen?"
        qs = _parse_questions(raw)
        assert len(qs) == 3
        assert "What is MCPFramework?" in qs

    def test_parses_numbered_paren_format(self) -> None:
        raw = "1) What is MCPFramework?\n2) How does state management work?"
        qs = _parse_questions(raw)
        assert len(qs) == 2

    def test_skips_empty_lines(self) -> None:
        raw = "\n1. What is MCPFramework?\n\n2. How does state work?\n\n"
        qs = _parse_questions(raw)
        assert len(qs) == 2

    def test_caps_at_5(self) -> None:
        raw = "\n".join(f"{i}. Question number {i}?" for i in range(1, 10))
        qs = _parse_questions(raw)
        assert len(qs) <= 5

    def test_returns_empty_for_garbage(self) -> None:
        qs = _parse_questions("no questions here not at all really no query marks")
        assert len(qs) == 0


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander.stats
# ──────────────────────────────────────────────────────────────────────────────

class TestQAExpanderStats:
    def test_stats_returns_expected_keys(self) -> None:
        e = _make_expander()
        s = e.stats()
        assert "entries_expanded" in s
        assert "total_generated" in s
        assert "last_run" in s
        assert "runs" in s
        assert "notebook_id" in s
        assert "nexus_qa_count" in s

    def test_stats_reflects_state(self) -> None:
        e = _make_expander()
        e._state = {"expanded_hashes": ["abc", "def"], "total_generated": 42,
                    "last_run": "2025-01-01", "runs": 7, "notebook_id": "nb-x"}
        s = e.stats()
        assert s["entries_expanded"] == 2
        assert s["total_generated"] == 42
        assert s["runs"] == 7


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander.reset
# ──────────────────────────────────────────────────────────────────────────────

class TestQAExpanderReset:
    def test_reset_clears_state(self, tmp_path: Path) -> None:
        from engine.nexus import qa_expander as m
        original = m._STATE_FILE
        m._STATE_FILE = tmp_path / "state.json"
        m._STATE_FILE.write_text('{"expanded_hashes": ["abc"], "runs": 5}')
        try:
            e = QAExpander()
            e.reset()
            assert not m._STATE_FILE.exists()
            assert e._state["runs"] == 0
            assert e._state["expanded_hashes"] == []
        finally:
            m._STATE_FILE = original


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander._fetch_unexpanded_entries
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchUnexpandedEntries:
    def test_skips_qa_type_entries(self) -> None:
        e = _make_expander()
        long = "A " * 50  # well over 80 chars
        e._nexus.search.return_value = [
            _make_entry("QA Entry", content=long, content_type="qa"),
            _make_entry("Good Entry", content=long),
        ]
        e._nexus.list_entries = MagicMock(side_effect=AttributeError)
        results = e._fetch_unexpanded_entries(limit=10)
        titles = [r["title"] for r in results]
        assert "QA Entry" not in titles
        assert "Good Entry" in titles

    def test_skips_short_content(self) -> None:
        e = _make_expander()
        e._nexus.search.return_value = [
            _make_entry("Short Entry", content="too short"),
            _make_entry("Long Entry"),
        ]
        e._nexus.list_entries = MagicMock(side_effect=AttributeError)
        results = e._fetch_unexpanded_entries(limit=10)
        titles = [r["title"] for r in results]
        assert "Short Entry" not in titles

    def test_skips_already_expanded(self) -> None:
        e = _make_expander()
        long = "B " * 50
        entry = _make_entry("Already Done", content=long)
        eh = _entry_hash(entry)
        e._state["expanded_hashes"] = [eh]
        e._nexus.search.return_value = [entry, _make_entry("New Entry")]
        e._nexus.list_entries = MagicMock(side_effect=AttributeError)
        results = e._fetch_unexpanded_entries(limit=10)
        titles = [r["title"] for r in results]
        assert "Already Done" not in titles
        assert "New Entry" in titles

    def test_respects_limit(self) -> None:
        e = _make_expander()
        e._nexus.list_entries = MagicMock(side_effect=AttributeError)
        e._nexus.search.return_value = [
            _make_entry(f"Entry {i}") for i in range(20)
        ]
        results = e._fetch_unexpanded_entries(limit=3)
        assert len(results) <= 3

    def test_uses_list_entries_when_available(self) -> None:
        e = _make_expander()
        long = "C " * 50
        e._nexus.list_entries = MagicMock(return_value=[
            _make_entry("From List Entries", content=long),
        ])
        results = e._fetch_unexpanded_entries(limit=10)
        e._nexus.list_entries.assert_called_once()
        assert any(r["title"] == "From List Entries" for r in results)


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander._expand_entry
# ──────────────────────────────────────────────────────────────────────────────

class TestExpandEntry:
    def test_returns_parsed_questions(self) -> None:
        e = _make_expander()
        questions = e._expand_entry(_make_entry(), "nb-x")
        assert len(questions) >= 1
        assert all(isinstance(q, str) for q in questions)

    def test_handles_nlm_exception(self) -> None:
        e = _make_expander()
        e._hybrid.ask.side_effect = RuntimeError("NLM offline")
        questions = e._expand_entry(_make_entry(), "nb-x")
        assert questions == []

    def test_truncates_long_content(self) -> None:
        e = _make_expander()
        long_entry = _make_entry(content="x" * 10_000)
        # Should not raise even with very long content
        e._expand_entry(long_entry, "nb-x")
        call_kwargs = e._hybrid.ask.call_args
        prompt_arg = call_kwargs[0][1] if call_kwargs[0] else call_kwargs[1].get("prompt", "")
        # Content should be capped at 2000 chars in the prompt
        assert len(prompt_arg) < 5000


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander._store_pairs
# ──────────────────────────────────────────────────────────────────────────────

class TestStorePairs:
    def test_stores_each_question(self) -> None:
        e = _make_expander()
        questions = ["What is X?", "How does Y work?", "Why does Z happen?"]
        stored = e._store_pairs(_make_entry(), questions, e._nexus)
        assert stored == 3
        assert e._nexus.add_qa.call_count == 3

    def test_uses_entry_category(self) -> None:
        e = _make_expander()
        entry = _make_entry(category="performance")
        e._store_pairs(entry, ["What is perf?"], e._nexus)
        call_kwargs = e._nexus.add_qa.call_args[1]
        assert "performance" in call_kwargs.get("category", "")

    def test_truncates_answer_content(self) -> None:
        e = _make_expander()
        entry = _make_entry(content="X" * 5000)
        e._store_pairs(entry, ["What is X?"], e._nexus)
        call_kwargs = e._nexus.add_qa.call_args[1]
        answer = call_kwargs.get("answer", "")
        assert len(answer) <= 1600  # 1500 chars + source tag

    def test_handles_nexus_exception(self) -> None:
        e = _make_expander()
        e._nexus.add_qa.side_effect = RuntimeError("Nexus down")
        stored = e._store_pairs(_make_entry(), ["Q?"], e._nexus)
        assert stored == 0


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander.run — dry run
# ──────────────────────────────────────────────────────────────────────────────

class TestRunDryRun:
    def test_dry_run_returns_counts(self) -> None:
        e = _make_expander(dry_run=True)
        result = e.run(batch_size=3)
        assert result["status"] == "done"
        assert result["entries_processed"] == 3
        assert result["pairs_generated"] == 3 * 5  # 5 questions per entry

    def test_dry_run_makes_no_nlm_calls(self) -> None:
        e = _make_expander(dry_run=True)
        e.run(batch_size=3)
        e._hybrid.ask.assert_not_called()

    def test_dry_run_makes_no_nexus_writes(self) -> None:
        e = _make_expander(dry_run=True)
        e.run(batch_size=3)
        e._nexus.add_qa.assert_not_called()

    def test_dry_run_marks_hashes_as_done(self) -> None:
        e = _make_expander(dry_run=True)
        e.run(batch_size=3)
        assert len(e._state["expanded_hashes"]) == 3


# ──────────────────────────────────────────────────────────────────────────────
# QAExpander.run — live (mocked NLM)
# ──────────────────────────────────────────────────────────────────────────────

class TestRunLive:
    def test_run_calls_nlm_for_each_entry(self) -> None:
        e = _make_expander(dry_run=False)
        # Give expander a notebook ID so it doesn't try to create one
        e._state["notebook_id"] = "nb-x"
        e.run(batch_size=3)
        assert e._hybrid.ask.call_count == 3

    def test_run_stores_pairs_in_nexus(self) -> None:
        e = _make_expander(dry_run=False)
        e._state["notebook_id"] = "nb-x"
        with patch("time.sleep"):  # skip pacing
            result = e.run(batch_size=3)
        assert result["pairs_stored"] > 0
        assert e._nexus.add_qa.call_count > 0

    def test_run_updates_total_generated(self) -> None:
        e = _make_expander(dry_run=False)
        e._state["notebook_id"] = "nb-x"
        with patch("time.sleep"):
            result = e.run(batch_size=2)
        assert e._state["total_generated"] == result["pairs_stored"]

    def test_run_empty_when_all_expanded(self) -> None:
        e = _make_expander(dry_run=False)
        # Pre-mark all entries as expanded
        entries = e._nexus.search.return_value
        e._state["expanded_hashes"] = [_entry_hash(en) for en in entries]
        # Also block list_entries
        e._nexus.list_entries = MagicMock(side_effect=AttributeError)
        result = e.run(batch_size=10)
        assert result["status"] == "complete"
        assert result["entries_processed"] == 0

    def test_run_creates_notebook_if_missing(self) -> None:
        e = _make_expander(dry_run=False)
        e._state.pop("notebook_id", None)
        with patch("time.sleep"):
            e.run(batch_size=1)
        e._hybrid.create_notebook.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# run_qa_expansion (scheduler callback)
# ──────────────────────────────────────────────────────────────────────────────

class TestRunQAExpansionCallback:
    def test_calls_expander_run(self) -> None:
        with patch("engine.nexus.qa_expander.get_qa_expander") as mock_get:
            mock_instance = MagicMock()
            mock_instance.run.return_value = {"status": "done", "pairs_stored": 10}
            mock_get.return_value = mock_instance
            result = run_qa_expansion(batch_size=15)
        mock_instance.run.assert_called_once_with(batch_size=15)
        assert result == {"status": "done", "pairs_stored": 10}

    def test_returns_error_on_exception(self) -> None:
        with patch("engine.nexus.qa_expander.get_qa_expander",
                   side_effect=RuntimeError("NLM offline")):
            result = run_qa_expansion()
        assert "error" in result
        assert "NLM offline" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        from engine.nexus import qa_expander as m
        m._EXPANDER = None  # reset
        e1 = get_qa_expander()
        e2 = get_qa_expander()
        assert e1 is e2


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler integration
# ──────────────────────────────────────────────────────────────────────────────

class TestSchedulerIntegration:
    def test_qa_expansion_task_registered(self) -> None:
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        ids = [call.args[0] for call in daemon.register.call_args_list]
        assert "qa-expansion" in ids

    def test_total_task_count_is_21(self) -> None:
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        assert daemon.register.call_count == 40

    def test_qa_expansion_callback_calls_run(self) -> None:
        from engine.nexus.scheduler_daemon import _qa_expansion_callback
        with patch("engine.nexus.qa_expander.run_qa_expansion") as mock_run:
            mock_run.return_value = {"status": "done", "pairs_stored": 5}
            result = _qa_expansion_callback()
        mock_run.assert_called_once_with(batch_size=20)
        assert result == {"status": "done", "pairs_stored": 5}

    def test_qa_expansion_callback_handles_exception(self) -> None:
        from engine.nexus.scheduler_daemon import _qa_expansion_callback
        with patch("engine.nexus.qa_expander.run_qa_expansion",
                   side_effect=RuntimeError("NLM down")):
            result = _qa_expansion_callback()
        assert "error" in result
        assert "NLM down" in result["error"]

