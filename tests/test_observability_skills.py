"""
Tests for engine.skills.builtin.observability_skills.

Covers:
- All 10 skills are registered in the 'observability' pack
- Each skill returns valid JSON
- query_logs returns a list with expected keys
- get_error_summary has expected structure
- get_slow_operations returns a list
- flush_old_logs returns deleted_count
- get_trace returns events list
- run_integration_tests returns a list of results
- get_integration_results returns a list
- get_flaky_tests returns a list
- probe_services returns a dict of service→bool
- register_integration_test success and error cases
- Mock StructuredLogger and IntegrationRunner throughout
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from engine.observability.structured_logger import LogEvent, LogLevel


# ---------------------------------------------------------------------------
# Helpers to build mock return values
# ---------------------------------------------------------------------------


def _make_log_event(
    service: str = "test_svc",
    level: str = "INFO",
    message: str = "test message",
    trace_id: str | None = None,
    duration_ms: float | None = None,
    error_type: str | None = None,
) -> LogEvent:
    return LogEvent(
        event_id="evt-1",
        timestamp=time.time(),
        level=level,
        logger_name=service,
        message=message,
        context={},
        trace_id=trace_id,
        span_id=None,
        service=service,
        tags=[],
        duration_ms=duration_ms,
        error_type=error_type,
        error_msg=None,
        stack_trace=None,
    )


def _make_int_result(
    test_id: str = "t1",
    passed: bool = True,
    skipped: bool = False,
) -> Any:
    from engine.testing.integration_runner import IntegrationResult

    return IntegrationResult(
        result_id="r1",
        test_id=test_id,
        passed=passed,
        skipped=skipped,
        duration_ms=10.0,
        error=None,
        logs=[],
        metrics={},
        timestamp=time.time(),
    )


# ---------------------------------------------------------------------------
# Fixture: force-import the skills module so decorators fire.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def import_skills() -> None:
    """Import the observability skills module to trigger @skill registration."""
    import engine.skills.builtin.observability_skills  # noqa: F401


# ===========================================================================
# Skill registration tests
# ===========================================================================


class TestSkillRegistration:
    """All 10 observability skills are registered in the registry."""

    EXPECTED_SKILLS = [
        "query_logs",
        "get_error_summary",
        "get_slow_operations",
        "flush_old_logs",
        "get_trace",
        "run_integration_tests",
        "get_integration_results",
        "get_flaky_tests",
        "probe_services",
        "register_integration_test",
    ]

    def test_all_skills_in_observability_pack(self) -> None:
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("observability")
        skill_names = {fn.__name__ for fn in tools}
        for expected in self.EXPECTED_SKILLS:
            assert expected in skill_names, f"Skill not registered: {expected}"

    def test_observability_pack_has_10_skills(self) -> None:
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("observability")
        assert len(tools) == 10

    def test_skills_are_callable(self) -> None:
        from engine.skills.registry import SKILL_REGISTRY

        tools = SKILL_REGISTRY.get_pack_tools("observability")
        for tool in tools:
            assert callable(tool)


# ===========================================================================
# query_logs skill
# ===========================================================================


class TestQueryLogsSkill:
    """query_logs returns valid JSON list."""

    def test_returns_valid_json(self) -> None:
        from engine.skills.builtin.observability_skills import query_logs

        mock_sl = MagicMock()
        mock_sl.query.return_value = [_make_log_event()]

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = query_logs()

        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_returns_list_of_events(self) -> None:
        from engine.skills.builtin.observability_skills import query_logs

        mock_sl = MagicMock()
        mock_sl.query.return_value = [_make_log_event(), _make_log_event()]

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = query_logs()

        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_event_has_expected_keys(self) -> None:
        from engine.skills.builtin.observability_skills import query_logs

        mock_sl = MagicMock()
        mock_sl.query.return_value = [_make_log_event(level="ERROR", error_type="ValueError")]

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = query_logs()

        event = json.loads(result)[0]
        for key in ("event_id", "timestamp", "level", "service", "message"):
            assert key in event

    def test_invalid_level_returns_error_json(self) -> None:
        from engine.skills.builtin.observability_skills import query_logs

        result = query_logs(level="BADLEVEL")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_empty_result_returns_empty_list(self) -> None:
        from engine.skills.builtin.observability_skills import query_logs

        mock_sl = MagicMock()
        mock_sl.query.return_value = []

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = query_logs()

        assert json.loads(result) == []


# ===========================================================================
# get_error_summary skill
# ===========================================================================


class TestGetErrorSummarySkill:
    """get_error_summary returns expected structure."""

    def test_returns_valid_json(self) -> None:
        from engine.skills.builtin.observability_skills import get_error_summary

        mock_sl = MagicMock()
        mock_sl.get_error_summary.return_value = {
            "period_hours": 24,
            "total_errors": 5,
            "by_type": {"ValueError": 3},
            "by_service": {"svc": 5},
        }

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_error_summary()

        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_has_total_errors_key(self) -> None:
        from engine.skills.builtin.observability_skills import get_error_summary

        mock_sl = MagicMock()
        mock_sl.get_error_summary.return_value = {
            "period_hours": 24,
            "total_errors": 0,
            "by_type": {},
            "by_service": {},
        }

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_error_summary()

        parsed = json.loads(result)
        assert "total_errors" in parsed

    def test_has_by_type_and_by_service(self) -> None:
        from engine.skills.builtin.observability_skills import get_error_summary

        mock_sl = MagicMock()
        mock_sl.get_error_summary.return_value = {
            "period_hours": 1,
            "total_errors": 2,
            "by_type": {"RuntimeError": 2},
            "by_service": {"engine": 2},
        }

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_error_summary(hours=1.0)

        parsed = json.loads(result)
        assert "by_type" in parsed
        assert "by_service" in parsed


# ===========================================================================
# get_slow_operations skill
# ===========================================================================


class TestGetSlowOperationsSkill:
    """get_slow_operations returns a list of slow span dicts."""

    def test_returns_valid_json_list(self) -> None:
        from engine.skills.builtin.observability_skills import get_slow_operations

        mock_sl = MagicMock()
        mock_sl.get_slow_operations.return_value = [
            {"event_id": "e1", "service": "svc", "message": "slow", "duration_ms": 1200.0, "timestamp": 0.0}
        ]

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_slow_operations()

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_empty_when_no_slow_ops(self) -> None:
        from engine.skills.builtin.observability_skills import get_slow_operations

        mock_sl = MagicMock()
        mock_sl.get_slow_operations.return_value = []

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_slow_operations(threshold_ms=9999)

        assert json.loads(result) == []


# ===========================================================================
# flush_old_logs skill
# ===========================================================================


class TestFlushOldLogsSkill:
    """flush_old_logs returns deleted_count."""

    def test_returns_deleted_count(self) -> None:
        from engine.skills.builtin.observability_skills import flush_old_logs

        mock_sl = MagicMock()
        mock_sl.flush_old_logs.return_value = 42

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = flush_old_logs(days=7)

        parsed = json.loads(result)
        assert parsed["deleted_count"] == 42
        assert parsed["days"] == 7

    def test_returns_valid_json(self) -> None:
        from engine.skills.builtin.observability_skills import flush_old_logs

        mock_sl = MagicMock()
        mock_sl.flush_old_logs.return_value = 0

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = flush_old_logs()

        json.loads(result)  # must not raise


# ===========================================================================
# get_trace skill
# ===========================================================================


class TestGetTraceSkill:
    """get_trace returns all events for a trace_id."""

    def test_returns_events_list(self) -> None:
        from engine.skills.builtin.observability_skills import get_trace

        mock_sl = MagicMock()
        mock_sl.get_trace.return_value = [
            _make_log_event(trace_id="tr-1"),
            _make_log_event(trace_id="tr-1"),
        ]

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_trace("tr-1")

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_empty_for_unknown_trace(self) -> None:
        from engine.skills.builtin.observability_skills import get_trace

        mock_sl = MagicMock()
        mock_sl.get_trace.return_value = []

        with patch("engine.skills.builtin.observability_skills._sl", return_value=mock_sl):
            result = get_trace("unknown")

        assert json.loads(result) == []


# ===========================================================================
# run_integration_tests skill
# ===========================================================================


class TestRunIntegrationTestsSkill:
    """run_integration_tests returns a list of result dicts."""

    def test_returns_list(self) -> None:
        from engine.skills.builtin.observability_skills import run_integration_tests

        mock_ir = MagicMock()
        mock_ir.run.return_value = [_make_int_result(), _make_int_result(passed=False)]

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = run_integration_tests()

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_result_has_expected_keys(self) -> None:
        from engine.skills.builtin.observability_skills import run_integration_tests

        mock_ir = MagicMock()
        mock_ir.run.return_value = [_make_int_result()]

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = run_integration_tests()

        item = json.loads(result)[0]
        for key in ("test_id", "passed", "skipped", "duration_ms"):
            assert key in item

    def test_tag_filter_passed_to_runner(self) -> None:
        from engine.skills.builtin.observability_skills import run_integration_tests

        mock_ir = MagicMock()
        mock_ir.run.return_value = []

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            run_integration_tests(tags="smoke,fast")

        call_kwargs = mock_ir.run.call_args
        assert call_kwargs.kwargs.get("tags") == ["smoke", "fast"]


# ===========================================================================
# get_integration_results skill
# ===========================================================================


class TestGetIntegrationResultsSkill:
    """get_integration_results returns a list of result dicts."""

    def test_returns_valid_json_list(self) -> None:
        from engine.skills.builtin.observability_skills import get_integration_results

        mock_ir = MagicMock()
        mock_ir.get_results.return_value = [_make_int_result()]

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = get_integration_results()

        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_returns_empty_list_when_no_results(self) -> None:
        from engine.skills.builtin.observability_skills import get_integration_results

        mock_ir = MagicMock()
        mock_ir.get_results.return_value = []

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = get_integration_results()

        assert json.loads(result) == []


# ===========================================================================
# get_flaky_tests skill
# ===========================================================================


class TestGetFlakyTestsSkill:
    """get_flaky_tests returns a list of flaky test info."""

    def test_returns_valid_json_list(self) -> None:
        from engine.skills.builtin.observability_skills import get_flaky_tests

        mock_ir = MagicMock()
        mock_ir.get_flaky_tests.return_value = [
            {"test_id": "t1", "total_runs": 5, "failures": 2, "failure_rate": 0.4}
        ]

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = get_flaky_tests()

        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_empty_when_no_flaky(self) -> None:
        from engine.skills.builtin.observability_skills import get_flaky_tests

        mock_ir = MagicMock()
        mock_ir.get_flaky_tests.return_value = []

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = get_flaky_tests()

        assert json.loads(result) == []


# ===========================================================================
# probe_services skill
# ===========================================================================


class TestProbeServicesSkill:
    """probe_services returns a dict of service → bool."""

    def test_returns_valid_json_dict(self) -> None:
        from engine.skills.builtin.observability_skills import probe_services

        mock_ir = MagicMock()
        mock_ir.probe_services.return_value = {
            "lmstudio": False,
            "nexus": False,
            "comfyui": False,
            "mcp": True,
        }

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = probe_services()

        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_has_known_service_keys(self) -> None:
        from engine.skills.builtin.observability_skills import probe_services

        mock_ir = MagicMock()
        mock_ir.probe_services.return_value = {
            "lmstudio": False,
            "nexus": False,
            "comfyui": False,
            "mcp": True,
        }

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = probe_services()

        parsed = json.loads(result)
        assert "lmstudio" in parsed
        assert "nexus" in parsed

    def test_values_are_booleans(self) -> None:
        from engine.skills.builtin.observability_skills import probe_services

        mock_ir = MagicMock()
        mock_ir.probe_services.return_value = {"lmstudio": False, "mcp": True}

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = probe_services()

        parsed = json.loads(result)
        for v in parsed.values():
            assert isinstance(v, bool)


# ===========================================================================
# register_integration_test skill
# ===========================================================================


class TestRegisterIntegrationTestSkill:
    """register_integration_test — success and error paths."""

    def test_successful_registration(self) -> None:
        from engine.skills.builtin.observability_skills import register_integration_test

        mock_ir = MagicMock()
        mock_ir.register_dynamic.return_value = "my_dynamic_test"

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = register_integration_test(
                name="My Dynamic Test",
                services_json="[]",
                test_code="def run_test(): pass",
            )

        parsed = json.loads(result)
        assert parsed["status"] == "registered"
        assert "test_id" in parsed

    def test_invalid_services_json(self) -> None:
        from engine.skills.builtin.observability_skills import register_integration_test

        result = register_integration_test(
            name="Bad Services",
            services_json="{not_a_list}",
            test_code="def run_test(): pass",
        )
        parsed = json.loads(result)
        assert "error" in parsed

    def test_invalid_code_returns_error(self) -> None:
        from engine.skills.builtin.observability_skills import register_integration_test

        mock_ir = MagicMock()
        mock_ir.register_dynamic.side_effect = ValueError("run_test not defined")

        with patch("engine.skills.builtin.observability_skills._ir", return_value=mock_ir):
            result = register_integration_test(
                name="Bad Code",
                services_json="[]",
                test_code="def wrong_name(): pass",
            )

        parsed = json.loads(result)
        assert "error" in parsed

    def test_non_list_services_json(self) -> None:
        from engine.skills.builtin.observability_skills import register_integration_test

        result = register_integration_test(
            name="Bad",
            services_json='"a_string"',
            test_code="def run_test(): pass",
        )
        parsed = json.loads(result)
        assert "error" in parsed
