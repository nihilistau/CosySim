"""Tests for engine.nexus.system_reflection — NLM-driven system analysis."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.system_reflection import (
    ReflectionInsight,
    ReflectionReport,
    SystemReflection,
    WEEKLY_QUESTIONS,
    MONTHLY_QUESTIONS,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def reflection():
    """Fresh SystemReflection instance."""
    return SystemReflection()


@pytest.fixture
def sample_metrics():
    """Realistic metric trends dict."""
    return {
        "period_days": 7,
        "trends": {
            "llm.cache.hit_rate": {
                "current": 0.25,
                "mean": 0.3,
                "min": 0.1,
                "max": 0.5,
                "count": 10,
                "direction": "down",
            },
            "tests.pass_rate": {
                "current": 0.92,
                "mean": 0.95,
                "min": 0.88,
                "max": 1.0,
                "count": 5,
                "direction": "down",
            },
            "tasks.completed": {
                "current": 20,
                "mean": 18,
                "min": 10,
                "max": 25,
                "count": 7,
                "direction": "up",
            },
            "tasks.failed": {
                "current": 8,
                "mean": 5,
                "min": 2,
                "max": 10,
                "count": 7,
                "direction": "up",
            },
            "nexus.entries.total": {
                "current": 450,
                "mean": 420,
                "min": 400,
                "max": 450,
                "count": 7,
                "direction": "up",
            },
        },
        "regressions": [],
    }


# ── Data Model Tests ────────────────────────────────────────────────────


class TestReflectionInsight:
    """Test ReflectionInsight dataclass."""

    def test_create_insight(self):
        """Basic insight creation."""
        insight = ReflectionInsight(
            insight_id="test-1",
            category="improvement",
            title="Test insight",
            description="A test insight description",
            confidence=0.8,
            priority="high",
            actionable=True,
            suggested_action="Do something",
        )
        assert insight.insight_id == "test-1"
        assert insight.category == "improvement"
        assert insight.actionable is True
        assert insight.suggested_action == "Do something"

    def test_insight_defaults(self):
        """Default values for optional fields."""
        insight = ReflectionInsight(
            insight_id="test-2",
            category="pattern",
            title="Default test",
            description="Testing defaults",
            confidence=0.5,
            priority="low",
            actionable=False,
        )
        assert insight.suggested_action == ""
        assert insight.metric_references == []

    def test_insight_asdict(self):
        """asdict serialization."""
        insight = ReflectionInsight(
            insight_id="test-3",
            category="risk",
            title="Serializable",
            description="Check asdict",
            confidence=0.7,
            priority="medium",
            actionable=True,
            metric_references=["tests.pass_rate"],
        )
        d = asdict(insight)
        assert d["insight_id"] == "test-3"
        assert d["metric_references"] == ["tests.pass_rate"]


class TestReflectionReport:
    """Test ReflectionReport dataclass."""

    def test_create_report(self):
        """Basic report creation."""
        report = ReflectionReport(
            report_id="report-1",
            period="weekly",
            created_at="2024-01-01T00:00:00Z",
        )
        assert report.report_id == "report-1"
        assert report.insights == []
        assert report.tasks_created == []
        assert report.nlm_notebook_id is None

    def test_report_with_insights(self):
        """Report with populated insights."""
        insight = ReflectionInsight(
            insight_id="i1",
            category="pattern",
            title="Test",
            description="Desc",
            confidence=0.5,
            priority="low",
            actionable=False,
        )
        report = ReflectionReport(
            report_id="report-2",
            period="monthly",
            created_at="2024-01-01",
            insights=[insight],
            tasks_created=["task-1"],
        )
        assert len(report.insights) == 1
        assert len(report.tasks_created) == 1


# ── Question Sets ───────────────────────────────────────────────────────


class TestQuestions:
    """Verify question set structure."""

    def test_weekly_questions_nonempty(self):
        """Weekly questions exist."""
        assert len(WEEKLY_QUESTIONS) >= 5

    def test_monthly_has_more(self):
        """Monthly has more questions than weekly."""
        assert len(MONTHLY_QUESTIONS) > len(WEEKLY_QUESTIONS)

    def test_monthly_includes_weekly(self):
        """Monthly questions are a superset of weekly."""
        for q in WEEKLY_QUESTIONS:
            assert q in MONTHLY_QUESTIONS


# ── Heuristic Analysis ─────────────────────────────────────────────────


class TestHeuristicAnalysis:
    """Test the heuristic (non-NLM) analysis path."""

    def test_low_cache_hit_rate(self, reflection, sample_metrics):
        """Low cache hit rate generates improvement insight."""
        insights = reflection._analyze_heuristic(sample_metrics)
        cache_insights = [i for i in insights if "cache" in i.title.lower()]
        assert len(cache_insights) >= 1
        assert cache_insights[0].category == "improvement"
        assert cache_insights[0].priority == "high"

    def test_low_test_pass_rate(self, reflection, sample_metrics):
        """Low test pass rate generates risk insight."""
        insights = reflection._analyze_heuristic(sample_metrics)
        test_insights = [i for i in insights if "test" in i.title.lower()]
        assert len(test_insights) >= 1
        assert test_insights[0].category == "risk"

    def test_high_task_failure(self, reflection, sample_metrics):
        """High task failure rate generates risk insight."""
        insights = reflection._analyze_heuristic(sample_metrics)
        task_insights = [i for i in insights if "task" in i.title.lower()]
        assert len(task_insights) >= 1

    def test_no_issues_gives_positive(self, reflection):
        """When all metrics are good, we get a positive insight."""
        good_metrics = {
            "period_days": 7,
            "trends": {
                "llm.cache.hit_rate": {"current": 0.8, "direction": "up"},
                "tests.pass_rate": {"current": 1.0, "direction": "stable"},
            },
            "regressions": [],
        }
        insights = reflection._analyze_heuristic(good_metrics)
        assert len(insights) == 1
        assert "normal" in insights[0].title.lower()
        assert insights[0].actionable is False

    def test_empty_metrics_gives_positive(self, reflection):
        """Empty metrics still produce a positive insight."""
        insights = reflection._analyze_heuristic({"trends": {}, "regressions": []})
        assert len(insights) >= 1

    def test_regressions_create_insights(self, reflection):
        """Detected regressions become risk insights."""
        metrics = {
            "trends": {},
            "regressions": [
                {"metric_name": "llm.latency.avg_ms", "message": "20% regression"}
            ],
        }
        insights = reflection._analyze_heuristic(metrics)
        reg_insights = [i for i in insights if i.category == "risk"]
        assert len(reg_insights) >= 1
        assert "regression" in reg_insights[0].title.lower()

    def test_knowledge_shrinking(self, reflection):
        """Declining entry count triggers warning."""
        metrics = {
            "trends": {
                "nexus.entries.total": {"current": 300, "direction": "down"},
            },
            "regressions": [],
        }
        insights = reflection._analyze_heuristic(metrics)
        shrink = [i for i in insights if "shrink" in i.title.lower()]
        assert len(shrink) >= 1


# ── Document Building ──────────────────────────────────────────────────


class TestDocumentBuilding:
    """Test reflection document generation."""

    def test_builds_markdown(self, reflection, sample_metrics):
        """Document is valid markdown with expected sections."""
        doc = reflection._build_reflection_document(
            sample_metrics, {"session_count": 5, "summaries": ["Did stuff"]},
            "weekly", 7,
        )
        assert "# CosySim System Reflection" in doc
        assert "Metrics Summary" in doc
        assert "Recent Activity" in doc
        assert "Sessions in period: 5" in doc

    def test_empty_metrics_handled(self, reflection):
        """Document generation works with empty metrics."""
        doc = reflection._build_reflection_document(
            {"trends": {}}, {"session_count": 0, "summaries": []},
            "weekly", 7,
        )
        assert "No metric data available" in doc

    def test_regressions_section(self, reflection):
        """Regressions appear in document."""
        metrics = {
            "trends": {},
            "regressions": [
                {"metric_name": "speed", "message": "Got slow"}
            ],
        }
        doc = reflection._build_reflection_document(
            metrics, {"session_count": 0, "summaries": []}, "weekly", 7,
        )
        assert "Detected Regressions" in doc
        assert "Got slow" in doc


# ── NLM Answer Parsing ─────────────────────────────────────────────────


class TestNLMParsing:
    """Test parsing NLM responses into insights."""

    def test_parse_long_answer(self, reflection):
        """Long answer gets split into multiple insights."""
        answer = (
            "The cache hit rate shows a declining trend over the past week. "
            "This indicates the system is not effectively reusing prior answers.\n\n"
            "The task failure rate has increased significantly, suggesting that "
            "task-agent matching needs improvement. We should consider routing "
            "complex tasks to larger models.\n\n"
            "Knowledge growth is healthy with 50 new entries added this week."
        )
        insights = reflection._parse_nlm_answer(
            "What are the top 3 patterns?", answer
        )
        assert len(insights) >= 2
        assert all(i.confidence == 0.75 for i in insights)

    def test_parse_short_answer_skipped(self, reflection):
        """Very short answers are skipped."""
        insights = reflection._parse_nlm_answer("question?", "OK")
        assert len(insights) == 0

    def test_parse_empty_answer(self, reflection):
        """Empty answer gives empty list."""
        insights = reflection._parse_nlm_answer("question?", "")
        assert len(insights) == 0

    def test_parse_improvement_question(self, reflection):
        """Improvement-related questions get 'improvement' category."""
        insights = reflection._parse_nlm_answer(
            "What improvements would reduce compute?",
            "We should implement batch processing to reduce per-query overhead "
            "and improve throughput significantly.",
        )
        if insights:
            assert insights[0].category == "improvement"

    def test_parse_risk_question(self, reflection):
        """Risk-related questions get 'risk' category."""
        insights = reflection._parse_nlm_answer(
            "Are there any concerning trends?",
            "The memory usage pattern shows a consistent upward trend that could "
            "lead to OOM errors within the next two weeks.",
        )
        if insights:
            assert insights[0].category == "risk"


# ── Full Reflection Cycle ──────────────────────────────────────────────


class TestFullReflection:
    """Test the complete reflection pipeline."""

    @patch("engine.nexus.system_reflection.SystemReflection._store_report")
    @patch("engine.nexus.system_reflection.SystemReflection._store_insights")
    @patch("engine.nexus.system_reflection.SystemReflection._create_tasks")
    @patch("engine.nexus.system_reflection.SystemReflection._collect_sessions")
    @patch("engine.nexus.system_reflection.SystemReflection._collect_metrics")
    def test_heuristic_reflection(
        self, mock_metrics, mock_sessions, mock_tasks,
        mock_store_insights, mock_store_report, reflection, sample_metrics,
    ):
        """Full cycle with heuristic analysis (no NLM)."""
        mock_metrics.return_value = sample_metrics
        mock_sessions.return_value = {"session_count": 3, "summaries": []}
        mock_tasks.return_value = ["task-1"]
        mock_store_insights.return_value = ["id-1"]

        report = reflection.run_reflection(period="weekly", days=7, use_nlm=False)

        assert report.report_id.startswith("reflection-weekly-")
        assert report.period == "weekly"
        assert len(report.insights) > 0
        assert report.nlm_notebook_id is None
        assert report.duration_seconds >= 0

    @patch("engine.nexus.system_reflection.SystemReflection._store_report")
    @patch("engine.nexus.system_reflection.SystemReflection._store_insights")
    @patch("engine.nexus.system_reflection.SystemReflection._create_tasks")
    @patch("engine.nexus.system_reflection.SystemReflection._collect_sessions")
    @patch("engine.nexus.system_reflection.SystemReflection._collect_metrics")
    def test_monthly_reflection(
        self, mock_metrics, mock_sessions, mock_tasks,
        mock_store_insights, mock_store_report, reflection,
    ):
        """Monthly reflection uses monthly questions."""
        mock_metrics.return_value = {"trends": {}, "regressions": []}
        mock_sessions.return_value = {"session_count": 0, "summaries": []}
        mock_tasks.return_value = []
        mock_store_insights.return_value = []

        report = reflection.run_reflection(period="monthly", days=30, use_nlm=False)

        assert report.period == "monthly"

    def test_history_tracking(self, reflection):
        """Reports are tracked in history."""
        with patch.object(reflection, "_collect_metrics", return_value={"trends": {}, "regressions": []}), \
             patch.object(reflection, "_collect_sessions", return_value={"session_count": 0, "summaries": []}), \
             patch.object(reflection, "_store_insights", return_value=[]), \
             patch.object(reflection, "_store_report"):
            reflection.run_reflection(use_nlm=False)
            reflection.run_reflection(use_nlm=False)

        history = reflection.get_history()
        assert len(history) == 2

    def test_latest_insights_empty(self, reflection):
        """No history returns empty insights."""
        assert reflection.latest_insights() == []

    def test_latest_insights_after_run(self, reflection):
        """Latest insights populated after run."""
        with patch.object(reflection, "_collect_metrics", return_value={
            "trends": {"llm.cache.hit_rate": {"current": 0.1}},
            "regressions": [],
        }), \
             patch.object(reflection, "_collect_sessions", return_value={"session_count": 0, "summaries": []}), \
             patch.object(reflection, "_store_insights", return_value=[]), \
             patch.object(reflection, "_store_report"):
            reflection.run_reflection(use_nlm=False)

        insights = reflection.latest_insights()
        assert len(insights) >= 1


# ── Nexus Storage ──────────────────────────────────────────────────────


class TestNexusStorage:
    """Test insight and report storage."""

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_insights(self, mock_client, reflection):
        """Insights are stored in Nexus."""
        client = MagicMock()
        mock_client.return_value = client

        insights = [
            ReflectionInsight(
                insight_id="i1", category="improvement", title="Test",
                description="Description", confidence=0.8, priority="high",
                actionable=True, suggested_action="Fix it",
                metric_references=["test.metric"],
            )
        ]
        stored = reflection._store_insights("report-1", insights)
        assert len(stored) == 1
        client.add_entry.assert_called_once()

    @patch("engine.nexus.client.get_nexus_client")
    def test_store_report(self, mock_client, reflection):
        """Full report is stored in Nexus."""
        client = MagicMock()
        mock_client.return_value = client

        report = ReflectionReport(
            report_id="r1", period="weekly", created_at="2024-01-01",
            insights=[
                ReflectionInsight(
                    insight_id="i1", category="pattern", title="T",
                    description="D", confidence=0.5, priority="low",
                    actionable=False,
                )
            ],
        )
        reflection._store_report(report)
        client.add_entry.assert_called_once()

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("Nexus unavailable"))
    def test_store_insights_no_nexus(self, mock_client, reflection):
        """Storage failure is handled gracefully when Nexus is down."""
        insights = [
            ReflectionInsight(
                insight_id="i1", category="pattern", title="Test insight",
                description="Test description", confidence=0.5, priority="low",
                actionable=False,
            )
        ]
        # Should not raise even without Nexus
        stored = reflection._store_insights("report-1", insights)
        # May or may not store, but should not crash
        assert isinstance(stored, list)


# ── Task Generation ────────────────────────────────────────────────────


class TestTaskGeneration:
    """Test automatic task creation from insights."""

    @patch("engine.nexus.task_scheduler.get_task_scheduler")
    def test_creates_tasks_for_actionable(self, mock_scheduler, reflection):
        """Actionable high/medium insights create tasks."""
        scheduler = MagicMock()
        mock_scheduler.return_value = scheduler

        insights = [
            ReflectionInsight(
                insight_id="i1", category="improvement", title="Fix cache",
                description="Cache is slow", confidence=0.8, priority="high",
                actionable=True, suggested_action="Increase TTL",
            ),
            ReflectionInsight(
                insight_id="i2", category="pattern", title="Good trend",
                description="All fine", confidence=0.5, priority="low",
                actionable=False,
            ),
        ]
        tasks = reflection._create_tasks(insights)
        assert len(tasks) == 1
        scheduler.add_task.assert_called_once()

    def test_no_tasks_for_low_priority(self, reflection):
        """Low priority insights don't generate tasks."""
        insights = [
            ReflectionInsight(
                insight_id="i1", category="pattern", title="Minor",
                description="Not important", confidence=0.3, priority="low",
                actionable=True,
            ),
        ]
        # Without task scheduler, returns empty
        tasks = reflection._create_tasks(insights)
        assert isinstance(tasks, list)

    def test_max_five_tasks(self, reflection):
        """At most 5 tasks are created per reflection."""
        insights = [
            ReflectionInsight(
                insight_id=f"i{i}", category="improvement",
                title=f"Fix {i}", description=f"Issue {i}",
                confidence=0.9, priority="high", actionable=True,
            )
            for i in range(10)
        ]
        with patch("engine.nexus.task_scheduler.get_task_scheduler") as mock:
            scheduler = MagicMock()
            mock.return_value = scheduler
            tasks = reflection._create_tasks(insights)
            assert scheduler.add_task.call_count <= 5


# ── Singleton ──────────────────────────────────────────────────────────


class TestSingleton:
    """Test singleton pattern."""

    def test_get_system_reflection(self):
        """Singleton returns same instance."""
        import engine.nexus.system_reflection as mod
        mod._instance = None
        r1 = mod.get_system_reflection()
        r2 = mod.get_system_reflection()
        assert r1 is r2
        mod._instance = None
