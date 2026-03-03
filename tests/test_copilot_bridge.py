"""Tests for engine.nexus.copilot_bridge — Copilot CLI self-improvement bridge."""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.integration

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.nexus.copilot_bridge import (
    CopilotBridge,
    SessionMetrics,
    get_copilot_bridge,
)


# ──── Fixtures ────


@pytest.fixture
def mock_nexus():
    """Mock NexusClient with standard method stubs."""
    client = MagicMock()
    client.search.return_value = [
        {"title": "MCP Architecture", "content": "MCP uses tree state management." * 10},
        {"title": "Scene Lifecycle", "content": "Scenes follow BaseScene pattern." * 10},
    ]
    client.find_qa.return_value = None
    client.get_rules.return_value = ["Use Nexus-first", "Mock at boundaries"]
    client.add_qa.return_value = "qa-stored-123"
    client.add_entry.return_value = "entry-456"
    client.log_session.return_value = None
    return client


@pytest.fixture
def mock_router():
    """Mock NLMRouter that returns answers with source tiers."""
    router = MagicMock()

    # Create a realistic RouteResult-like object
    def make_result(answer="NLM answer text", source_tier="nlm"):
        result = MagicMock()
        result.answer = answer
        result.source_tier = source_tier
        result.was_cached = source_tier == "cache"
        return result

    router.route.side_effect = lambda q, **kw: make_result()
    router.savings_report.return_value = {
        "total_queries": 5,
        "savings_pct": 80.0,
        "breakdown": {"cache": 2, "nlm": 2, "llm": 1},
    }
    return router


@pytest.fixture
def mock_forge():
    """Mock KnowledgeForge."""
    forge = MagicMock()

    # analyze() result
    analyze_result = MagicMock()
    analyze_result.notebook_id = "nb-analyze-001"
    analyze_result.qa_pairs = [
        MagicMock(to_dict=MagicMock(return_value={"question": "Q?", "answer": "A."}))
    ]
    analyze_result.errors = []
    forge.analyze.return_value = analyze_result

    # decompose() result
    decompose_result = MagicMock()
    decompose_result.steps = [
        {"step": 1, "action": "Create module"},
        {"step": 2, "action": "Add tests"},
    ]
    decompose_result.errors = []
    forge.decompose.return_value = decompose_result

    return forge


@pytest.fixture
def bridge(mock_nexus, mock_router, mock_forge):
    """CopilotBridge with all dependencies injected."""
    b = CopilotBridge()
    b._nexus = mock_nexus
    b._router = mock_router
    b._forge = mock_forge
    return b


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton between tests."""
    import engine.nexus.copilot_bridge as mod
    mod._bridge = None
    yield
    mod._bridge = None


# ──── SessionMetrics Tests ────


class TestSessionMetrics:
    """Tests for the SessionMetrics dataclass."""

    def test_default_values(self):
        """New metrics start with all counters at zero."""
        m = SessionMetrics()
        assert m.nexus_searches == 0
        assert m.nexus_cache_hits == 0
        assert m.nlm_asks == 0
        assert m.llm_calls == 0
        assert m.tools_used == []
        assert m.files_edited == []
        assert m.decisions_stored == 0
        assert m.qa_pairs_generated == 0

    def test_session_start_is_monotonic(self):
        """Session start timestamp uses monotonic clock."""
        before = time.monotonic()
        m = SessionMetrics()
        after = time.monotonic()
        assert before <= m.session_start <= after

    def test_to_dict_fields(self):
        """to_dict includes all expected keys."""
        m = SessionMetrics()
        d = m.to_dict()
        expected_keys = {
            "duration_seconds", "nexus_searches", "nexus_cache_hits",
            "nlm_asks", "llm_calls", "total_queries", "compute_saved_pct",
            "tools_used", "files_edited", "decisions_stored", "qa_pairs_generated",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_compute_saved_zero_queries(self):
        """Compute saved is 0 when no queries were made."""
        m = SessionMetrics()
        d = m.to_dict()
        assert d["compute_saved_pct"] == 0
        assert d["total_queries"] == 0

    def test_to_dict_compute_saved_all_cached(self):
        """100% saved when all queries hit cache."""
        m = SessionMetrics()
        m.nexus_cache_hits = 10
        d = m.to_dict()
        assert d["total_queries"] == 10
        assert d["compute_saved_pct"] == 100.0

    def test_to_dict_compute_saved_mixed(self):
        """Correct percentage with mix of cache, NLM, and LLM."""
        m = SessionMetrics()
        m.nexus_cache_hits = 3
        m.nlm_asks = 4
        m.llm_calls = 3
        d = m.to_dict()
        assert d["total_queries"] == 10
        # saved = cache(3) + nlm(4) = 7, out of 10 → 70%
        assert d["compute_saved_pct"] == 70.0

    def test_to_dict_duration_positive(self):
        """Duration is positive and measured in seconds."""
        m = SessionMetrics()
        time.sleep(0.01)
        d = m.to_dict()
        assert d["duration_seconds"] >= 0.0

    def test_to_dict_counts_tools_and_files(self):
        """Tool and file counts reflect list lengths."""
        m = SessionMetrics()
        m.tools_used = ["edit", "create", "grep"]
        m.files_edited = ["a.py", "b.py"]
        d = m.to_dict()
        assert d["tools_used"] == 3
        assert d["files_edited"] == 2


# ──── Initialization Tests ────


class TestCopilotBridgeInit:
    """Tests for CopilotBridge initialization."""

    def test_init_creates_fresh_metrics(self):
        """New bridge has fresh SessionMetrics."""
        b = CopilotBridge()
        assert isinstance(b._metrics, SessionMetrics)
        assert b._metrics.nlm_asks == 0

    def test_init_lazy_deps_are_none(self):
        """Dependencies start as None (lazy-loaded)."""
        b = CopilotBridge()
        assert b._nexus is None
        assert b._router is None
        assert b._forge is None

    def test_metrics_property(self, bridge):
        """metrics property exposes SessionMetrics."""
        assert bridge.metrics is bridge._metrics
        assert isinstance(bridge.metrics, SessionMetrics)


# ──── Lazy-Load Tests ────


class TestLazyLoading:
    """Tests for lazy-loading of NexusClient, NLMRouter, KnowledgeForge."""

    def test_get_nexus_returns_cached(self):
        """Second call returns cached instance."""
        b = CopilotBridge()
        cached = MagicMock()
        b._nexus = cached
        result = b._get_nexus()
        assert result is cached

    def test_get_nexus_unavailable_returns_none(self):
        """Nexus import failure returns None gracefully."""
        b = CopilotBridge()
        with patch(
            "engine.nexus.copilot_bridge.CopilotBridge._get_nexus",
            return_value=None,
        ):
            assert b._get_nexus() is None

    def test_get_router_cached(self):
        """Router is cached after first load."""
        b = CopilotBridge()
        mock_router = MagicMock()
        b._router = mock_router
        assert b._get_router() is mock_router

    def test_get_forge_cached(self):
        """Forge is cached after first load."""
        b = CopilotBridge()
        mock_forge = MagicMock()
        b._forge = mock_forge
        assert b._get_forge() is mock_forge


# ──── session_start Tests ────


class TestSessionStart:
    """Tests for session_start() lifecycle method."""

    def test_returns_task_in_context(self, bridge):
        """Context includes the original task description."""
        ctx = bridge.session_start("Add caching")
        assert ctx["task"] == "Add caching"

    def test_empty_task_returns_minimal_context(self, bridge):
        """Empty task skips Nexus searches."""
        ctx = bridge.session_start("")
        assert ctx["task"] == ""
        assert ctx["knowledge"] == []

    def test_searches_nexus_for_knowledge(self, bridge, mock_nexus):
        """Nexus search is called for non-empty task (at least once for task knowledge)."""
        ctx = bridge.session_start("Implement MCP skills")
        # search is called multiple times: once for task knowledge, once for decisions, once for arch overview
        mock_nexus.search.assert_any_call("Implement MCP skills", limit=5)
        assert len(ctx["knowledge"]) == 2
        assert bridge._metrics.nexus_searches >= 1

    def test_knowledge_entries_truncated(self, bridge, mock_nexus):
        """Knowledge content is truncated to 300 chars."""
        long_content = "X" * 500
        mock_nexus.search.return_value = [
            {"title": "Long", "content": long_content}
        ]
        ctx = bridge.session_start("task")
        assert len(ctx["knowledge"][0]["content"]) <= 300

    def test_knowledge_capped_at_five(self, bridge, mock_nexus):
        """At most 5 knowledge entries returned."""
        mock_nexus.search.return_value = [
            {"title": f"Entry {i}", "content": f"Content {i}"} for i in range(10)
        ]
        ctx = bridge.session_start("big search")
        assert len(ctx["knowledge"]) <= 5

    def test_cached_qa_hit(self, bridge, mock_nexus):
        """Cached Q&A answer is included and counts as cache hit."""
        mock_nexus.find_qa.return_value = {"answer": "Use the interceptor pipeline."}
        ctx = bridge.session_start("How to intercept?")
        assert "cached_answer" in ctx
        assert "interceptor" in ctx["cached_answer"]
        assert bridge._metrics.nexus_cache_hits == 1

    def test_cached_qa_miss(self, bridge, mock_nexus):
        """No cached_answer key when Q&A misses."""
        mock_nexus.find_qa.return_value = None
        ctx = bridge.session_start("novel topic")
        assert "cached_answer" not in ctx

    def test_rules_loaded(self, bridge, mock_nexus):
        """Coding rules are loaded into context (session_start loads rules both directly and via onboarding)."""
        ctx = bridge.session_start("write tests")
        # get_rules called multiple times: once for coding in session_start, then for coding/global/copilot in onboarding
        mock_nexus.get_rules.assert_any_call(scope="coding")
        assert ctx["rules"] == ["Use Nexus-first", "Mock at boundaries"]

    def test_resets_metrics(self, bridge):
        """session_start resets metrics for new session."""
        bridge._metrics.nlm_asks = 99
        bridge.session_start("fresh task")
        assert bridge._metrics.nlm_asks == 0

    def test_nexus_unavailable_graceful(self):
        """Works gracefully when Nexus is unavailable."""
        b = CopilotBridge()
        b._nexus = None
        with patch.object(b, "_get_nexus", return_value=None):
            ctx = b.session_start("task")
        assert ctx["task"] == "task"
        assert ctx["knowledge"] == []

    def test_search_exception_caught(self, bridge, mock_nexus):
        """Nexus search exception doesn't crash."""
        mock_nexus.search.side_effect = ConnectionError("offline")
        ctx = bridge.session_start("task")
        assert ctx["knowledge"] == []

    def test_find_qa_exception_caught(self, bridge, mock_nexus):
        """Q&A lookup exception doesn't crash."""
        mock_nexus.find_qa.side_effect = TimeoutError("slow")
        ctx = bridge.session_start("task")
        assert "cached_answer" not in ctx

    def test_rules_exception_caught(self, bridge, mock_nexus):
        """Rules lookup exception doesn't crash."""
        mock_nexus.get_rules.side_effect = RuntimeError("fail")
        ctx = bridge.session_start("task")
        assert "rules" not in ctx


# ──── session_end Tests ────


class TestSessionEnd:
    """Tests for session_end() lifecycle method."""

    def test_returns_metrics(self, bridge):
        """Result contains session metrics."""
        result = bridge.session_end("Done with caching")
        assert "metrics" in result
        assert "duration_seconds" in result["metrics"]

    def test_logs_session(self, bridge, mock_nexus):
        """Session is logged in Nexus."""
        bridge.session_end("Implemented caching")
        mock_nexus.log_session.assert_called_once_with(
            project="CosySim",
            summary="Implemented caching",
        )

    def test_stores_metrics_entry(self, bridge, mock_nexus):
        """Metrics are stored as a Nexus entry."""
        bridge.session_end("session summary")
        mock_nexus.add_entry.assert_called_once()
        call_kwargs = mock_nexus.add_entry.call_args[1]
        assert "Session:" in call_kwargs["title"]
        assert call_kwargs["content_type"] == "history"
        assert call_kwargs["category"] == "sessions"
        assert "copilot" in call_kwargs["tags"]

    def test_default_summary(self, bridge, mock_nexus):
        """Empty summary uses default title."""
        bridge.session_end("")
        call_kwargs = mock_nexus.add_entry.call_args[1]
        assert call_kwargs["title"] == "Copilot Session"

    def test_nexus_unavailable(self):
        """Returns metrics even when Nexus is down."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.session_end("summary")
        assert "metrics" in result

    def test_log_exception_caught(self, bridge, mock_nexus):
        """Log session exception doesn't crash."""
        mock_nexus.log_session.side_effect = RuntimeError("log fail")
        result = bridge.session_end("summary")
        assert "metrics" in result


# ──── pre_plan Tests ────


class TestPrePlan:
    """Tests for pre_plan() — NLM-powered task pre-planning."""

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_generates_questions(self, mock_gen_q, bridge, mock_router):
        """Questions are generated for the task."""
        mock_gen_q.return_value = ["Q1?", "Q2?", "Q3?"]
        result = bridge.pre_plan("Add caching to API", question_count=3)
        mock_gen_q.assert_called_once_with(
            "Add caching to API", category="plan", count=3, subject="Add caching to API"[:50]
        )
        assert result["task"] == "Add caching to API"

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_routes_questions_through_nlm(self, mock_gen_q, bridge, mock_router):
        """Each question is routed via the NLM router."""
        mock_gen_q.return_value = ["Q1?", "Q2?"]
        bridge.pre_plan("task")
        assert mock_router.route.call_count == 2

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_qa_pairs_in_result(self, mock_gen_q, bridge, mock_router):
        """Result contains Q&A pairs from routing."""
        mock_gen_q.return_value = ["Q1?"]
        result = bridge.pre_plan("task")
        assert len(result["qa_pairs"]) == 1
        assert result["qa_pairs"][0]["question"] == "Q1?"
        assert result["qa_pairs"][0]["answer"] == "NLM answer text"
        assert result["qa_pairs"][0]["source"] == "nlm"

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_answer_truncated_to_500(self, mock_gen_q, bridge, mock_router):
        """Answers are truncated to 500 characters."""
        long_answer = "A" * 1000
        route_result = MagicMock()
        route_result.answer = long_answer
        route_result.source_tier = "nlm"
        mock_router.route.return_value = route_result
        mock_gen_q.return_value = ["Q?"]

        result = bridge.pre_plan("task")
        assert len(result["qa_pairs"][0]["answer"]) <= 500

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_cache_hit_tracks_metric(self, mock_gen_q, bridge, mock_router):
        """Cache hits increment nexus_cache_hits."""
        route_result = MagicMock()
        route_result.answer = "cached"
        route_result.source_tier = "cache"
        mock_router.route.side_effect = None
        mock_router.route.return_value = route_result
        mock_gen_q.return_value = ["Q?"]

        bridge.pre_plan("task")
        assert bridge._metrics.nexus_cache_hits == 1

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_fts_hit_tracks_metric(self, mock_gen_q, bridge, mock_router):
        """FTS hits increment nexus_cache_hits."""
        route_result = MagicMock()
        route_result.answer = "from fts"
        route_result.source_tier = "fts"
        mock_router.route.side_effect = None
        mock_router.route.return_value = route_result
        mock_gen_q.return_value = ["Q?"]

        bridge.pre_plan("task")
        assert bridge._metrics.nexus_cache_hits == 1

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_nlm_hit_tracks_metric(self, mock_gen_q, bridge, mock_router):
        """NLM answers increment nlm_asks."""
        mock_gen_q.return_value = ["Q?"]
        bridge.pre_plan("task")
        assert bridge._metrics.nlm_asks == 1

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_llm_fallback_tracks_metric(self, mock_gen_q, bridge, mock_router):
        """LLM fallback increments llm_calls."""
        route_result = MagicMock()
        route_result.answer = "llm fallback"
        route_result.source_tier = "llm"
        mock_router.route.side_effect = None
        mock_router.route.return_value = route_result
        mock_gen_q.return_value = ["Q?"]

        bridge.pre_plan("task")
        assert bridge._metrics.llm_calls == 1

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_tracks_qa_pairs_generated(self, mock_gen_q, bridge, mock_router):
        """qa_pairs_generated metric reflects answered questions."""
        mock_gen_q.return_value = ["Q1?", "Q2?", "Q3?"]
        bridge.pre_plan("task")
        assert bridge._metrics.qa_pairs_generated == 3

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_skips_empty_answers(self, mock_gen_q, bridge, mock_router):
        """Questions with empty answers are skipped."""
        route_result = MagicMock()
        route_result.answer = ""
        route_result.source_tier = "none"
        mock_router.route.side_effect = None
        mock_router.route.return_value = route_result
        mock_gen_q.return_value = ["Q?"]

        result = bridge.pre_plan("task")
        assert len(result["qa_pairs"]) == 0

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_router_unavailable(self, mock_gen_q, bridge):
        """Returns error when router is unavailable."""
        bridge._router = None
        with patch.object(bridge, "_get_router", return_value=None):
            mock_gen_q.return_value = ["Q?"]
            result = bridge.pre_plan("task")
        assert "error" in result
        assert "unavailable" in result["error"].lower()


# ──── analyze_files Tests ────


class TestAnalyzeFiles:
    """Tests for analyze_files() — NLM source analysis."""

    def test_returns_insights(self, bridge, mock_forge):
        """Returns notebook_id and insights from forge."""
        result = bridge.analyze_files(["src/engine/mcp.py"])
        assert result["notebook_id"] == "nb-analyze-001"
        assert len(result["insights"]) == 1
        assert result["errors"] == []

    def test_passes_questions(self, bridge, mock_forge):
        """Custom questions are forwarded to forge."""
        bridge.analyze_files(
            ["src/a.py"], questions=["What pattern is used?"]
        )
        mock_forge.analyze.assert_called_once_with(
            ["src/a.py"], questions=["What pattern is used?"]
        )

    def test_multiple_files(self, bridge, mock_forge):
        """Multiple file paths are passed to forge."""
        bridge.analyze_files(["a.py", "b.py", "c.py"])
        call_args = mock_forge.analyze.call_args[0][0]
        assert call_args == ["a.py", "b.py", "c.py"]

    def test_forge_unavailable(self):
        """Returns error dict when forge is unavailable."""
        b = CopilotBridge()
        with patch.object(b, "_get_forge", return_value=None):
            result = b.analyze_files(["file.py"])
        assert "error" in result
        assert "unavailable" in result["error"].lower()

    def test_no_questions_passed(self, bridge, mock_forge):
        """Works without explicit questions."""
        bridge.analyze_files(["src/x.py"])
        call_kwargs = mock_forge.analyze.call_args[1]
        assert call_kwargs["questions"] is None


# ──── get_guide Tests ────


class TestGetGuide:
    """Tests for get_guide() — NLM implementation guides."""

    def test_returns_steps(self, bridge, mock_forge):
        """Guide contains decomposed steps."""
        result = bridge.get_guide("Add caching layer", notebook_id="nb-1")
        assert result["step_count"] == 2
        assert result["steps"][0]["step"] == 1
        assert result["errors"] == []

    def test_uses_provided_notebook(self, bridge, mock_forge):
        """Existing notebook_id skips file upload."""
        bridge.get_guide("Plan", notebook_id="nb-existing")
        mock_forge.decompose.assert_called_once_with(
            "Plan", notebook_id="nb-existing"
        )

    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_creates_notebook_from_files(self, mock_get_engine, bridge, mock_forge):
        """Creates notebook from files when no notebook_id provided."""
        mock_engine = MagicMock()
        mock_engine.create_from_files.return_value = {"notebook_id": "nb-new-789"}
        mock_get_engine.return_value = mock_engine

        bridge.get_guide("Plan", files=["a.py", "b.py"])
        mock_engine.create_from_files.assert_called_once()
        mock_forge.decompose.assert_called_once_with(
            "Plan", notebook_id="nb-new-789"
        )

    def test_forge_unavailable(self):
        """Returns error when forge is unavailable."""
        b = CopilotBridge()
        with patch.object(b, "_get_forge", return_value=None):
            result = b.get_guide("Plan")
        assert "error" in result

    @patch("engine.nexus.nlm_engine.get_nlm_engine")
    def test_notebook_creation_failure(self, mock_get_engine, bridge, mock_forge):
        """Handles notebook creation returning no notebook_id."""
        mock_engine = MagicMock()
        mock_engine.create_from_files.return_value = {}
        mock_get_engine.return_value = mock_engine

        bridge.get_guide("Plan", files=["a.py"])
        # decompose still called with empty notebook_id
        mock_forge.decompose.assert_called_once_with("Plan", notebook_id="")


# ──── track_tool_use Tests ────


class TestTrackToolUse:
    """Tests for track_tool_use() — tool usage tracking."""

    def test_appends_tool_name(self, bridge):
        """Tool name is appended to tools_used list."""
        bridge.track_tool_use("grep")
        bridge.track_tool_use("view")
        assert bridge._metrics.tools_used == ["grep", "view"]

    def test_tracks_edit_file(self, bridge):
        """Edit tool records the file path."""
        bridge.track_tool_use("edit", {"path": "src/main.py"})
        assert "src/main.py" in bridge._metrics.files_edited

    def test_tracks_create_file(self, bridge):
        """Create tool records the file path."""
        bridge.track_tool_use("create", {"path": "tests/test_new.py"})
        assert "tests/test_new.py" in bridge._metrics.files_edited

    def test_no_duplicate_files(self, bridge):
        """Same file edited twice is only recorded once."""
        bridge.track_tool_use("edit", {"path": "a.py"})
        bridge.track_tool_use("edit", {"path": "a.py"})
        assert bridge._metrics.files_edited.count("a.py") == 1

    def test_non_edit_tool_no_file(self, bridge):
        """Non-edit tools don't add to files_edited."""
        bridge.track_tool_use("grep", {"path": "src/x.py"})
        assert bridge._metrics.files_edited == []

    def test_no_params(self, bridge):
        """Tool tracking works without params."""
        bridge.track_tool_use("view")
        assert "view" in bridge._metrics.tools_used
        assert bridge._metrics.files_edited == []

    def test_empty_path_ignored(self, bridge):
        """Edit with empty path doesn't add to files_edited."""
        bridge.track_tool_use("edit", {"path": ""})
        assert bridge._metrics.files_edited == []


# ──── track_error Tests ────


class TestTrackError:
    """Tests for track_error() — error pattern tracking."""

    def test_appends_error_marker(self, bridge):
        """Error is recorded with ERROR: prefix."""
        bridge.track_error("grep", "file not found")
        assert "ERROR:grep" in bridge._metrics.tools_used

    def test_stores_error_in_nexus(self, bridge, mock_nexus):
        """Error is stored as a Nexus entry."""
        bridge.track_error("build", "compilation failed")
        mock_nexus.add_entry.assert_called_once()
        call_args = mock_nexus.add_entry.call_args
        assert "build" in call_args[0][0]
        assert "compilation failed" in call_args[0][1]
        assert call_args[1]["content_type"] == "memory"
        assert call_args[1]["category"] == "debugging"

    def test_nexus_unavailable_no_crash(self):
        """Error tracking works even without Nexus."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            b.track_error("tool", "error msg")
        assert "ERROR:tool" in b._metrics.tools_used

    def test_nexus_exception_swallowed(self, bridge, mock_nexus):
        """Nexus storage exception doesn't propagate."""
        mock_nexus.add_entry.side_effect = RuntimeError("storage full")
        bridge.track_error("tool", "msg")  # should not raise
        assert "ERROR:tool" in bridge._metrics.tools_used


# ──── store_decision Tests ────


class TestStoreDecision:
    """Tests for store_decision() — design decision storage."""

    def test_stores_in_nexus(self, bridge, mock_nexus):
        """Decision is stored as a Nexus note entry."""
        entry_id = bridge.store_decision("Use Redis", "For caching layer")
        assert entry_id == "entry-456"
        call_kwargs = mock_nexus.add_entry.call_args[1]
        assert "Decision: Use Redis" == call_kwargs["title"]
        assert call_kwargs["content"] == "For caching layer"
        assert call_kwargs["content_type"] == "note"
        assert "decision" in call_kwargs["tags"]

    def test_increments_decisions_stored(self, bridge):
        """Decisions stored counter is incremented."""
        bridge.store_decision("D1", "Content 1")
        bridge.store_decision("D2", "Content 2")
        assert bridge._metrics.decisions_stored == 2

    def test_custom_category(self, bridge, mock_nexus):
        """Custom category is passed through."""
        bridge.store_decision("T", "C", category="performance")
        call_kwargs = mock_nexus.add_entry.call_args[1]
        assert call_kwargs["category"] == "performance"

    def test_nexus_unavailable_returns_none(self):
        """Returns None when Nexus is down."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.store_decision("T", "C")
        assert result is None

    def test_nexus_exception_returns_none(self, bridge, mock_nexus):
        """Returns None on Nexus exception."""
        mock_nexus.add_entry.side_effect = ConnectionError("offline")
        result = bridge.store_decision("T", "C")
        assert result is None
        # counter not incremented on failure
        assert bridge._metrics.decisions_stored == 0


# ──── post_session Tests ────


class TestPostSession:
    """Tests for post_session() — post-session distillation."""

    def test_stores_decisions(self, bridge, mock_nexus):
        """Each decision is stored in Nexus."""
        decisions = [
            {"title": "Use Redis", "content": "For caching", "category": "arch"},
            {"title": "Use pytest", "content": "For testing"},
        ]
        result = bridge.post_session("Completed caching", decisions=decisions)
        assert len(result["stored"]) == 2

    def test_returns_metrics(self, bridge):
        """Result includes session metrics."""
        result = bridge.post_session("Done")
        assert "metrics" in result
        assert "duration_seconds" in result["metrics"]

    def test_calls_session_end(self, bridge, mock_nexus):
        """post_session triggers session_end internally."""
        bridge.post_session("summary")
        mock_nexus.log_session.assert_called_once()

    def test_nexus_unavailable(self):
        """Returns error and metrics when Nexus is down."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.post_session("summary")
        assert "error" in result
        assert "metrics" in result

    def test_no_decisions(self, bridge):
        """Works fine with no decisions to store."""
        result = bridge.post_session("summary", decisions=None)
        assert result["stored"] == []

    def test_empty_decisions_list(self, bridge):
        """Empty decisions list produces no stored entries."""
        result = bridge.post_session("summary", decisions=[])
        assert result["stored"] == []

    def test_decision_with_missing_title(self, bridge, mock_nexus):
        """Decision missing title uses default."""
        decisions = [{"content": "some content"}]
        bridge.post_session("summary", decisions=decisions)
        # store_decision is called with the default "Untitled Decision"
        call_kwargs = mock_nexus.add_entry.call_args_list[0][1]
        assert "Untitled Decision" in call_kwargs["title"]

    def test_partial_decision_failure(self, bridge, mock_nexus):
        """Continues storing even if one decision fails."""
        # First add_entry call (for decision) succeeds, second call (decision) fails,
        # third call is the session metrics entry
        mock_nexus.add_entry.side_effect = [
            "entry-1",
            ConnectionError("fail"),
            "entry-3",
        ]
        decisions = [
            {"title": "D1", "content": "C1"},
            {"title": "D2", "content": "C2"},
        ]
        result = bridge.post_session("summary", decisions=decisions)
        # Only first succeeds
        assert "entry-1" in result["stored"]
        assert len(result["stored"]) == 1


# ──── generate_questions Tests ────


class TestGenerateQuestions:
    """Tests for generate_questions() — auto-question generation."""

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_returns_list_of_strings(self, mock_gen_q, bridge):
        """Returns a list of question strings."""
        mock_gen_q.return_value = ["Q1?", "Q2?", "Q3?"]
        result = bridge.generate_questions("MCP Framework", count=3)
        assert result == ["Q1?", "Q2?", "Q3?"]

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_passes_category(self, mock_gen_q, bridge):
        """Category parameter is forwarded."""
        mock_gen_q.return_value = []
        bridge.generate_questions("topic", count=5, category="code")
        mock_gen_q.assert_called_once_with(
            "topic", category="code", count=5, subject="topic"[:50]
        )

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_default_count_fifteen(self, mock_gen_q, bridge):
        """Default count is 15."""
        mock_gen_q.return_value = ["Q?"] * 15
        bridge.generate_questions("topic")
        mock_gen_q.assert_called_once_with(
            "topic", category="topic", count=15, subject="topic"[:50]
        )

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_subject_truncated(self, mock_gen_q, bridge):
        """Long topics are truncated to 50 chars for subject."""
        long_topic = "A" * 100
        mock_gen_q.return_value = []
        bridge.generate_questions(long_topic, count=1)
        mock_gen_q.assert_called_once_with(
            long_topic, category="topic", count=1, subject=long_topic[:50]
        )


# ──── get_savings_report Tests ────


class TestGetSavingsReport:
    """Tests for get_savings_report() — compute savings metrics."""

    def test_includes_session_metrics(self, bridge):
        """Report contains standard SessionMetrics fields."""
        report = bridge.get_savings_report()
        assert "duration_seconds" in report
        assert "compute_saved_pct" in report
        assert "total_queries" in report

    def test_includes_router_savings(self, bridge, mock_router):
        """Router savings are merged into report."""
        report = bridge.get_savings_report()
        assert "router_savings" in report
        assert report["router_savings"]["savings_pct"] == 80.0
        mock_router.savings_report.assert_called_once()

    def test_no_router_no_crash(self):
        """Works without router (no router_savings key)."""
        b = CopilotBridge()
        with patch.object(b, "_get_router", return_value=None):
            report = b.get_savings_report()
        assert "router_savings" not in report
        assert "duration_seconds" in report

    def test_reflects_accumulated_metrics(self, bridge):
        """Report reflects metrics accumulated during session."""
        bridge._metrics.nexus_cache_hits = 5
        bridge._metrics.nlm_asks = 3
        bridge._metrics.llm_calls = 2
        report = bridge.get_savings_report()
        assert report["total_queries"] == 10
        assert report["compute_saved_pct"] == 80.0

    def test_all_cache_hits_savings(self, bridge):
        """100% savings when everything hits cache."""
        bridge._metrics.nexus_cache_hits = 20
        report = bridge.get_savings_report()
        assert report["compute_saved_pct"] == 100.0

    def test_all_llm_calls_no_savings(self, bridge):
        """0% savings when everything goes to LLM."""
        bridge._metrics.llm_calls = 10
        bridge._metrics.nexus_cache_hits = 0
        bridge._metrics.nlm_asks = 0
        report = bridge.get_savings_report()
        assert report["compute_saved_pct"] == 0.0


# ──── Singleton Tests ────


class TestGetCopilotBridge:
    """Tests for get_copilot_bridge() singleton."""

    def test_returns_copilot_bridge(self):
        """Singleton returns a CopilotBridge instance."""
        with patch("engine.nexus.copilot_bridge.CopilotBridge") as MockBridge:
            MockBridge.return_value = MagicMock(spec=CopilotBridge)
            bridge = get_copilot_bridge()
            assert bridge is not None

    def test_returns_same_instance(self):
        """Repeated calls return the same instance."""
        with patch("engine.nexus.copilot_bridge.CopilotBridge") as MockBridge:
            instance = MagicMock(spec=CopilotBridge)
            MockBridge.return_value = instance
            b1 = get_copilot_bridge()
            b2 = get_copilot_bridge()
            assert b1 is b2
            # Constructor only called once
            assert MockBridge.call_count == 1


# ──── Integration-Style Tests ────


class TestPrePlanIntegration:
    """Integration-style tests for multi-step pre_plan workflows."""

    @patch("engine.nexus.knowledge_forge.generate_questions")
    def test_mixed_source_tiers(self, mock_gen_q, bridge, mock_router):
        """pre_plan correctly tracks mixed source tiers."""
        answers = [
            ("cached answer", "cache"),
            ("fts answer", "fts"),
            ("nlm answer", "nlm"),
            ("llm answer", "llm"),
        ]
        call_idx = [0]

        def route_side_effect(q, **kw):
            r = MagicMock()
            r.answer, r.source_tier = answers[call_idx[0] % len(answers)]
            call_idx[0] += 1
            return r

        mock_router.route.side_effect = route_side_effect
        mock_gen_q.return_value = ["Q1?", "Q2?", "Q3?", "Q4?"]

        result = bridge.pre_plan("big task", question_count=4)

        assert len(result["qa_pairs"]) == 4
        assert bridge._metrics.nexus_cache_hits == 2  # cache + fts
        assert bridge._metrics.nlm_asks == 1
        assert bridge._metrics.llm_calls == 1
        assert bridge._metrics.qa_pairs_generated == 4


class TestFullSessionLifecycle:
    """Test full session lifecycle: start → work → end."""

    def test_full_lifecycle(self, bridge, mock_nexus):
        """Complete session lifecycle updates all metrics."""
        # Start
        ctx = bridge.session_start("Add caching")
        assert "knowledge" in ctx

        # Track tool usage
        bridge.track_tool_use("edit", {"path": "cache.py"})
        bridge.track_tool_use("grep")
        bridge.track_tool_use("edit", {"path": "tests.py"})

        # Track an error
        bridge.track_error("build", "syntax error")

        # Store a decision
        bridge.store_decision("Use Redis", "For distributed caching")

        # End session
        result = bridge.post_session(
            "Implemented Redis caching",
            decisions=[{"title": "TTL strategy", "content": "1 hour TTL"}],
        )

        # Verify accumulated metrics
        assert "metrics" in result
        metrics = result["metrics"]
        assert metrics["tools_used"] >= 3  # edit, grep, edit + ERROR:build
        assert metrics["files_edited"] == 2  # cache.py, tests.py
        assert metrics["decisions_stored"] >= 1

    def test_track_multiple_unique_files(self, bridge):
        """Track unique files across many edit operations."""
        for i in range(5):
            bridge.track_tool_use("edit", {"path": f"file_{i}.py"})
        # Duplicate
        bridge.track_tool_use("edit", {"path": "file_0.py"})

        assert len(bridge._metrics.files_edited) == 5


# ──── consensus_gate Tests ────


class TestConsensusGate:
    """Tests for consensus_gate() — governance enforcement before operations."""

    def test_allowed_by_default_when_nexus_down(self):
        """Returns True (allow) when Nexus is unavailable."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.consensus_gate("arch-change", "Restructure MCP")
        assert result is True

    def test_allowed_when_no_blocking_rules(self, bridge, mock_nexus):
        """Returns True when no blocking rules are found."""
        mock_nexus.get_rules.return_value = [{"title": "Use types", "content": "Add hints"}]
        result = bridge.consensus_gate("minor-edit", "Add a docstring")
        assert result is True

    def test_blocked_when_deny_rule_present(self, bridge, mock_nexus):
        """Returns False when a 'deny' rule is found for the operation."""
        mock_nexus.get_rules.return_value = [
            {"title": "No direct schema changes", "content": "block: schema modifications"}
        ]
        result = bridge.consensus_gate("arch-change", "Remove MCP tree")
        assert result is False

    def test_stores_gate_check_in_nexus(self, bridge, mock_nexus):
        """Gate check result is stored as a copilot-decisions entry."""
        mock_nexus.get_rules.return_value = []
        bridge.consensus_gate("rule-change", "Add new rule")
        # add_entry should be called for the gate check
        assert mock_nexus.add_entry.called
        call_kwargs = mock_nexus.add_entry.call_args[1]
        assert call_kwargs["category"] == "copilot-decisions"
        assert "gate" in call_kwargs["tags"]

    def test_rules_exception_allows(self, bridge, mock_nexus):
        """Exception during rule check allows the operation (fail-open)."""
        mock_nexus.get_rules.side_effect = RuntimeError("Nexus down")
        result = bridge.consensus_gate("config-change", "Update config")
        assert result is True


# ──── get_onboarding_context Tests ────


class TestGetOnboardingContext:
    """Tests for get_onboarding_context() — loads full context at session start."""

    def test_returns_dict_with_all_keys(self, bridge, mock_nexus):
        """Returns dict with rules, decisions, architecture_overview, active_todos."""
        with patch.object(bridge, "get_decision_history", return_value=[]):
            with patch("engine.nexus.task_scheduler.get_task_scheduler", side_effect=ImportError):
                result = bridge.get_onboarding_context()
        assert "rules" in result
        assert "recent_decisions" in result
        assert "architecture_overview" in result
        assert "active_todos" in result

    def test_loads_coding_rules(self, bridge, mock_nexus):
        """Coding rules are loaded from Nexus."""
        mock_nexus.get_rules.return_value = ["Use absolute imports", "No print()"]
        with patch.object(bridge, "get_decision_history", return_value=[]):
            with patch("engine.nexus.task_scheduler.get_task_scheduler", side_effect=ImportError):
                result = bridge.get_onboarding_context()
        assert len(result["rules"]) > 0

    def test_nexus_unavailable_returns_error(self):
        """Returns error key when Nexus is down."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.get_onboarding_context()
        assert "error" in result

    def test_architecture_search_performed(self, bridge, mock_nexus):
        """Nexus is searched for architecture overview."""
        mock_nexus.search.return_value = [
            {"title": "Architecture", "content": "MCP tree manages state"}
        ]
        with patch.object(bridge, "get_decision_history", return_value=[]):
            with patch("engine.nexus.task_scheduler.get_task_scheduler", side_effect=ImportError):
                result = bridge.get_onboarding_context()
        assert "MCP tree" in result["architecture_overview"]


# ──── get_decision_history Tests ────


class TestGetDecisionHistory:
    """Tests for get_decision_history() — retrieves past architectural decisions."""

    def test_returns_list(self, bridge, mock_nexus):
        """Returns a list of decision dicts."""
        mock_nexus.search.return_value = [
            {"title": "Decision: Use FTS5", "content": "FTS5 for search.", "category": "architecture"}
        ]
        mock_nexus.find_qa.return_value = None
        result = bridge.get_decision_history("search")
        assert isinstance(result, list)

    def test_filters_to_decision_categories(self, bridge, mock_nexus):
        """Only entries with decision/architecture/copilot categories are included."""
        mock_nexus.search.return_value = [
            {"title": "Decision: Use Redis", "content": "Redis for cache.", "category": "architecture"},
            {"title": "Random entry", "content": "Some note.", "category": "general"},
        ]
        mock_nexus.find_qa.return_value = None
        result = bridge.get_decision_history("cache")
        titles = [d["title"] for d in result]
        assert "Decision: Use Redis" in titles
        assert "Random entry" not in titles

    def test_increments_nexus_searches(self, bridge, mock_nexus):
        """Nexus searches counter is incremented."""
        mock_nexus.search.return_value = []
        mock_nexus.find_qa.return_value = None
        initial = bridge._metrics.nexus_searches
        bridge.get_decision_history("topic")
        assert bridge._metrics.nexus_searches == initial + 1

    def test_nexus_unavailable_returns_empty(self):
        """Returns empty list when Nexus is unavailable."""
        b = CopilotBridge()
        with patch.object(b, "_get_nexus", return_value=None):
            result = b.get_decision_history("anything")
        assert result == []

    def test_respects_n_limit(self, bridge, mock_nexus):
        """Returned list is capped at n entries."""
        mock_nexus.search.return_value = [
            {"title": f"D{i}", "content": "c", "category": "architecture"}
            for i in range(10)
        ]
        mock_nexus.find_qa.return_value = None
        result = bridge.get_decision_history("arch", n=3)
        assert len(result) <= 3

    def test_includes_qa_cache_results(self, bridge, mock_nexus):
        """Q&A cache hits are appended as decisions."""
        mock_nexus.search.return_value = []
        mock_nexus.find_qa.return_value = {
            "question": "How does NLM routing work?",
            "answer": "4-tier pipeline: cache → FTS → NLM → LLM",
        }
        result = bridge.get_decision_history("nlm routing")
        sources = [d.get("source") for d in result]
        assert "qa_cache" in sources

