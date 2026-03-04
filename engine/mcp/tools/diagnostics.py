"""MCP tool domain: diagnostics.

Thin wrappers that delegate to *_tools.py implementations.
Apply @mcp_tool for unified error handling and serialisation.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.paths import ROOT as _root
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.mcp.decorators import mcp_tool
from engine.mcp._lazy import _get_db, _get_rag, _get_config

logger = logging.getLogger(__name__)

# ──── DIAGNOSTICS TOOLS ──────────────────────────────────────────────────


@mcp_tool
def diagnose_test_failures(pytest_output: str) -> str:
    """Auto-diagnose test failures from pytest output. Parses failures,
    checks Nexus for prior fixes, applies heuristics, asks NLM, stores
    diagnoses, and creates fix tasks. Returns root causes and suggested fixes."""
    try:
        from engine.nexus.auto_diagnosis import get_auto_diagnosis
        return json.dumps(get_auto_diagnosis().full_pipeline(pytest_output), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def diagnose_test_file(test_file: str, test_name: str = "") -> str:
    """Run a test file, auto-diagnose failures, and create fix tasks.
    Returns diagnoses with root cause, confidence, and suggested fixes."""
    try:
        from engine.nexus.auto_diagnosis import get_auto_diagnosis
        diag = get_auto_diagnosis()
        diagnoses = diag.diagnose_file(test_file, test_name)
        tasks = diag.create_fix_tasks(diagnoses)
        return json.dumps({
            "failures_found": len(diagnoses),
            "diagnoses": [
                {
                    "test": f"{d.failure.test_file}::{d.failure.test_name}",
                    "error": d.failure.error_type,
                    "root_cause": d.root_cause[:200],
                    "suggested_fix": d.suggested_fix[:200],
                    "confidence": d.confidence,
                    "source": d.source,
                }
                for d in diagnoses
            ],
            "tasks_created": len(tasks),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def metrics_dashboard(hours: int = 24) -> str:
    """Generate a full system metrics dashboard in markdown with trends,
    comparisons, and active alerts."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return get_meta_metrics().dashboard(hours=hours)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def metrics_collect_all() -> str:
    """Collect and record all current system metrics — VRAM, Nexus stats,
    inference stats, test counts. Returns recorded values."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return json.dumps(get_meta_metrics().collect_all(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def metrics_check_regressions(threshold_pct: float = 10.0) -> str:
    """Check all tracked metrics for regressions against baselines.
    Returns alerts for any metrics that degraded beyond the threshold."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        alerts = get_meta_metrics().check_regressions(threshold_pct=threshold_pct)
        return json.dumps(
            [{"metric": a.metric_name, "type": a.alert_type, "message": a.message,
              "current": a.current_value, "baseline": a.baseline_value}
             for a in alerts],
            indent=2, default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def metrics_snapshot() -> str:
    """Get the most recent value for every tracked metric."""
    try:
        from engine.nexus.meta_metrics import get_meta_metrics
        return json.dumps(get_meta_metrics().snapshot(), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def reflection_run(period: str = "weekly", days: int = 7, use_nlm: bool = False) -> str:
    """Run a system reflection analysis — collect metrics, analyze patterns, generate insights, create tasks."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        report = get_system_reflection().run_reflection(period=period, days=days, use_nlm=use_nlm)
        return json.dumps({
            "report_id": report.report_id,
            "period": report.period,
            "insight_count": len(report.insights),
            "tasks_created": len(report.tasks_created),
            "insights": [
                {"title": i.title, "category": i.category, "priority": i.priority,
                 "actionable": i.actionable, "description": i.description[:200]}
                for i in report.insights
            ],
            "duration_seconds": report.duration_seconds,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def reflection_history(limit: int = 5) -> str:
    """Get recent system reflection reports and their summaries."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        return json.dumps(get_system_reflection().get_history(limit=limit), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def reflection_latest_insights(limit: int = 10) -> str:
    """Get insights from the most recent system reflection."""
    try:
        from engine.nexus.system_reflection import get_system_reflection
        return json.dumps(get_system_reflection().latest_insights(limit=limit), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def experiment_scan_and_propose() -> str:
    """Scan current metrics against templates and propose experiments for triggered conditions."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        proposals = get_experiment_proposer().scan_and_propose()
        return json.dumps([
            {"proposal_id": p.proposal_id, "experiment_name": p.experiment_name,
             "trigger_metric": p.trigger_metric, "trigger_value": p.trigger_value,
             "priority": p.priority, "hypothesis": p.hypothesis}
            for p in proposals
        ], default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def experiment_list_proposals(status: str = "") -> str:
    """List experiment proposals. Filter: 'pending', 'active', or '' for all."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        s = status if status else None
        return json.dumps(get_experiment_proposer().get_proposals(status=s), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_tool
def experiment_list_templates() -> str:
    """List all experiment templates with their triggers and thresholds."""
    try:
        from engine.nexus.experiment_proposals import get_experiment_proposer
        return json.dumps(get_experiment_proposer().list_templates(), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
