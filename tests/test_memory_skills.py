"""Tests for memory_skills.py — memory query, storage, and chain summarization skills.

Covers:
- search_memory: RAG vector search with character filtering
- store_memory: RAG storage with importance scoring
- get_event_chain_summary: event chain retrieval & formatting
- summarize_chain: LLM-based chain compaction with optional RAG storage
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _make_memory(content: str, **overrides) -> dict:
    """Create a mock RAG memory result dict."""
    result = {"content": content, "score": 0.9, "memory_type": "fact"}
    result.update(overrides)
    return result


def _make_event(event_type: str, actor: str, summary: str, **overrides) -> dict:
    """Create a mock event dict matching EventChain output."""
    event = {
        "event_type": event_type,
        "actor": actor,
        "summary": summary,
        "timestamp": "2025-01-15T10:30:00.000Z",
    }
    event.update(overrides)
    return event


def _chain_context(**overrides) -> dict:
    """Return a typical chain context dict."""
    ctx = {
        "chain_id": "chain-abc-123",
        "scene_id": "phone",
        "character_id": "char-01",
    }
    ctx.update(overrides)
    return ctx


# ═══════════════════════════════════════════════════════════════════
# search_memory
# ═══════════════════════════════════════════════════════════════════

class TestSearchMemory:
    """Tests for the search_memory skill."""

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_results_found(self, MockRAG, mock_ctx):
        """Matching memories are formatted as numbered lines."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value
        rag_inst.query_memories.return_value = [
            _make_memory("The user likes jazz"),
            _make_memory("Meeting scheduled for Tuesday"),
        ]

        from engine.skills.builtin.memory_skills import search_memory
        result = search_memory("jazz")

        assert "Memory 1: The user likes jazz" in result
        assert "Memory 2: Meeting scheduled for Tuesday" in result
        rag_inst.query_memories.assert_called_once_with(
            character_id="char-01",
            query="jazz",
            n_results=5,
            chain_id="chain-abc-123",
            scene_id="phone",
        )

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_no_results(self, MockRAG, mock_ctx):
        """Empty result set returns a friendly message."""
        mock_ctx.return_value = _chain_context()
        MockRAG.return_value.query_memories.return_value = []

        from engine.skills.builtin.memory_skills import search_memory
        result = search_memory("nonexistent topic")

        assert result == "No relevant memories found."

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_custom_character_id(self, MockRAG, mock_ctx):
        """Explicit character_id overrides the chain context value."""
        mock_ctx.return_value = _chain_context(character_id="ctx-char")
        rag_inst = MockRAG.return_value
        rag_inst.query_memories.return_value = [_make_memory("result")]

        from engine.skills.builtin.memory_skills import search_memory
        search_memory("query", character_id="explicit-char")

        assert rag_inst.query_memories.call_args[1]["character_id"] == "explicit-char"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_fallback_character_id_global(self, MockRAG, mock_ctx):
        """No character_id in args or context falls back to 'global'."""
        mock_ctx.return_value = {"chain_id": None, "scene_id": "unknown"}
        rag_inst = MockRAG.return_value
        rag_inst.query_memories.return_value = []

        from engine.skills.builtin.memory_skills import search_memory
        search_memory("query")

        assert rag_inst.query_memories.call_args[1]["character_id"] == "global"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_top_k_clamped_to_range(self, MockRAG, mock_ctx):
        """top_k is clamped between 1 and 20."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value
        rag_inst.query_memories.return_value = []

        from engine.skills.builtin.memory_skills import search_memory

        search_memory("q", top_k=0)
        assert rag_inst.query_memories.call_args[1]["n_results"] == 1

        search_memory("q", top_k=50)
        assert rag_inst.query_memories.call_args[1]["n_results"] == 20

        search_memory("q", top_k=10)
        assert rag_inst.query_memories.call_args[1]["n_results"] == 10

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_exception_returns_error_string(self, MockRAG, mock_ctx):
        """Exceptions are caught and returned as error messages."""
        mock_ctx.side_effect = RuntimeError("DB offline")

        from engine.skills.builtin.memory_skills import search_memory
        result = search_memory("anything")

        assert "Memory search failed:" in result
        assert "DB offline" in result

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_results_with_plain_string_entries(self, MockRAG, mock_ctx):
        """Results that lack a 'content' key use the raw repr."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value
        rag_inst.query_memories.return_value = [{"score": 0.5}]

        from engine.skills.builtin.memory_skills import search_memory
        result = search_memory("query")

        # Falls back to str(r) because r.get('content', r) returns r itself
        assert "Memory 1:" in result


# ═══════════════════════════════════════════════════════════════════
# store_memory
# ═══════════════════════════════════════════════════════════════════

class TestStoreMemory:
    """Tests for the store_memory skill."""

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_success(self, MockRAG, mock_ctx):
        """Successful storage returns confirmation with importance score."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        result = store_memory("The user prefers dark mode", importance=0.9)

        assert "Memory stored successfully" in result
        assert "0.9" in result
        rag_inst.add_memory.assert_called_once_with(
            character_id="char-01",
            content="The user prefers dark mode",
            memory_type="fact",
            importance=0.9,
            chain_id="chain-abc-123",
            scene_id="phone",
        )

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_with_chain_context(self, MockRAG, mock_ctx):
        """Chain context values flow through to add_memory."""
        ctx = _chain_context(chain_id="chain-xyz", scene_id="bedroom")
        mock_ctx.return_value = ctx
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        store_memory("Some fact")

        kwargs = rag_inst.add_memory.call_args[1]
        assert kwargs["chain_id"] == "chain-xyz"
        assert kwargs["scene_id"] == "bedroom"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_custom_character_id(self, MockRAG, mock_ctx):
        """Explicit character_id overrides context."""
        mock_ctx.return_value = _chain_context(character_id="ctx-char")
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        store_memory("info", character_id="custom-char")

        assert rag_inst.add_memory.call_args[1]["character_id"] == "custom-char"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_custom_memory_type(self, MockRAG, mock_ctx):
        """Non-default memory_type is passed through."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        store_memory("User felt happy", memory_type="emotion")

        assert rag_inst.add_memory.call_args[1]["memory_type"] == "emotion"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_fallback_character_global(self, MockRAG, mock_ctx):
        """No character_id anywhere defaults to 'global'."""
        mock_ctx.return_value = {}
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        store_memory("global fact")

        assert rag_inst.add_memory.call_args[1]["character_id"] == "global"

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_exception_returns_error(self, MockRAG, mock_ctx):
        """Exceptions are caught and returned as error messages."""
        mock_ctx.return_value = _chain_context()
        MockRAG.return_value.add_memory.side_effect = IOError("disk full")

        from engine.skills.builtin.memory_skills import store_memory
        result = store_memory("data")

        assert "Failed to store memory:" in result
        assert "disk full" in result

    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    def test_store_importance_cast_to_float(self, MockRAG, mock_ctx):
        """importance parameter is cast to float."""
        mock_ctx.return_value = _chain_context()
        rag_inst = MockRAG.return_value

        from engine.skills.builtin.memory_skills import store_memory
        store_memory("info", importance=1)

        assert isinstance(rag_inst.add_memory.call_args[1]["importance"], float)


# ═══════════════════════════════════════════════════════════════════
# get_event_chain_summary
# ═══════════════════════════════════════════════════════════════════

class TestGetEventChainSummary:
    """Tests for the get_event_chain_summary skill."""

    @patch("content.simulation.database.events.get_event_chain")
    def test_events_found(self, mock_get_ec):
        """Events are formatted with timestamp, type, actor, and summary."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("user_message", "user", "Hello there"),
            _make_event("llm_response", "assistant", "Hi! How can I help?"),
        ]
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-001")

        assert "Event chain: chain-001" in result
        assert "Total events: 2" in result
        assert "user_message (user): Hello there" in result
        assert "llm_response (assistant): Hi! How can I help?" in result

    @patch("content.simulation.database.events.get_event_chain")
    def test_no_events(self, mock_get_ec):
        """Empty chain returns a 'no events' message."""
        ec = MagicMock()
        ec.get_chain.return_value = []
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-empty")

        assert "No events found for chain chain-empty" in result

    @patch("content.simulation.database.events.get_event_chain")
    def test_none_events(self, mock_get_ec):
        """None result from get_chain is treated as no events."""
        ec = MagicMock()
        ec.get_chain.return_value = None
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-none")

        assert "No events found" in result

    @patch("content.simulation.database.events.get_event_chain")
    def test_exception_returns_error(self, mock_get_ec):
        """Exceptions are caught and returned as error messages."""
        mock_get_ec.side_effect = ConnectionError("DB unreachable")

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-err")

        assert "Failed to retrieve event chain:" in result
        assert "DB unreachable" in result

    @patch("content.simulation.database.events.get_event_chain")
    def test_timestamp_truncation(self, mock_get_ec):
        """Timestamps are truncated to 19 chars (YYYY-MM-DDTHH:MM:SS)."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("test", "bot", "evt", timestamp="2025-01-15T10:30:00.123456Z"),
        ]
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-ts")

        assert "2025-01-15T10:30:00" in result
        # Fractional seconds stripped
        assert ".123456Z" not in result

    @patch("content.simulation.database.events.get_event_chain")
    def test_missing_fields_handled(self, mock_get_ec):
        """Events with missing optional fields still format correctly."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            {"event_type": "test"},  # no actor, summary, timestamp
        ]
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import get_event_chain_summary
        result = get_event_chain_summary("chain-sparse")

        assert "test ()" in result  # actor defaults to ""


# ═══════════════════════════════════════════════════════════════════
# summarize_chain
# ═══════════════════════════════════════════════════════════════════

class TestSummarizeChain:
    """Tests for the summarize_chain skill."""

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_with_llm_and_store(self, mock_get_ec, MockRAG, mock_ctx, MockEC):
        """LLM summarization stores result in RAG and logs compaction event."""
        # Event chain data
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("user_message", "user", "Tell me about cats"),
            _make_event("llm_response", "assistant", "Cats are great pets"),
        ]
        mock_get_ec.return_value = ec

        # Chain context
        mock_ctx.return_value = _chain_context()

        # Mock lmstudio
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "User asked about cats; assistant replied positively."

        with patch.dict("sys.modules", {"lmstudio": MagicMock()}):
            import sys
            mock_lms = sys.modules["lmstudio"]
            mock_lms.llm.return_value = mock_llm

            from engine.skills.builtin.memory_skills import summarize_chain
            result = summarize_chain("chain-sum", character_id="char-01")

        assert "Chain summarized and stored" in result
        assert "User asked about cats" in result

        # Verify RAG storage
        rag_inst = MockRAG.return_value
        rag_inst.add_memory.assert_called_once()
        store_kwargs = rag_inst.add_memory.call_args[1]
        assert store_kwargs["memory_type"] == "chain_summary"
        assert store_kwargs["importance"] == 0.8
        assert store_kwargs["metadata"] == {"chain_id": "chain-sum"}

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_llm_fallback(self, mock_get_ec, MockRAG, mock_ctx, MockEC):
        """When LLM import fails, fallback joins first 8 summaries with pipes."""
        ec = MagicMock()
        events = [
            _make_event("user_message", "user", f"Message {i}")
            for i in range(10)
        ]
        ec.get_chain.return_value = events
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context()

        # Make lmstudio import fail
        with patch.dict("sys.modules", {"lmstudio": None}):
            from engine.skills.builtin.memory_skills import summarize_chain
            result = summarize_chain("chain-fb", character_id="char-01")

        assert "Chain summarized and stored" in result
        # Fallback joins with " | " and only takes first 8
        assert " | " in result
        # Verify only 8 items max in fallback
        rag_inst = MockRAG.return_value
        stored_content = rag_inst.add_memory.call_args[1]["content"]
        assert stored_content.count(" | ") <= 7  # at most 8 items → 7 separators

    @patch("content.simulation.database.events.get_event_chain")
    def test_no_events(self, mock_get_ec):
        """No events returns an explanatory message without storing."""
        ec = MagicMock()
        ec.get_chain.return_value = []
        mock_get_ec.return_value = ec

        from engine.skills.builtin.memory_skills import summarize_chain
        result = summarize_chain("chain-empty")

        assert "No events found for chain chain-empty" in result
        assert "nothing to summarize" in result

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_store_false_skips_rag(self, mock_get_ec, MockRAG, mock_ctx, MockEC):
        """store_result=False returns summary without storing in RAG."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("user_message", "user", "Hi"),
        ]
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context()

        with patch.dict("sys.modules", {"lmstudio": None}):
            from engine.skills.builtin.memory_skills import summarize_chain
            result = summarize_chain("chain-ns", store_result=False)

        assert "not stored" in result
        MockRAG.return_value.add_memory.assert_not_called()

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_compaction_event_logged(self, mock_get_ec, MockRAG, mock_ctx, MockEC):
        """When storing, a memory_compacted event is logged via EventChain."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("user_message", "user", "test"),
        ]
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context()

        ec2_inst = MockEC.return_value

        with patch.dict("sys.modules", {"lmstudio": None}):
            from engine.skills.builtin.memory_skills import summarize_chain
            summarize_chain("chain-log", character_id="char-01")

        ec2_inst.log.assert_called_once()
        log_kwargs = ec2_inst.log.call_args
        assert log_kwargs[0][0] == "memory_stored"
        assert log_kwargs[1]["actor"] == "skill:summarize_chain"
        assert "chain-log" in log_kwargs[1]["payload"]["compacted_chain"]

    @patch("content.simulation.database.events.get_event_chain")
    def test_exception_returns_error(self, mock_get_ec):
        """Top-level exceptions are caught and returned as error text."""
        mock_get_ec.side_effect = RuntimeError("event DB crashed")

        from engine.skills.builtin.memory_skills import summarize_chain
        result = summarize_chain("chain-err")

        assert "Failed to summarize chain chain-err:" in result
        assert "event DB crashed" in result

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_character_id_fallback_to_context(
        self, mock_get_ec, MockRAG, mock_ctx, MockEC
    ):
        """Character ID falls back to chain context when not provided."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("msg", "user", "hi"),
        ]
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context(character_id="ctx-char-99")

        with patch.dict("sys.modules", {"lmstudio": None}):
            from engine.skills.builtin.memory_skills import summarize_chain
            summarize_chain("chain-ctx")  # no character_id arg

        store_kwargs = MockRAG.return_value.add_memory.call_args[1]
        assert store_kwargs["character_id"] == "ctx-char-99"

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_events_without_summary_skipped_in_chain_text(
        self, mock_get_ec, MockRAG, mock_ctx, MockEC
    ):
        """Events with empty summary are excluded from the LLM prompt text."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("user_message", "user", "Has summary"),
            _make_event("internal", "system", ""),  # empty summary
        ]
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context()

        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Summary of events."

        with patch.dict("sys.modules", {"lmstudio": MagicMock()}):
            import sys
            mock_lms = sys.modules["lmstudio"]
            mock_lms.llm.return_value = mock_llm

            from engine.skills.builtin.memory_skills import summarize_chain
            summarize_chain("chain-skip", store_result=False)

        # The prompt sent to LLM should contain only the event with a summary
        prompt_arg = mock_llm.complete.call_args[0][0]
        assert "Has summary" in prompt_arg
        assert "internal (system):" not in prompt_arg

    @patch("content.simulation.database.events.EventChain")
    @patch("engine.skills.chain_context.get_chain_context")
    @patch("content.simulation.database.rag.RAGMemory")
    @patch("content.simulation.database.events.get_event_chain")
    def test_ec_log_exception_suppressed(
        self, mock_get_ec, MockRAG, mock_ctx, MockEC
    ):
        """If the compaction event log fails, the error is suppressed."""
        ec = MagicMock()
        ec.get_chain.return_value = [
            _make_event("msg", "user", "data"),
        ]
        mock_get_ec.return_value = ec
        mock_ctx.return_value = _chain_context()

        # Make EventChain.log raise
        MockEC.return_value.log.side_effect = RuntimeError("log failed")

        with patch.dict("sys.modules", {"lmstudio": None}):
            from engine.skills.builtin.memory_skills import summarize_chain
            result = summarize_chain("chain-logfail", character_id="char-01")

        # Should still succeed — error is suppressed
        assert "Chain summarized and stored" in result
