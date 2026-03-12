"""Workspace Pipeline End-to-End Smoke Test.

Validates live API connectivity for all Workspace Gemini services
and pipeline stage execution.  Run manually or via scheduler.

Usage:
    python scripts/workspace_smoke_test.py              # All tests
    python scripts/workspace_smoke_test.py --stage X    # Single stage
    python scripts/workspace_smoke_test.py --quick      # Fast health only
    python scripts/workspace_smoke_test.py --json       # JSON output
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)


# ──── Result Model ────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    """Result of a single smoke test."""

    name: str
    passed: bool
    duration_ms: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 1),
            "message": self.message,
            "details": self.details,
        }


@dataclass
class SmokeTestReport:
    """Aggregate smoke test report."""

    timestamp: str
    results: List[TestResult] = field(default_factory=list)
    total_duration_ms: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "timestamp": self.timestamp,
            "passed": self.passed,
            "failed": self.failed,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "all_passed": self.all_passed,
            "results": [r.to_dict() for r in self.results],
        }


# ──── Test Functions ──────────────────────────────────────────────────────────


def _timed(name: str, func, *args, **kwargs) -> TestResult:
    """Run a test function and time it."""
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return TestResult(
            name=name,
            passed=True,
            duration_ms=elapsed,
            message="OK",
            details=result if isinstance(result, dict) else {},
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return TestResult(
            name=name,
            passed=False,
            duration_ms=elapsed,
            message=str(exc),
        )


def test_workspace_gemini_client_available() -> Dict[str, Any]:
    """Check that WorkspaceGeminiClient module is importable."""
    from engine.integrations.workspace_gemini_client import WorkspaceGeminiClient

    if WorkspaceGeminiClient is None:
        raise RuntimeError("WorkspaceGeminiClient class not found")
    return {"class": "WorkspaceGeminiClient"}


def test_sheets_client_available() -> Dict[str, Any]:
    """Check that GoogleSheetsClient can be instantiated."""
    from engine.integrations.gsheets_client import get_sheets_client

    client = get_sheets_client()
    if client is None:
        raise RuntimeError("GoogleSheetsClient is None — no account available")
    return {"client": type(client).__name__}


def test_docs_client_available() -> Dict[str, Any]:
    """Check that GoogleDocsClient module is importable."""
    from engine.integrations.google_docs_client import GoogleDocsClient

    if GoogleDocsClient is None:
        raise RuntimeError("GoogleDocsClient class not found")
    return {"class": "GoogleDocsClient"}


def test_drive_client_available() -> Dict[str, Any]:
    """Check that GoogleDriveClient can be instantiated."""
    from engine.integrations.google_drive_client import get_drive_client

    client = get_drive_client()
    if client is None:
        raise RuntimeError("GoogleDriveClient is None — no account available")
    return {"client": type(client).__name__}


def test_nlm_client_available() -> Dict[str, Any]:
    """Check that NLM direct client module is importable."""
    from engine.integrations import nlm_direct_client

    if not hasattr(nlm_direct_client, "NLMDirectClient"):
        raise RuntimeError("NLMDirectClient class not found in module")
    return {"module": "nlm_direct_client", "class": "NLMDirectClient"}


def test_nexus_client_available() -> Dict[str, Any]:
    """Check that Nexus client is reachable."""
    from engine.nexus.client import get_nexus_client

    client = get_nexus_client()
    if client is None:
        raise RuntimeError("Nexus client is None")
    return {"client": type(client).__name__}


def test_pipeline_stages_registered() -> Dict[str, Any]:
    """Check that all expected pipeline stages are registered."""
    from engine.nexus.workspace_pipeline import STAGE_REGISTRY

    expected_stages = [
        "nlm_research", "nlm_add_source", "create_doc", "create_sheet",
        "fill_sheet", "drive_search", "drive_upload", "drive_ask",
        "nexus_store", "export_doc", "workspace_generate", "fetch_news",
        "columnsmith",
    ]
    missing = [s for s in expected_stages if s not in STAGE_REGISTRY]
    if missing:
        raise RuntimeError(f"Missing pipeline stages: {missing}")
    return {"stages": len(STAGE_REGISTRY), "expected": len(expected_stages)}


def test_pipeline_templates_available() -> Dict[str, Any]:
    """Check that all pipeline templates are defined."""
    from engine.nexus.workspace_pipeline import PIPELINE_TEMPLATES

    expected_templates = [
        "research_and_distill", "create_knowledge_doc", "data_enrichment",
        "cross_source_synthesis", "news_pipeline", "doc_to_notebook",
        "sheet_to_knowledge", "generate_and_store", "news_to_knowledge",
    ]
    missing = [t for t in expected_templates if t not in PIPELINE_TEMPLATES]
    if missing:
        raise RuntimeError(f"Missing templates: {missing}")
    return {"templates": len(PIPELINE_TEMPLATES)}


def test_workspace_rpc_registry() -> Dict[str, Any]:
    """Check that WorkspaceRPCRegistry loads and has all sections."""
    from engine.integrations.workspace_rpc_registry import get_workspace_registry

    registry = get_workspace_registry()
    summary = registry.summary()
    if summary.get("total_operations", 0) == 0:
        raise RuntimeError("Registry has 0 operations")
    return summary


def test_scheduler_workspace_tasks() -> Dict[str, Any]:
    """Check that workspace pipeline tasks are in the scheduler."""
    from engine.nexus.scheduler_daemon import get_scheduler_daemon

    daemon = get_scheduler_daemon()
    expected_tasks = [
        "workspace-news-pipeline",
        "workspace-news-to-knowledge",
        "workspace-research-cycle",
        "workspace-pipeline-health",
    ]
    registered = [t for t in expected_tasks if t in daemon._tasks]
    missing = [t for t in expected_tasks if t not in daemon._tasks]
    if missing:
        raise RuntimeError(f"Missing scheduler tasks: {missing}")
    return {"registered": len(registered), "total_scheduler_tasks": len(daemon._tasks)}


def test_news_pipeline_sources() -> Dict[str, Any]:
    """Check that news source registry has curated sources."""
    from engine.nexus.news_sources import get_news_registry

    registry = get_news_registry()
    sources = registry.list_sources()
    categories = set()
    for src in sources:
        if hasattr(src, "category"):
            categories.add(src.category)
    if len(sources) == 0:
        raise RuntimeError("No news sources registered")
    return {"sources": len(sources), "categories": list(categories)}


def test_workspace_skills_registered() -> Dict[str, Any]:
    """Check that workspace skills module is importable and has skills."""
    import engine.skills.builtin.workspace_skills as ws_mod

    skill_funcs = [
        name for name in dir(ws_mod)
        if name.startswith("workspace_") and callable(getattr(ws_mod, name, None))
    ]
    if len(skill_funcs) < 10:
        raise RuntimeError(
            f"Expected 10+ workspace_ functions, found {len(skill_funcs)}: "
            f"{skill_funcs}"
        )
    return {"workspace_functions": len(skill_funcs), "names": skill_funcs}


# ──── Live API Tests (require real credentials) ───────────────────────────────


def test_workspace_get_settings() -> Dict[str, Any]:
    """Live test: call Workspace Gemini getSettings endpoint."""
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client

    client = get_workspace_gemini_client()
    if client is None:
        raise RuntimeError("No client available")
    result = client.get_settings()
    return {"settings_keys": list(result.keys()) if isinstance(result, dict) else type(result).__name__}


def test_workspace_quota_summary() -> Dict[str, Any]:
    """Live test: call Workspace Gemini quotaSummary endpoint."""
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client

    client = get_workspace_gemini_client()
    if client is None:
        raise RuntimeError("No client available")
    result = client.quota_summary()
    return {"quota": result if isinstance(result, dict) else str(result)[:200]}


def test_workspace_list_gems() -> Dict[str, Any]:
    """Live test: call Workspace Gemini listGems endpoint."""
    from engine.integrations.workspace_gemini_client import get_workspace_gemini_client

    client = get_workspace_gemini_client()
    if client is None:
        raise RuntimeError("No client available")
    result = client.list_gems()
    return {"gems": len(result) if isinstance(result, list) else type(result).__name__}


# ──── Runner ──────────────────────────────────────────────────────────────────


HEALTH_TESTS = [
    ("workspace_gemini_client", test_workspace_gemini_client_available),
    ("sheets_client", test_sheets_client_available),
    ("docs_client", test_docs_client_available),
    ("drive_client", test_drive_client_available),
    ("nlm_client", test_nlm_client_available),
    ("nexus_client", test_nexus_client_available),
    ("pipeline_stages", test_pipeline_stages_registered),
    ("pipeline_templates", test_pipeline_templates_available),
    ("rpc_registry", test_workspace_rpc_registry),
    ("scheduler_tasks", test_scheduler_workspace_tasks),
    ("news_sources", test_news_pipeline_sources),
    ("workspace_skills", test_workspace_skills_registered),
]

LIVE_TESTS = [
    ("live_get_settings", test_workspace_get_settings),
    ("live_quota_summary", test_workspace_quota_summary),
    ("live_list_gems", test_workspace_list_gems),
]


def run_smoke_tests(
    quick: bool = False,
    stage: Optional[str] = None,
    json_output: bool = False,
) -> SmokeTestReport:
    """Run smoke tests and return report.

    Args:
        quick: Only run health checks (no live API calls).
        stage: Run only a specific test by name.
        json_output: Suppress console output (caller handles JSON).

    Returns:
        SmokeTestReport with all results.
    """
    report = SmokeTestReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    start = time.perf_counter()

    tests_to_run = list(HEALTH_TESTS)
    if not quick:
        tests_to_run.extend(LIVE_TESTS)

    if stage:
        tests_to_run = [(n, f) for n, f in tests_to_run if n == stage]
        if not tests_to_run:
            print(f"Unknown test: {stage}")
            print(f"Available: {[n for n, _ in HEALTH_TESTS + LIVE_TESTS]}")
            sys.exit(1)

    for name, func in tests_to_run:
        result = _timed(name, func)
        report.results.append(result)
        if not json_output:
            status = "PASS" if result.passed else "FAIL"
            print(f"  [{status}] {name}: {result.message} ({result.duration_ms:.0f}ms)")

    report.total_duration_ms = (time.perf_counter() - start) * 1000

    if not json_output:
        print(f"\n{'='*60}")
        print(f"  {report.passed}/{len(report.results)} passed, "
              f"{report.failed} failed, "
              f"{report.total_duration_ms:.0f}ms total")
        print(f"{'='*60}")

    # Store report in Nexus
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        client.add_entry(
            title=f"Workspace Smoke Test: {report.timestamp[:10]}",
            content=json.dumps(report.to_dict(), indent=2),
            content_type="note",
            category="system",
        )
    except Exception:
        pass

    return report


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.WARNING)

    args = sys.argv[1:]
    quick = "--quick" in args
    json_output = "--json" in args
    stage = None
    if "--stage" in args:
        idx = args.index("--stage")
        if idx + 1 < len(args):
            stage = args[idx + 1]

    if not json_output:
        print(f"\n[*] Workspace Pipeline Smoke Test")
        print(f"    Mode: {'quick health' if quick else 'full (health + live API)'}")
        print(f"{'='*60}\n")

    report = run_smoke_tests(quick=quick, stage=stage, json_output=json_output)

    if json_output:
        print(json.dumps(report.to_dict(), indent=2))

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
