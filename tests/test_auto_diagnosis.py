"""
Tests for the auto-diagnosis module.

Validates failure parsing, heuristic diagnosis, NLM integration,
Nexus caching, and fix task generation.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.auto_diagnosis import (
    AutoDiagnosis,
    Diagnosis,
    FailureInfo,
    get_auto_diagnosis,
    parse_pytest_output,
)


# ═══════════════════════════════════════════════════════════════════
# FIXTURES & HELPERS
# ═══════════════════════════════════════════════════════════════════

SAMPLE_PYTEST_OUTPUT = """
============================= test session starts =============================
collected 100 items

tests/test_foo.py::test_bar PASSED
tests/test_foo.py::test_baz FAILED
tests/test_bar.py::test_qux FAILED

================================== FAILURES ===================================
_____________________________ test_baz _____________________________

tests/test_foo.py:42: in test_baz
    result = do_thing(123)
engine/core.py:15: in do_thing
    return data["missing_key"]
E   KeyError: 'missing_key'

_____________________________ test_qux _____________________________

tests/test_bar.py:10: in test_qux
    import nonexistent_module
E   ModuleNotFoundError: No module named 'nonexistent_module'

=========================== short test summary info ===========================
FAILED tests/test_foo.py::test_baz - KeyError: 'missing_key'
FAILED tests/test_bar.py::test_qux - ModuleNotFoundError: No module named 'nonexistent_module'
======================== 1 passed, 2 failed in 0.42s =========================
"""

SAMPLE_ASSERTION_OUTPUT = """
FAILED tests/test_scene.py::test_scene_state - AssertionError: assert 'ready' == 'loading'
"""

SAMPLE_TIMEOUT_OUTPUT = """
FAILED tests/test_slow.py::test_hang - TimeoutError: Test timed out
"""

SAMPLE_CONNECTION_OUTPUT = """
FAILED tests/test_api.py::test_connect - ConnectionRefusedError: Connection refused
"""

SAMPLE_ATTRIBUTE_OUTPUT = """
_____________________________ test_attr _____________________________
tests/test_attr.py:5: in test_attr
    obj.missing_method()
E   AttributeError: 'MyClass' object has no attribute 'missing_method'

FAILED tests/test_attr.py::test_attr - AttributeError: 'MyClass' object has no attribute 'missing_method'
"""

SAMPLE_TYPEERROR_OUTPUT = """
_____________________________ test_args _____________________________
tests/test_args.py:5: in test_args
    func(1, 2, 3)
E   TypeError: func() takes 2 positional arguments but 3 were given

FAILED tests/test_args.py::test_args - TypeError: func() takes 2 positional arguments but 3 were given
"""


# ═══════════════════════════════════════════════════════════════════
# PARSER TESTS
# ═══════════════════════════════════════════════════════════════════

class TestParsePytestOutput:
    """Test failure parsing from pytest output."""

    def test_parse_finds_failures(self):
        """Parser extracts both failed tests."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        assert len(failures) == 2

    def test_parse_extracts_test_file(self):
        """Parser extracts correct test file paths."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        files = {f.test_file for f in failures}
        assert "tests/test_foo.py" in files
        assert "tests/test_bar.py" in files

    def test_parse_extracts_test_names(self):
        """Parser extracts correct test function names."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        names = {f.test_name for f in failures}
        assert "test_baz" in names
        assert "test_qux" in names

    def test_parse_extracts_error_types(self):
        """Parser extracts error types from traceback blocks."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        types = {f.error_type for f in failures}
        assert "KeyError" in types
        assert "ModuleNotFoundError" in types

    def test_parse_generates_fingerprints(self):
        """Each failure gets a unique fingerprint."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        fingerprints = {f.fingerprint for f in failures}
        assert len(fingerprints) == 2

    def test_parse_deduplicates(self):
        """Duplicate failures are not repeated."""
        doubled = SAMPLE_PYTEST_OUTPUT + SAMPLE_PYTEST_OUTPUT
        failures = parse_pytest_output(doubled)
        assert len(failures) == 2

    def test_parse_no_failures(self):
        """Parser returns empty list when no failures."""
        output = "10 passed in 1.0s"
        assert parse_pytest_output(output) == []

    def test_parse_extracts_source_file(self):
        """Parser extracts source file from traceback."""
        failures = parse_pytest_output(SAMPLE_PYTEST_OUTPUT)
        baz = [f for f in failures if f.test_name == "test_baz"][0]
        # Should find engine/core.py from the traceback
        assert baz.source_file  # Has some source file

    def test_parse_assertion_error(self):
        """Parser handles AssertionError."""
        failures = parse_pytest_output(SAMPLE_ASSERTION_OUTPUT)
        assert len(failures) == 1
        assert failures[0].test_name == "test_scene_state"

    def test_parse_connection_error(self):
        """Parser handles ConnectionRefusedError."""
        failures = parse_pytest_output(SAMPLE_CONNECTION_OUTPUT)
        assert len(failures) == 1
        assert failures[0].test_name == "test_connect"


# ═══════════════════════════════════════════════════════════════════
# FAILURE INFO TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFailureInfo:
    """Test FailureInfo dataclass."""

    def test_fingerprint_auto_generated(self):
        """Fingerprint is auto-generated from test path and error type."""
        info = FailureInfo(
            test_file="tests/test_foo.py",
            test_name="test_bar",
            error_type="KeyError",
            error_message="missing_key",
            traceback="",
        )
        assert len(info.fingerprint) == 12

    def test_fingerprint_deterministic(self):
        """Same inputs produce same fingerprint."""
        info1 = FailureInfo("t.py", "test_x", "KeyError", "k", "")
        info2 = FailureInfo("t.py", "test_x", "KeyError", "k", "")
        assert info1.fingerprint == info2.fingerprint

    def test_fingerprint_varies_by_test(self):
        """Different tests produce different fingerprints."""
        info1 = FailureInfo("t.py", "test_x", "KeyError", "k", "")
        info2 = FailureInfo("t.py", "test_y", "KeyError", "k", "")
        assert info1.fingerprint != info2.fingerprint


# ═══════════════════════════════════════════════════════════════════
# HEURISTIC DIAGNOSIS TESTS
# ═══════════════════════════════════════════════════════════════════

class TestHeuristics:
    """Test heuristic diagnosis patterns."""

    def setup_method(self):
        """Create a fresh AutoDiagnosis."""
        self.diag = AutoDiagnosis()

    def test_import_error_heuristic(self):
        """ImportError produces high-confidence diagnosis."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "ImportError",
            "No module named 'foo'", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert result.confidence >= 0.8
        assert "foo" in result.root_cause

    def test_module_not_found_heuristic(self):
        """ModuleNotFoundError produces diagnosis."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "ModuleNotFoundError",
            "No module named 'bar'", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert result.confidence >= 0.8

    def test_attribute_error_heuristic(self):
        """AttributeError produces diagnosis."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "AttributeError",
            "'X' object has no attribute 'y'", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert result.source == "heuristic"

    def test_type_error_arg_count(self):
        """TypeError with argument mismatch diagnosed."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "TypeError",
            "func() takes 2 positional arguments but 3 were given", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert result.confidence >= 0.7

    def test_key_error_heuristic(self):
        """KeyError produces diagnosis suggesting .get()."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "KeyError",
            "'missing_key'", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert ".get(" in result.suggested_fix

    def test_file_not_found_heuristic(self):
        """FileNotFoundError produces diagnosis."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "FileNotFoundError",
            "No such file: '/tmp/test.db'", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert "tmp_path" in result.suggested_fix

    def test_connection_error_heuristic(self):
        """ConnectionError diagnosed as unmocked network call."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "ConnectionError",
            "Connection refused", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is not None
        assert result.confidence >= 0.9
        assert "mock" in result.suggested_fix.lower()

    def test_unknown_error_no_heuristic(self):
        """Unknown error types return None from heuristics."""
        failure = FailureInfo(
            "tests/t.py", "test_x", "CustomWeirdError",
            "something weird happened", "", "",
        )
        result = self.diag._apply_heuristics(failure, "")
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# FULL PIPELINE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """Test the complete diagnosis pipeline."""

    def setup_method(self):
        """Create fresh AutoDiagnosis."""
        self.diag = AutoDiagnosis()

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_diagnose_output_returns_diagnoses(self, mock_nexus):
        """diagnose_output produces diagnoses from pytest output."""
        diagnoses = self.diag.diagnose_output(SAMPLE_PYTEST_OUTPUT)
        assert len(diagnoses) == 2

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_diagnose_output_has_root_causes(self, mock_nexus):
        """Each diagnosis has a root cause."""
        diagnoses = self.diag.diagnose_output(SAMPLE_PYTEST_OUTPUT)
        for d in diagnoses:
            assert d.root_cause, f"Missing root_cause for {d.failure.test_name}"

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_diagnose_output_has_suggested_fixes(self, mock_nexus):
        """Each diagnosis has a suggested fix."""
        diagnoses = self.diag.diagnose_output(SAMPLE_PYTEST_OUTPUT)
        for d in diagnoses:
            assert d.suggested_fix, f"Missing suggested_fix for {d.failure.test_name}"

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_full_pipeline_returns_summary(self, mock_nexus):
        """full_pipeline returns structured summary."""
        result = self.diag.full_pipeline(SAMPLE_PYTEST_OUTPUT)
        assert "failures_found" in result
        assert "diagnoses" in result
        assert "tasks_created" in result
        assert result["failures_found"] == 2

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_full_pipeline_no_failures(self, mock_nexus):
        """full_pipeline returns empty results when no failures."""
        result = self.diag.full_pipeline("10 passed in 1.0s")
        assert result["failures_found"] == 0
        assert result["diagnoses"] == []

    @patch("engine.nexus.client.get_nexus_client")
    def test_nexus_cache_hit(self, mock_nexus_client):
        """Nexus cache hit returns cached diagnosis."""
        mock_client = MagicMock()
        mock_nexus_client.return_value = mock_client
        mock_client.search.return_value = [
            {
                "id": 42,
                "content": "diagnosis:abc123\nRoot cause: Cached root cause\nFix: Cached fix",
            }
        ]

        failure = FailureInfo("t.py", "test_x", "KeyError", "k", "")
        result = self.diag._check_nexus_cache(failure)
        assert result is not None
        assert result.source == "nexus_cache"
        assert result.confidence == 0.9
        assert "Cached root cause" in result.root_cause

    @patch("engine.nexus.client.get_nexus_client", side_effect=Exception("no nexus"))
    def test_nexus_cache_miss(self, mock_nexus):
        """Nexus cache miss returns None."""
        failure = FailureInfo("t.py", "test_x", "KeyError", "k", "")
        result = self.diag._check_nexus_cache(failure)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# TASK CREATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestTaskCreation:
    """Test fix task generation from diagnoses."""

    def setup_method(self):
        """Create fresh AutoDiagnosis."""
        self.diag = AutoDiagnosis()

    @patch("engine.nexus.task_scheduler.get_task_scheduler")
    def test_creates_tasks_from_diagnoses(self, mock_scheduler):
        """create_fix_tasks creates tasks for confident diagnoses."""
        mock_task = MagicMock()
        mock_task.id = "fix-1"
        mock_task.title = "Fix test_x"
        mock_scheduler.return_value.from_template.return_value = mock_task

        diagnoses = [
            Diagnosis(
                failure=FailureInfo("t.py", "test_x", "KeyError", "k", ""),
                root_cause="Missing key",
                suggested_fix="Use .get()",
                confidence=0.8,
                source="heuristic",
            ),
        ]
        tasks = self.diag.create_fix_tasks(diagnoses)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "fix-1"

    @patch("engine.nexus.task_scheduler.get_task_scheduler")
    def test_skips_low_confidence(self, mock_scheduler):
        """create_fix_tasks skips low-confidence diagnoses."""
        diagnoses = [
            Diagnosis(
                failure=FailureInfo("t.py", "test_x", "WeirdError", "x", ""),
                root_cause="Unknown",
                suggested_fix="Investigate",
                confidence=0.1,
                source="fallback",
            ),
        ]
        tasks = self.diag.create_fix_tasks(diagnoses)
        assert len(tasks) == 0

    @patch("engine.nexus.task_scheduler.get_task_scheduler", side_effect=Exception("no scheduler"))
    def test_handles_scheduler_unavailable(self, mock_scheduler):
        """create_fix_tasks handles missing scheduler gracefully."""
        diagnoses = [
            Diagnosis(
                failure=FailureInfo("t.py", "test_x", "KeyError", "k", ""),
                root_cause="x",
                suggested_fix="y",
                confidence=0.8,
                source="heuristic",
            ),
        ]
        tasks = self.diag.create_fix_tasks(diagnoses)
        assert tasks == []


# ═══════════════════════════════════════════════════════════════════
# SINGLETON & SKILL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """get_auto_diagnosis returns the same instance."""
        d1 = get_auto_diagnosis()
        d2 = get_auto_diagnosis()
        assert d1 is d2

    def test_skill_exists(self):
        """diagnose_failures skill is registered."""
        from engine.skills.registry import SKILL_REGISTRY
        assert SKILL_REGISTRY.get_skill("diagnose_failures") is not None

    def test_diagnose_test_file_skill_exists(self):
        """diagnose_test_file skill is registered."""
        from engine.skills.registry import SKILL_REGISTRY
        assert SKILL_REGISTRY.get_skill("diagnose_test_file") is not None
