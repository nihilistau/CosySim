"""
Tests for the autonomy skills pack and MCP tool wiring.

Validates that all autonomy skills (scheduler, news, notebooks, quality,
governance, tasks) are importable, discoverable by the skill registry,
and return valid JSON from mocked backends.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _mock_news_article(**overrides: Any) -> MagicMock:
    """Create a mock NewsArticle."""
    art = MagicMock()
    art.title = overrides.get("title", "Test Article")
    art.url = overrides.get("url", "https://example.com/1")
    art.source_id = overrides.get("source_id", "hn-top")
    art.category = overrides.get("category", "ai_ml")
    art.summary = overrides.get("summary", "Test summary")
    art.score = overrides.get("score", 0.8)
    art.published_at = overrides.get("published_at", datetime.now(timezone.utc))
    art.keywords = overrides.get("keywords", ["ai", "test"])
    return art


# ═══════════════════════════════════════════════════════════════════
# SKILL IMPORT & REGISTRATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSkillRegistration:
    """Verify all autonomy skills are importable and registered."""

    def test_import_module(self):
        """Module imports without errors."""
        from engine.skills.builtin import autonomy_skills
        assert autonomy_skills is not None

    def test_scheduler_skills_exist(self):
        """Scheduler skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            scheduler_status,
            scheduler_run_now,
            scheduler_list_tasks,
        )
        assert callable(scheduler_status)
        assert callable(scheduler_run_now)
        assert callable(scheduler_list_tasks)

    def test_news_skills_exist(self):
        """News intelligence skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            news_fetch,
            news_fetch_and_store,
            news_digest,
            news_list_sources,
        )
        assert callable(news_fetch)
        assert callable(news_fetch_and_store)
        assert callable(news_digest)
        assert callable(news_list_sources)

    def test_notebook_skills_exist(self):
        """NLM notebook management skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            nlm_notebook_list,
            nlm_notebook_seed_docs,
            nlm_notebook_seed_code,
            nlm_notebook_research,
            nlm_notebook_rotate,
        )
        assert callable(nlm_notebook_list)
        assert callable(nlm_notebook_seed_docs)
        assert callable(nlm_notebook_seed_code)
        assert callable(nlm_notebook_research)
        assert callable(nlm_notebook_rotate)

    def test_quality_skills_exist(self):
        """Knowledge quality skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            nexus_quality_report,
            nexus_full_maintenance,
            nexus_backup,
        )
        assert callable(nexus_quality_report)
        assert callable(nexus_full_maintenance)
        assert callable(nexus_backup)

    def test_governance_skills_exist(self):
        """Governance skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            governance_validate_file,
            governance_validate_commit,
            governance_check_permissions,
            governance_seed_rules,
            governance_stats,
        )
        assert callable(governance_validate_file)
        assert callable(governance_validate_commit)
        assert callable(governance_check_permissions)
        assert callable(governance_seed_rules)
        assert callable(governance_stats)

    def test_task_skills_exist(self):
        """Task auto-generation skills are defined."""
        from engine.skills.builtin.autonomy_skills import (
            tasks_from_test_failures,
            tasks_from_benchmark,
            task_from_template,
            task_list_templates,
        )
        assert callable(tasks_from_test_failures)
        assert callable(tasks_from_benchmark)
        assert callable(task_from_template)
        assert callable(task_list_templates)

    def test_builtin_init_imports_autonomy(self):
        """builtin/__init__.py imports autonomy_skills."""
        from engine.skills.builtin import autonomy_skills
        assert hasattr(autonomy_skills, "scheduler_status")

    def test_all_skills_registered_in_registry(self):
        """Every public skill function in autonomy_skills is in the SKILL_REGISTRY."""
        from engine.skills.registry import SKILL_REGISTRY
        expected_skills = [
            "scheduler_status", "scheduler_run_now", "scheduler_list_tasks",
            "news_fetch", "news_fetch_and_store", "news_digest", "news_list_sources",
            "nlm_notebook_list", "nlm_notebook_seed_docs", "nlm_notebook_seed_code",
            "nlm_notebook_research", "nlm_notebook_rotate",
            "nexus_quality_report", "nexus_full_maintenance", "nexus_backup",
            "governance_validate_file", "governance_validate_commit",
            "governance_check_permissions", "governance_seed_rules", "governance_stats",
            "tasks_from_test_failures", "tasks_from_benchmark",
            "task_from_template", "task_list_templates",
            "diagnose_failures", "diagnose_test_file",
            "training_collect_task", "training_collect_qa",
            "training_export_jsonl", "training_export_sharegpt",
            "training_export_dpo", "training_sync_nexus", "training_stats",
            "metrics_record", "metrics_trend", "metrics_check_regressions",
            "metrics_dashboard", "metrics_collect_all", "metrics_snapshot",
            "reflection_run", "reflection_history", "reflection_latest_insights",
            "experiment_scan_and_propose", "experiment_list_proposals",
            "experiment_list_templates",
            "copilot_sync_config", "copilot_config_status",
            "copilot_list_instructions", "copilot_list_agents",
            "knowledge_graph_build", "knowledge_graph_gaps",
            "knowledge_graph_clusters", "knowledge_graph_search",
            "knowledge_graph_research_tasks",
        ]
        for name in expected_skills:
            assert SKILL_REGISTRY.get_skill(name) is not None, f"{name} not in SKILL_REGISTRY"


# ═══════════════════════════════════════════════════════════════════
# SCHEDULER SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSchedulerSkills:
    """Test scheduler skills with mocked daemon."""

    @patch("engine.skills.builtin.autonomy_skills._scheduler")
    def test_scheduler_status_returns_json(self, mock_sched):
        """scheduler_status returns valid JSON."""
        from engine.skills.builtin.autonomy_skills import scheduler_status
        mock_sched.return_value.status.return_value = {
            "running": False,
            "task_count": 6,
            "tasks": [],
        }
        result = scheduler_status()
        data = json.loads(result)
        assert "running" in data
        assert data["task_count"] == 6

    @patch("engine.skills.builtin.autonomy_skills._scheduler")
    def test_scheduler_run_now_returns_json(self, mock_sched):
        """scheduler_run_now returns valid JSON."""
        from engine.skills.builtin.autonomy_skills import scheduler_run_now
        mock_sched.return_value.run_task.return_value = {
            "success": True,
            "duration_s": 1.23,
        }
        result = scheduler_run_now("nexus-maintenance")
        data = json.loads(result)
        assert data["success"] is True

    @patch("engine.skills.builtin.autonomy_skills._scheduler")
    def test_scheduler_list_tasks_returns_json(self, mock_sched):
        """scheduler_list_tasks returns valid JSON."""
        from engine.skills.builtin.autonomy_skills import scheduler_list_tasks
        mock_sched.return_value.list_tasks.return_value = [
            {"id": "nexus-maintenance", "name": "Nexus Health"},
        ]
        result = scheduler_list_tasks()
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["id"] == "nexus-maintenance"


# ═══════════════════════════════════════════════════════════════════
# NEWS SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNewsSkills:
    """Test news intelligence skills with mocked registry."""

    @patch("engine.skills.builtin.autonomy_skills._news")
    def test_news_fetch_returns_articles(self, mock_news):
        """news_fetch returns JSON list of articles."""
        from engine.skills.builtin.autonomy_skills import news_fetch
        articles = [_mock_news_article(title="Test 1"), _mock_news_article(title="Test 2")]
        mock_news.return_value.fetch_all.return_value = articles
        mock_news.return_value.filter_articles.return_value = articles
        mock_news.return_value.score_relevance.return_value = 0.75

        result = news_fetch()
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["title"] == "Test 1"

    @patch("engine.skills.builtin.autonomy_skills._news")
    def test_news_fetch_and_store_calls_store(self, mock_news):
        """news_fetch_and_store stores articles in Nexus."""
        from engine.skills.builtin.autonomy_skills import news_fetch_and_store
        articles = [_mock_news_article()]
        mock_news.return_value.fetch_all.return_value = articles
        mock_news.return_value.filter_articles.return_value = articles
        mock_news.return_value.score_relevance.return_value = 0.9
        mock_news.return_value.store_to_nexus.return_value = 1
        mock_news.return_value.generate_digest.return_value = "# Digest"

        with patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus")):
            result = news_fetch_and_store()
        data = json.loads(result)
        assert data["stored"] == 1
        mock_news.return_value.store_to_nexus.assert_called_once()

    @patch("engine.skills.builtin.autonomy_skills._news")
    def test_news_list_sources_returns_stats(self, mock_news):
        """news_list_sources returns source statistics."""
        from engine.skills.builtin.autonomy_skills import news_list_sources
        mock_news.return_value.stats.return_value = {"total": 5}
        result = news_list_sources()
        data = json.loads(result)
        assert data["total"] == 5


# ═══════════════════════════════════════════════════════════════════
# NOTEBOOK SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNotebookSkills:
    """Test NLM notebook management skills."""

    @patch("engine.skills.builtin.autonomy_skills._notebooks")
    def test_nlm_notebook_list_returns_health(self, mock_nb):
        """nlm_notebook_list returns notebook health data."""
        from engine.skills.builtin.autonomy_skills import nlm_notebook_list
        mock_nb.return_value.health.return_value = {"slots": [], "total": 0}
        result = nlm_notebook_list()
        data = json.loads(result)
        assert "total" in data

    @patch("engine.skills.builtin.autonomy_skills._notebooks")
    def test_nlm_notebook_seed_docs_calls_seed(self, mock_nb):
        """nlm_notebook_seed_docs calls seed_from_docs."""
        from engine.skills.builtin.autonomy_skills import nlm_notebook_seed_docs
        mock_nb.return_value.seed_from_docs.return_value = {"seeded": True}
        result = nlm_notebook_seed_docs("cosysim-architecture")
        data = json.loads(result)
        assert data["seeded"] is True
        mock_nb.return_value.seed_from_docs.assert_called_once_with("cosysim-architecture")

    @patch("engine.skills.builtin.autonomy_skills._notebooks")
    def test_nlm_notebook_seed_code_calls_seed(self, mock_nb):
        """nlm_notebook_seed_code calls seed_from_code."""
        from engine.skills.builtin.autonomy_skills import nlm_notebook_seed_code
        mock_nb.return_value.seed_from_code.return_value = {"seeded": True}
        result = nlm_notebook_seed_code("cosysim-codebase")
        data = json.loads(result)
        assert data["seeded"] is True

    @patch("engine.skills.builtin.autonomy_skills._notebooks")
    def test_nlm_notebook_research_creates_notebook(self, mock_nb):
        """nlm_notebook_research creates or gets a research notebook."""
        from engine.skills.builtin.autonomy_skills import nlm_notebook_research
        mock_nb.return_value.get_or_create_research.return_value = {
            "notebook_id": "nb-abc",
            "topic": "MCP state management",
        }
        result = nlm_notebook_research("MCP state management")
        data = json.loads(result)
        assert data["notebook_id"] == "nb-abc"

    @patch("engine.skills.builtin.autonomy_skills._notebooks")
    def test_nlm_notebook_rotate_calls_rotate(self, mock_nb):
        """nlm_notebook_rotate deletes and recreates a notebook slot."""
        from engine.skills.builtin.autonomy_skills import nlm_notebook_rotate
        mock_nb.return_value.rotate_notebook.return_value = {"rotated": True}
        result = nlm_notebook_rotate("news-daily")
        data = json.loads(result)
        assert data["rotated"] is True


# ═══════════════════════════════════════════════════════════════════
# QUALITY SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestQualitySkills:
    """Test knowledge quality skills."""

    @patch("engine.nexus.self_maintenance.quality_report")
    def test_nexus_quality_report_returns_json(self, mock_report):
        """nexus_quality_report returns valid quality data."""
        from engine.skills.builtin.autonomy_skills import nexus_quality_report
        mock_report.return_value = {
            "total_entries": 100,
            "average_score": 0.72,
            "stale": [],
        }
        result = nexus_quality_report()
        data = json.loads(result)
        assert data["total_entries"] == 100

    @patch("engine.nexus.self_maintenance.nexus_full_maintenance")
    def test_nexus_full_maintenance_dry_run(self, mock_impl):
        """nexus_full_maintenance defaults to dry-run."""
        mock_impl.return_value = {"health": "ok"}
        from engine.skills.builtin.autonomy_skills import nexus_full_maintenance
        result = nexus_full_maintenance("false")
        data = json.loads(result)
        assert "health" in data
        mock_impl.assert_called_once_with(dry_run=True)


# ═══════════════════════════════════════════════════════════════════
# GOVERNANCE SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestGovernanceSkills:
    """Test governance validation skills."""

    @patch("engine.skills.builtin.autonomy_skills._governance")
    def test_governance_validate_file_returns_violations(self, mock_gov):
        """governance_validate_file returns list of violations."""
        from engine.skills.builtin.autonomy_skills import governance_validate_file
        mock_gov.return_value.validate_file.return_value = [
            {"rule": "no-print", "severity": "warning", "message": "print() found"},
        ]
        result = governance_validate_file("test.py")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["rule"] == "no-print"

    @patch("engine.skills.builtin.autonomy_skills._governance")
    def test_governance_validate_commit_returns_violations(self, mock_gov):
        """governance_validate_commit returns list of violations."""
        from engine.skills.builtin.autonomy_skills import governance_validate_commit
        mock_gov.return_value.validate_commit.return_value = [
            {"rule": "conventional-prefix", "severity": "error",
             "message": "Missing conventional prefix"},
        ]
        result = governance_validate_commit("bad commit msg")
        data = json.loads(result)
        assert len(data) == 1

    @patch("engine.skills.builtin.autonomy_skills._governance")
    def test_governance_check_permissions_returns_bool(self, mock_gov):
        """governance_check_permissions returns allowed bool."""
        from engine.skills.builtin.autonomy_skills import governance_check_permissions
        mock_gov.return_value.check_permissions.return_value = True
        result = governance_check_permissions("copilot", "admin")
        data = json.loads(result)
        assert data["allowed"] is True

    @patch("engine.skills.builtin.autonomy_skills._governance")
    def test_governance_seed_rules_returns_count(self, mock_gov):
        """governance_seed_rules returns seeded count."""
        from engine.skills.builtin.autonomy_skills import governance_seed_rules
        mock_gov.return_value.seed_rules.return_value = {"seeded": 18}
        result = governance_seed_rules()
        data = json.loads(result)
        assert data["seeded"] == 18

    @patch("engine.skills.builtin.autonomy_skills._governance")
    def test_governance_stats_returns_stats(self, mock_gov):
        """governance_stats returns rule statistics."""
        from engine.skills.builtin.autonomy_skills import governance_stats
        mock_gov.return_value.stats.return_value = {"total": 18, "by_scope": {}}
        result = governance_stats()
        data = json.loads(result)
        assert data["total"] == 18


# ═══════════════════════════════════════════════════════════════════
# TASK AUTO-GENERATION SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestTaskSkills:
    """Test task auto-generation skills."""

    @patch("engine.skills.builtin.autonomy_skills._tasks")
    def test_tasks_from_test_failures_parses_output(self, mock_tasks):
        """tasks_from_test_failures generates tasks from pytest output."""
        from engine.skills.builtin.autonomy_skills import tasks_from_test_failures
        mock_task = MagicMock()
        mock_task.id = "fix-test-1"
        mock_task.title = "Fix test_foo"
        mock_tasks.return_value.generate_from_test_failures.return_value = [mock_task]

        result = tasks_from_test_failures("FAILED tests/test_foo.py::test_bar")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["id"] == "fix-test-1"

    @patch("engine.skills.builtin.autonomy_skills._tasks")
    def test_tasks_from_benchmark_creates_task(self, mock_tasks):
        """tasks_from_benchmark creates optimization task on regression."""
        from engine.skills.builtin.autonomy_skills import tasks_from_benchmark
        mock_task = MagicMock()
        mock_task.id = "opt-inference"
        mock_task.title = "Optimize inference speed"
        mock_tasks.return_value.generate_from_benchmark.return_value = mock_task

        result = tasks_from_benchmark("inference_speed", "15.0", "20.0", "10")
        data = json.loads(result)
        assert data["created"] is True

    @patch("engine.skills.builtin.autonomy_skills._tasks")
    def test_tasks_from_benchmark_no_regression(self, mock_tasks):
        """tasks_from_benchmark returns no-op when no regression."""
        from engine.skills.builtin.autonomy_skills import tasks_from_benchmark
        mock_tasks.return_value.generate_from_benchmark.return_value = None

        result = tasks_from_benchmark("speed", "21.0", "20.0", "10")
        data = json.loads(result)
        assert data["created"] is False

    @patch("engine.skills.builtin.autonomy_skills._tasks")
    def test_task_from_template_creates_task(self, mock_tasks):
        """task_from_template creates task from template name."""
        from engine.skills.builtin.autonomy_skills import task_from_template
        mock_task = MagicMock()
        mock_task.id = "bug-fix-123"
        mock_task.title = "Fix login crash"
        mock_tasks.return_value.from_template.return_value = mock_task

        result = task_from_template("bug-fix", "Fix login crash", target_files="auth.py,login.py")
        data = json.loads(result)
        assert data["template"] == "bug-fix"
        assert data["id"] == "bug-fix-123"

    @patch("engine.skills.builtin.autonomy_skills._tasks")
    def test_task_list_templates_returns_list(self, mock_tasks):
        """task_list_templates returns available templates."""
        from engine.skills.builtin.autonomy_skills import task_list_templates
        mock_tasks.return_value.list_templates.return_value = [
            {"name": "bug-fix", "priority": "high"},
            {"name": "feature", "priority": "medium"},
        ]
        result = task_list_templates()
        data = json.loads(result)
        assert len(data) == 2


# ═══════════════════════════════════════════════════════════════════
# MCP TOOL REGISTRATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestMCPToolRegistration:
    """Verify MCP tools are registered in devtools_server."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        """Load devtools_server source once."""
        import pathlib
        self.source = pathlib.Path("engine/mcp/devtools_server.py").read_text(encoding="utf-8")

    def test_devtools_server_has_scheduler_tools(self):
        """devtools_server.py defines scheduler MCP tools."""
        assert "def scheduler_status" in self.source
        assert "def scheduler_run_now" in self.source

    def test_devtools_server_has_news_tools(self):
        """devtools_server.py defines news MCP tools."""
        assert "def news_fetch(" in self.source
        assert "def news_fetch_and_store" in self.source
        assert "def news_digest" in self.source
        assert "def news_sources" in self.source

    def test_devtools_server_has_notebook_tools(self):
        """devtools_server.py defines NLM notebook MCP tools."""
        assert "def nlm_notebook_list" in self.source
        assert "def nlm_notebook_seed" in self.source
        assert "def nlm_notebook_rotate" in self.source

    def test_devtools_server_has_quality_tools(self):
        """devtools_server.py defines quality and governance tools."""
        assert "def nexus_quality_report" in self.source
        assert "def governance_validate" in self.source
        assert "def governance_seed" in self.source
        assert "def governance_check_permission" in self.source

    def test_devtools_server_has_task_tools(self):
        """devtools_server.py defines task auto-generation tools."""
        assert "def task_auto_generate" in self.source
        assert "def task_from_template" in self.source
        assert "def task_list_templates" in self.source


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION FLOW TESTS
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationFlow:
    """Test the autonomous pipeline flow: scheduler → callbacks → Nexus → tasks."""

    @patch("engine.nexus.scheduler_daemon.get_scheduler_daemon")
    def test_scheduler_registers_all_builtin_tasks(self, mock_get):
        """Scheduler daemon registers 14 builtin tasks."""
        from engine.nexus.scheduler_daemon import _register_builtin_tasks
        daemon = MagicMock()
        _register_builtin_tasks(daemon)
        task_ids = [c.args[0] for c in daemon.register.call_args_list]
        assert daemon.register.call_count == 40
        assert "knowledge-quality" in task_ids
        assert "notebook-rotation" in task_ids
        assert "news-fetch" in task_ids
        assert "test-monitor" in task_ids
        assert "metrics-collect" in task_ids
        assert "training-sync" in task_ids
        assert "system-reflection" in task_ids
        assert "experiment-scan" in task_ids
        assert "ha-news-push" in task_ids
        assert "master-notebook-refresh" in task_ids
        assert "qa-expansion" in task_ids

    @patch("engine.nexus.self_maintenance.quality_report")
    def test_knowledge_quality_callback_calls_quality_report(self, mock_report):
        """knowledge quality callback actually calls quality_report."""
        from engine.nexus.scheduler_daemon import _knowledge_quality_callback
        mock_report.return_value = {"total_entries": 50, "stale": []}
        with patch("engine.nexus.client.get_nexus_client", side_effect=Exception):
            result = _knowledge_quality_callback()
        assert result["total_entries"] == 50

    @patch("engine.nexus.news_sources.get_news_registry")
    def test_news_callback_stores_to_nexus(self, mock_registry):
        """news callback fetches, filters, scores, and stores."""
        from engine.nexus.scheduler_daemon import _news_fetch_callback
        articles = [_mock_news_article()]
        mock_reg = mock_registry.return_value
        mock_reg.fetch_all.return_value = articles
        mock_reg.filter_articles.return_value = articles
        mock_reg.score_relevance.return_value = 0.9
        mock_reg.store_to_nexus.return_value = 1
        mock_reg.generate_digest.return_value = "# Digest"

        with patch("engine.nexus.client.get_nexus_client", side_effect=Exception):
            result = _news_fetch_callback()
        assert result["fetched"] == 1
        assert result["stored"] == 1
        mock_reg.store_to_nexus.assert_called_once()

    @patch("engine.nexus.nlm_notebook_manager.get_notebook_manager")
    def test_notebook_rotation_callback_cleans_stale(self, mock_mgr):
        """notebook rotation callback cleans up stale notebooks."""
        from engine.nexus.scheduler_daemon import _notebook_rotation_callback
        mock_mgr.return_value.cleanup_stale.return_value = ["research-old-1"]
        mock_mgr.return_value.health.return_value = {"slots": 3}

        result = _notebook_rotation_callback()
        assert result["removed_slots"] == ["research-old-1"]
        assert result["health"]["slots"] == 3

    def test_governance_manager_singleton(self):
        """GovernanceManager singleton returns same instance."""
        from engine.nexus.governance_rules import get_governance_manager
        mgr1 = get_governance_manager()
        mgr2 = get_governance_manager()
        assert mgr1 is mgr2

    def test_governance_manager_has_rules(self):
        """GovernanceManager loads 18 default rules."""
        from engine.nexus.governance_rules import get_governance_manager
        mgr = get_governance_manager()
        stats = mgr.stats()
        assert stats["total"] == 18

    def test_scheduler_daemon_singleton(self):
        """SchedulerDaemon singleton returns same instance."""
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        d1 = get_scheduler_daemon()
        d2 = get_scheduler_daemon()
        assert d1 is d2

    def test_scheduler_daemon_has_builtin_tasks(self):
        """SchedulerDaemon starts with 14 builtin tasks."""
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        status = daemon.status()
        assert status["task_count"] == 40

    def test_scheduler_daemon_task_ids(self):
        """SchedulerDaemon has the expected task IDs."""
        from engine.nexus.scheduler_daemon import get_scheduler_daemon
        daemon = get_scheduler_daemon()
        task_ids = [t["id"] for t in daemon.status()["tasks"]]
        expected = [
            "nexus-maintenance", "nexus-dedup", "knowledge-quality",
            "notebook-rotation", "news-fetch", "test-monitor",
            "metrics-collect", "training-sync",
            "system-reflection", "experiment-scan",
            "governance-audit", "ha-news-push",
            "session-distillation", "qa-generation", "copilot-self-sync",
            "master-notebook-refresh", "qa-history-mine", "qa-cache-prune",
        ]
        for tid in expected:
            assert tid in task_ids, f"Missing task: {tid}"

    def test_news_registry_singleton(self):
        """NewsSourceRegistry singleton returns same instance."""
        from engine.nexus.news_sources import get_news_registry
        r1 = get_news_registry()
        r2 = get_news_registry()
        assert r1 is r2

    def test_notebook_manager_singleton(self):
        """NLMNotebookManager singleton returns same instance."""
        from engine.nexus.nlm_notebook_manager import get_notebook_manager
        m1 = get_notebook_manager()
        m2 = get_notebook_manager()
        assert m1 is m2


class TestNLMWriteSkills:
    """Tests for the new NLM live write skills in autonomy pack."""

    def test_nlm_live_skills_importable(self):
        """All 7 new NLM live skills can be imported."""
        from engine.skills.builtin.autonomy_skills import (
            nlm_live_ask,
            nlm_live_batch_ask,
            nlm_generate_document,
            nlm_save_note,
            nlm_capture_cookies,
            nlm_proxy_meta,
            nlm_distill_notebook,
        )
        assert callable(nlm_live_ask)
        assert callable(nlm_live_batch_ask)
        assert callable(nlm_generate_document)
        assert callable(nlm_save_note)
        assert callable(nlm_capture_cookies)
        assert callable(nlm_proxy_meta)
        assert callable(nlm_distill_notebook)

    def test_nlm_live_ask_returns_error_when_proxy_offline(self):
        """nlm_live_ask returns JSON error when proxy is not running."""
        from engine.skills.builtin.autonomy_skills import nlm_live_ask
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.ask.return_value = {"error": "proxy_offline"}
            mock_get.return_value = mock_proxy
            result = nlm_live_ask("nb-123", "What is MCP?")
        data = json.loads(result)
        assert "error" in data

    def test_nlm_live_batch_ask_parses_json_questions(self):
        """nlm_live_batch_ask deserializes JSON string questions list."""
        from engine.skills.builtin.autonomy_skills import nlm_live_batch_ask
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.batch_ask.return_value = {"answers": [], "count": 0}
            mock_get.return_value = mock_proxy
            result = nlm_live_batch_ask("nb-123", '["Q1?", "Q2?"]')
        data = json.loads(result)
        assert "answers" in data
        # Verify the proxy received a list (not a string)
        call_args = mock_proxy.batch_ask.call_args
        assert isinstance(call_args[0][1], list)
        assert call_args[0][1] == ["Q1?", "Q2?"]

    def test_nlm_live_batch_ask_invalid_json_falls_back(self):
        """nlm_live_batch_ask handles invalid JSON gracefully."""
        from engine.skills.builtin.autonomy_skills import nlm_live_batch_ask
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.batch_ask.return_value = {"answers": []}
            mock_get.return_value = mock_proxy
            result = nlm_live_batch_ask("nb-123", "not json")
        assert json.loads(result) is not None
        call_args = mock_proxy.batch_ask.call_args
        assert isinstance(call_args[0][1], list)

    def test_nlm_generate_document_parses_source_ids(self):
        """nlm_generate_document deserializes source_ids JSON array."""
        from engine.skills.builtin.autonomy_skills import nlm_generate_document
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.generate_document.return_value = {"title": "Test Doc"}
            mock_get.return_value = mock_proxy
            result = nlm_generate_document("nb-123", '["src-1", "src-2"]', 2)
        data = json.loads(result)
        assert "title" in data

    def test_nlm_save_note_parses_source_ids(self):
        """nlm_save_note deserializes source_ids JSON array."""
        from engine.skills.builtin.autonomy_skills import nlm_save_note
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.save_note.return_value = {"note_id": "note-123"}
            mock_get.return_value = mock_proxy
            result = nlm_save_note("nb-123", '["src-1"]', 2)
        data = json.loads(result)
        assert "note_id" in data

    def test_nlm_capture_cookies_returns_json(self):
        """nlm_capture_cookies returns JSON response."""
        from engine.skills.builtin.autonomy_skills import nlm_capture_cookies
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.capture_cookies.return_value = {"imported_cookies": 5, "status": "ok"}
            mock_get.return_value = mock_proxy
            result = nlm_capture_cookies()
        data = json.loads(result)
        assert "imported_cookies" in data

    def test_nlm_proxy_meta_returns_json(self):
        """nlm_proxy_meta returns JSON with bl and f_sid."""
        from engine.skills.builtin.autonomy_skills import nlm_proxy_meta
        with patch("engine.mcp.notebooklm_proxy.get_notebooklm_proxy") as mock_get:
            mock_proxy = MagicMock()
            mock_proxy.get_meta.return_value = {"bl": "boq_test", "f_sid": "-1"}
            mock_get.return_value = mock_proxy
            result = nlm_proxy_meta()
        data = json.loads(result)
        assert "bl" in data
        assert "f_sid" in data

    def test_nlm_distill_notebook_offline_returns_error(self):
        """nlm_distill_notebook gracefully handles NLM proxy being offline."""
        from engine.skills.builtin.autonomy_skills import nlm_distill_notebook
        with patch("engine.nexus.nlm_qa_distiller.NLMQADistiller") as mock_cls:
            mock_distiller = MagicMock()
            mock_distiller.distill_topic.return_value = []
            mock_cls.return_value = mock_distiller
            result = nlm_distill_notebook("nb-123", "cosysim_architecture", 10)
        data = json.loads(result)
        assert data["pairs_generated"] == 0

