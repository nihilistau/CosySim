"""
System Reflection — NLM-driven autonomous system analysis and self-improvement.

The reflection engine periodically analyzes system metrics, session logs,
and operational data via NotebookLM to identify patterns, suggest improvements,
and auto-create actionable tasks.  This is the meta-learning loop that makes
the whole Project Autonomy system genuinely self-improving.

Pipeline:
    1. Collect metrics snapshot from MetaMetrics
    2. Collect recent session data from Nexus
    3. Build a reflection report document
    4. Create an NLM notebook seeded with the report
    5. Ask structured reflection questions
    6. Parse insights and store in Nexus
    7. Auto-create improvement tasks from insights
    8. Cleanup the NLM notebook

Trigger:
    - Weekly via SchedulerDaemon (``system-reflection`` task)
    - On-demand via MCP tool or @skill call

Thread-safe singleton — call ``get_system_reflection()``.
"""

from __future__ import annotations

import json
import logging
import time
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class ReflectionInsight:
    """A single insight extracted from NLM reflection."""

    insight_id: str
    category: str  # "pattern", "improvement", "risk", "opportunity"
    title: str
    description: str
    confidence: float  # 0.0–1.0
    priority: str  # "high", "medium", "low"
    actionable: bool
    suggested_action: str = ""
    metric_references: List[str] = field(default_factory=list)


@dataclass
class ReflectionReport:
    """Complete reflection analysis for a time period."""

    report_id: str
    period: str  # "weekly", "monthly"
    created_at: str
    metrics_summary: Dict[str, Any] = field(default_factory=dict)
    insights: List[ReflectionInsight] = field(default_factory=list)
    tasks_created: List[str] = field(default_factory=list)
    nlm_notebook_id: Optional[str] = None
    nlm_conversation_turns: int = 0
    duration_seconds: float = 0.0


# ── Reflection Questions ────────────────────────────────────────────────

WEEKLY_QUESTIONS = [
    "Based on these system metrics, what are the top 3 performance patterns "
    "you can identify?  Are there any concerning trends?",

    "Looking at the task completion data and error rates, which agent types "
    "or task categories are underperforming?  What might be causing this?",

    "Analyzing the knowledge growth and cache hit rates, is the system "
    "effectively building reusable knowledge?  Where are the gaps?",

    "What 3 concrete improvements would have the highest impact on overall "
    "system efficiency?  Consider both compute savings and quality gains.",

    "Are there any anomalies or unexpected patterns in the metrics that "
    "deserve investigation?  Any metrics that seem correlated?",

    "Based on the inference costs and token usage, what optimizations "
    "could reduce compute while maintaining output quality?",
]

MONTHLY_QUESTIONS = WEEKLY_QUESTIONS + [
    "Looking at the full month of data, what long-term trends are emerging? "
    "Is the system getting better or worse over time?",

    "Which areas of the codebase or system have the most recurring issues? "
    "What systemic changes would address root causes?",

    "Evaluate the knowledge pipeline: are we capturing the right knowledge? "
    "What important topics are underrepresented in Nexus?",

    "Propose 3 experiments that could validate improvement hypotheses. "
    "For each, describe the variants, metrics, and success criteria.",
]


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[SystemReflection] = None
_lock = threading.Lock()


def get_system_reflection() -> SystemReflection:
    """Get or create the singleton SystemReflection instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SystemReflection()
    return _instance


# ── Core Class ──────────────────────────────────────────────────────────


class SystemReflection:
    """NLM-driven system analysis and self-improvement engine.

    Collects metrics, builds reflection documents, sends them to
    NotebookLM for analysis, extracts insights, stores them in Nexus,
    and auto-creates improvement tasks.
    """

    def __init__(self) -> None:
        self._history: List[ReflectionReport] = []

    # ── Public API ──────────────────────────────────────────────────

    def run_reflection(
        self,
        period: str = "weekly",
        days: int = 7,
        use_nlm: bool = True,
    ) -> ReflectionReport:
        """Execute a full reflection cycle.

        Args:
            period: Reflection period — ``"weekly"`` or ``"monthly"``.
            days: Number of days of data to analyze.
            use_nlm: Whether to use NotebookLM for deep analysis.
                     If False, uses only heuristic analysis.

        Returns:
            A ``ReflectionReport`` with insights and created tasks.
        """
        start = time.monotonic()
        report_id = f"reflection-{period}-{uuid.uuid4().hex[:8]}"
        logger.info("Starting %s reflection: %s", period, report_id)

        # 1. Collect metrics
        metrics = self._collect_metrics(days)

        # 2. Collect recent session data
        sessions = self._collect_sessions(days)

        # 3. Build the reflection document
        doc = self._build_reflection_document(metrics, sessions, period, days)

        # 4. Analyze — via NLM if available, otherwise heuristic
        insights: List[ReflectionInsight] = []
        notebook_id = None
        conversation_turns = 0

        if use_nlm:
            try:
                nlm_result = self._analyze_with_nlm(doc, period)
                insights = nlm_result["insights"]
                notebook_id = nlm_result.get("notebook_id")
                conversation_turns = nlm_result.get("turns", 0)
            except Exception as exc:
                logger.warning(
                    "NLM analysis failed, falling back to heuristic: %s", exc
                )
                insights = self._analyze_heuristic(metrics)
        else:
            insights = self._analyze_heuristic(metrics)

        # 5. Store insights in Nexus
        stored_ids = self._store_insights(report_id, insights)

        # 6. Create improvement tasks
        tasks = self._create_tasks(insights)

        # 7. Build report
        elapsed = time.monotonic() - start
        report = ReflectionReport(
            report_id=report_id,
            period=period,
            created_at=datetime.now(timezone.utc).isoformat(),
            metrics_summary=metrics,
            insights=insights,
            tasks_created=tasks,
            nlm_notebook_id=notebook_id,
            nlm_conversation_turns=conversation_turns,
            duration_seconds=round(elapsed, 2),
        )
        self._history.append(report)

        # 8. Store the full report in Nexus
        self._store_report(report)

        logger.info(
            "Reflection %s complete: %d insights, %d tasks in %.1fs",
            report_id,
            len(insights),
            len(tasks),
            elapsed,
        )
        return report

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent reflection reports."""
        reports = self._history[-limit:]
        return [
            {
                "report_id": r.report_id,
                "period": r.period,
                "created_at": r.created_at,
                "insight_count": len(r.insights),
                "tasks_created": len(r.tasks_created),
                "duration_seconds": r.duration_seconds,
            }
            for r in reversed(reports)
        ]

    def latest_insights(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return insights from the most recent reflection."""
        if not self._history:
            return []
        latest = self._history[-1]
        return [asdict(i) for i in latest.insights[:limit]]

    # ── Metrics Collection ──────────────────────────────────────────

    def _collect_metrics(self, days: int) -> Dict[str, Any]:
        """Collect metrics from MetaMetrics for the given period."""
        result: Dict[str, Any] = {"period_days": days, "trends": {}}
        try:
            from engine.nexus.meta_metrics import get_meta_metrics
            mm = get_meta_metrics()

            # Collect trends for key metric categories
            metric_names = [
                "nexus.entries.total",
                "nexus.qa.cache_hits",
                "nexus.quality.average",
                "llm.calls.total",
                "llm.cache.hit_rate",
                "llm.tokens.output",
                "tasks.completed",
                "tasks.failed",
                "tests.pass_rate",
                "tests.total",
                "system.gpu.utilization",
                "system.gpu.memory_used_mb",
            ]
            for name in metric_names:
                try:
                    trend = mm.trend(name, days=days)
                    if trend.get("count", 0) > 0:
                        result["trends"][name] = {
                            "current": trend.get("last"),
                            "mean": trend.get("mean"),
                            "min": trend.get("min"),
                            "max": trend.get("max"),
                            "count": trend.get("count"),
                            "direction": trend.get("direction", "stable"),
                        }
                except Exception:
                    logger.warning("Metrics trend collection failed", exc_info=True)

            # Check for regressions
            try:
                regressions = mm.check_regressions()
                result["regressions"] = [asdict(a) for a in regressions]
            except Exception:
                logger.warning("Regression detection failed", exc_info=True)
                result["regressions"] = []

            # Dashboard summary
            try:
                result["dashboard"] = mm.dashboard(hours=days * 24)
            except Exception:
                logger.warning("Dashboard generation failed", exc_info=True)

        except ImportError:
            logger.warning("MetaMetrics not available")
        except Exception as exc:
            logger.warning("Metrics collection failed: %s", exc)

        return result

    def _collect_sessions(self, days: int) -> Dict[str, Any]:
        """Collect recent session data from Nexus."""
        result: Dict[str, Any] = {"session_count": 0, "summaries": []}
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            entries = client.search("session log", limit=20)
            if entries:
                result["session_count"] = len(entries)
                for entry in entries[:10]:
                    result["summaries"].append(
                        str(entry.get("title", ""))[:200]
                    )
        except Exception as exc:
            logger.debug("Session collection skipped: %s", exc)
        return result

    # ── Document Building ───────────────────────────────────────────

    def _build_reflection_document(
        self,
        metrics: Dict[str, Any],
        sessions: Dict[str, Any],
        period: str,
        days: int,
    ) -> str:
        """Build a markdown reflection document for NLM analysis."""
        lines = [
            f"# CosySim System Reflection — {period.title()} Report",
            f"",
            f"Period: last {days} days",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"",
            f"## Metrics Summary",
            f"",
        ]

        trends = metrics.get("trends", {})
        if trends:
            for name, data in sorted(trends.items()):
                direction = data.get("direction", "stable")
                icon = {"up": "↑", "down": "↓"}.get(direction, "→")
                lines.append(
                    f"- **{name}**: current={data.get('current', 'N/A')}, "
                    f"mean={data.get('mean', 'N/A')}, "
                    f"range=[{data.get('min', 'N/A')}, {data.get('max', 'N/A')}] "
                    f"{icon} ({data.get('count', 0)} samples)"
                )
        else:
            lines.append("- No metric data available for this period.")

        # Regressions
        regressions = metrics.get("regressions", [])
        if regressions:
            lines.append("")
            lines.append("## Detected Regressions")
            lines.append("")
            for reg in regressions:
                lines.append(
                    f"- **{reg.get('metric_name', '?')}**: "
                    f"{reg.get('message', 'regression detected')}"
                )

        # Sessions
        lines.append("")
        lines.append("## Recent Activity")
        lines.append(f"")
        lines.append(
            f"Sessions in period: {sessions.get('session_count', 0)}"
        )
        for summary in sessions.get("summaries", []):
            lines.append(f"- {summary}")

        # Dashboard
        dashboard = metrics.get("dashboard", "")
        if dashboard:
            lines.append("")
            lines.append("## System Dashboard")
            lines.append("")
            lines.append(dashboard)

        return "\n".join(lines)

    # ── NLM Analysis ────────────────────────────────────────────────

    def _analyze_with_nlm(
        self, document: str, period: str
    ) -> Dict[str, Any]:
        """Send reflection document to NLM and extract insights."""
        from engine.nexus.nlm_notebook_factory import get_notebook_factory
        from engine.nexus.nlm_engine import get_nlm_engine

        factory = get_notebook_factory()
        nb_name = f"reflection-{period}-{datetime.now().strftime('%Y%m%d')}"
        notebook_id = factory.get_or_create(nb_name, category="session")
        if not notebook_id:
            logger.warning("Failed to create reflection notebook")
            return {"insights": [], "notebook_id": "", "turns": 0}

        try:
            engine = get_nlm_engine()
        except Exception as exc:
            logger.warning("NLM engine unavailable: %s", exc)
            return {"insights": [], "notebook_id": notebook_id, "turns": 0}

        # Add the reflection document as a source
        try:
            engine.add_source(notebook_id, "text", document)
        except Exception as exc:
            logger.warning("Failed to add reflection source: %s", exc)

        # Select questions based on period
        questions = (
            MONTHLY_QUESTIONS if period == "monthly" else WEEKLY_QUESTIONS
        )

        # Ask each question and collect answers
        insights: List[ReflectionInsight] = []
        turns = 0
        for question in questions:
            try:
                answer = engine.ask(notebook_id, question)
                turns += 1
                parsed = self._parse_nlm_answer(question, answer)
                insights.extend(parsed)
            except Exception as exc:
                logger.warning("NLM question failed: %s", exc)

        return {
            "insights": insights,
            "notebook_id": notebook_id,
            "turns": turns,
        }

    def _parse_nlm_answer(
        self, question: str, answer: str
    ) -> List[ReflectionInsight]:
        """Parse NLM answer into structured insights."""
        if not answer or len(answer) < 20:
            return []

        insights: List[ReflectionInsight] = []

        # Determine category from question
        category = "pattern"
        if "improvement" in question.lower() or "optimization" in question.lower():
            category = "improvement"
        elif "risk" in question.lower() or "concern" in question.lower():
            category = "risk"
        elif "experiment" in question.lower() or "propose" in question.lower():
            category = "opportunity"

        # Determine priority from question
        priority = "medium"
        if "highest impact" in question.lower() or "top 3" in question.lower():
            priority = "high"

        # Split answer into paragraphs as individual insights
        paragraphs = [
            p.strip()
            for p in answer.split("\n\n")
            if p.strip() and len(p.strip()) > 30
        ]

        for i, paragraph in enumerate(paragraphs[:3]):
            title = paragraph[:100].split(".")[0].strip()
            if title.startswith("- "):
                title = title[2:]
            if title.startswith("**"):
                title = title.replace("**", "")

            insights.append(
                ReflectionInsight(
                    insight_id=f"nlm-{uuid.uuid4().hex[:8]}",
                    category=category,
                    title=title[:120],
                    description=paragraph[:500],
                    confidence=0.75,
                    priority=priority,
                    actionable="should" in paragraph.lower()
                    or "could" in paragraph.lower()
                    or "recommend" in paragraph.lower(),
                    suggested_action=(
                        paragraph[:200]
                        if "should" in paragraph.lower()
                        else ""
                    ),
                )
            )

        return insights

    # ── Heuristic Analysis ──────────────────────────────────────────

    def _analyze_heuristic(
        self, metrics: Dict[str, Any]
    ) -> List[ReflectionInsight]:
        """Generate insights from metrics without NLM."""
        insights: List[ReflectionInsight] = []
        trends = metrics.get("trends", {})

        # Check cache hit rate
        cache = trends.get("llm.cache.hit_rate", {})
        if cache:
            rate = cache.get("current", 0)
            if isinstance(rate, (int, float)):
                if rate < 0.3:
                    insights.append(
                        ReflectionInsight(
                            insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                            category="improvement",
                            title="Low cache hit rate detected",
                            description=(
                                f"Cache hit rate is {rate:.1%}, below the 30% "
                                f"threshold. Consider storing more Q&A pairs "
                                f"in Nexus and ensuring the query router is "
                                f"checking cache before making LLM calls."
                            ),
                            confidence=0.9,
                            priority="high",
                            actionable=True,
                            suggested_action="Increase Q&A cache coverage",
                            metric_references=["llm.cache.hit_rate"],
                        )
                    )

        # Check test pass rate
        tests = trends.get("tests.pass_rate", {})
        if tests:
            rate = tests.get("current", 1.0)
            if isinstance(rate, (int, float)) and rate < 0.95:
                insights.append(
                    ReflectionInsight(
                        insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                        category="risk",
                        title="Test pass rate below threshold",
                        description=(
                            f"Test pass rate is {rate:.1%}, below the 95% "
                            f"quality gate. Investigate recent test failures "
                            f"and prioritize fixes."
                        ),
                        confidence=0.95,
                        priority="high",
                        actionable=True,
                        suggested_action="Run auto-diagnosis on failing tests",
                        metric_references=["tests.pass_rate"],
                    )
                )

        # Check task completion
        completed = trends.get("tasks.completed", {})
        failed = trends.get("tasks.failed", {})
        if completed and failed:
            c_val = completed.get("current", 0)
            f_val = failed.get("current", 0)
            if isinstance(c_val, (int, float)) and isinstance(f_val, (int, float)):
                total = c_val + f_val
                if total > 0 and f_val / total > 0.2:
                    insights.append(
                        ReflectionInsight(
                            insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                            category="risk",
                            title="High task failure rate",
                            description=(
                                f"Task failure rate is "
                                f"{f_val / total:.1%} ({int(f_val)} failed "
                                f"out of {int(total)}). Review agent "
                                f"capabilities and task complexity matching."
                            ),
                            confidence=0.85,
                            priority="high",
                            actionable=True,
                            suggested_action=(
                                "Review task-agent matching rules"
                            ),
                            metric_references=[
                                "tasks.completed",
                                "tasks.failed",
                            ],
                        )
                    )

        # Check knowledge growth
        entries = trends.get("nexus.entries.total", {})
        if entries:
            direction = entries.get("direction", "stable")
            if direction == "down":
                insights.append(
                    ReflectionInsight(
                        insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                        category="risk",
                        title="Knowledge base shrinking",
                        description=(
                            "Nexus entry count is declining. This could "
                            "indicate cleanup being too aggressive or "
                            "insufficient knowledge capture."
                        ),
                        confidence=0.7,
                        priority="medium",
                        actionable=True,
                        suggested_action=(
                            "Review dedup and cleanup thresholds"
                        ),
                        metric_references=["nexus.entries.total"],
                    )
                )

        # Check regressions
        for reg in metrics.get("regressions", []):
            insights.append(
                ReflectionInsight(
                    insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                    category="risk",
                    title=f"Metric regression: {reg.get('metric_name', '?')}",
                    description=reg.get("message", "Performance regression"),
                    confidence=0.9,
                    priority="high",
                    actionable=True,
                    suggested_action="Investigate and revert if necessary",
                    metric_references=[reg.get("metric_name", "")],
                )
            )

        # If no issues found, add a positive insight
        if not insights:
            insights.append(
                ReflectionInsight(
                    insight_id=f"heuristic-{uuid.uuid4().hex[:8]}",
                    category="pattern",
                    title="System operating within normal parameters",
                    description=(
                        "All tracked metrics are within acceptable ranges. "
                        "No regressions or anomalies detected."
                    ),
                    confidence=0.8,
                    priority="low",
                    actionable=False,
                )
            )

        return insights

    # ── Nexus Storage ───────────────────────────────────────────────

    def _store_insights(
        self, report_id: str, insights: List[ReflectionInsight]
    ) -> List[str]:
        """Store individual insights in Nexus."""
        stored: List[str] = []
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            for insight in insights:
                try:
                    content = (
                        f"**Category:** {insight.category}\n"
                        f"**Priority:** {insight.priority}\n"
                        f"**Confidence:** {insight.confidence:.0%}\n"
                        f"**Actionable:** {'Yes' if insight.actionable else 'No'}\n\n"
                        f"{insight.description}\n\n"
                    )
                    if insight.suggested_action:
                        content += (
                            f"**Suggested Action:** {insight.suggested_action}\n"
                        )
                    if insight.metric_references:
                        content += (
                            f"**Metrics:** {', '.join(insight.metric_references)}\n"
                        )

                    client.add_entry(
                        title=f"[Reflection] {insight.title}",
                        content=content,
                        content_type="reflection",
                        category="system",
                        tags=[
                            "reflection",
                            insight.category,
                            insight.priority,
                            report_id,
                        ],
                    )
                    stored.append(insight.insight_id)
                except Exception as exc:
                    logger.debug("Failed to store insight: %s", exc)
        except Exception as exc:
            logger.warning("Cannot store insights — Nexus unavailable: %s", exc)
        return stored

    def _store_report(self, report: ReflectionReport) -> None:
        """Store the full reflection report in Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            summary_lines = [
                f"# {report.period.title()} Reflection — {report.report_id}",
                f"",
                f"- **Insights:** {len(report.insights)}",
                f"- **Tasks Created:** {len(report.tasks_created)}",
                f"- **Duration:** {report.duration_seconds:.1f}s",
                f"- **NLM Turns:** {report.nlm_conversation_turns}",
                f"",
                f"## Key Insights",
                f"",
            ]
            for insight in report.insights:
                priority_icon = {
                    "high": "🔴",
                    "medium": "🟡",
                    "low": "🟢",
                }.get(insight.priority, "⚪")
                summary_lines.append(
                    f"- {priority_icon} **{insight.title}** "
                    f"({insight.category}, {insight.confidence:.0%})"
                )

            client.add_entry(
                title=f"System Reflection: {report.period} — {report.created_at[:10]}",
                content="\n".join(summary_lines),
                content_type="reflection",
                category="system",
                tags=["reflection", "report", report.period, report.report_id],
            )
        except Exception as exc:
            logger.warning("Failed to store reflection report: %s", exc)

    # ── Task Generation ─────────────────────────────────────────────

    def _create_tasks(
        self, insights: List[ReflectionInsight]
    ) -> List[str]:
        """Create improvement tasks from actionable insights."""
        task_ids: List[str] = []
        actionable = [i for i in insights if i.actionable and i.priority in ("high", "medium")]

        if not actionable:
            return task_ids

        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()

            for insight in actionable[:5]:
                task_id = f"reflection-{insight.insight_id}"
                try:
                    scheduler.add_task(
                        task_id=task_id,
                        title=f"[Auto] {insight.title}",
                        description=(
                            f"{insight.description}\n\n"
                            f"Source: System Reflection\n"
                            f"Category: {insight.category}\n"
                            f"Priority: {insight.priority}\n"
                            f"Suggested: {insight.suggested_action}"
                        ),
                        priority=insight.priority,
                        source="system_reflection",
                        tags=["auto-generated", "reflection", insight.category],
                    )
                    task_ids.append(task_id)
                except Exception as exc:
                    logger.debug("Task creation failed: %s", exc)
        except Exception as exc:
            logger.warning("Task scheduler unavailable: %s", exc)

        return task_ids
