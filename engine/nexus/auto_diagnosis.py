"""
Auto-Diagnosis & Self-Repair — Automated failure analysis and fix generation.

When tests fail or errors spike, this module:
1. Parses failure details (file, test, traceback)
2. Searches Nexus for prior fixes to similar failures
3. If no prior fix: creates an NLM notebook with failing test + source
4. Asks NLM for diagnosis and fix suggestions
5. Stores diagnosis in Nexus for future reuse
6. Creates fix tasks for the agent fleet

This is the intelligence layer between "something broke" and "here's a fix".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data Models ────

@dataclass
class FailureInfo:
    """Parsed information about a test failure."""

    test_file: str
    test_name: str
    error_type: str
    error_message: str
    traceback: str
    source_file: str = ""
    source_line: int = 0
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.test_file}::{self.test_name}::{self.error_type}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class Diagnosis:
    """A diagnosis for a test failure."""

    failure: FailureInfo
    root_cause: str
    suggested_fix: str
    confidence: float = 0.0
    source: str = ""  # "nexus_cache", "nlm", "heuristic"
    related_entries: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ──── Failure Parser ────

_PYTEST_FAILURE_RE = re.compile(
    r"FAILED\s+([\w/\\._]+)::(\w+)",
)
_TRACEBACK_BLOCK_RE = re.compile(
    r"_{3,}\s+([\w/\\._]+::\w+)\s+_{3,}\n(.*?)(?=_{3,}|\Z)",
    re.DOTALL,
)
_ERROR_LINE_RE = re.compile(
    r"E\s+(\w+(?:Error|Exception|Warning|Failure)):\s*(.+)",
)
_FILE_LINE_RE = re.compile(
    r"([\w/\\._]+\.py):(\d+):",
)


def parse_pytest_output(output: str) -> List[FailureInfo]:
    """Parse pytest output into structured FailureInfo objects.

    Args:
        output: Raw pytest stdout+stderr output.

    Returns:
        List of FailureInfo, one per failed test.
    """
    failures: List[FailureInfo] = []
    seen_fingerprints: set = set()

    # Strategy 1: Parse FAILED lines for basic info + error type from summary
    _failed_detail_re = re.compile(
        r"FAILED\s+([\w/\\._]+)::([\w]+)\s*-\s*(\w+(?:Error|Exception|Warning|Failure)):\s*(.+)"
    )
    failed_tests = _PYTEST_FAILURE_RE.findall(output)

    # Build a map of error types from detailed FAILED lines
    detail_map: Dict[str, tuple] = {}
    for match in _failed_detail_re.finditer(output):
        key = f"{match.group(1)}::{match.group(2)}"
        detail_map[key] = (match.group(3), match.group(4).strip())

    for test_file, test_name in failed_tests:
        # Find the error type and message near this test
        error_type = "UnknownError"
        error_message = ""
        traceback = ""
        source_file = test_file
        source_line = 0

        # Check detailed FAILED line first
        key = f"{test_file}::{test_name}"
        if key in detail_map:
            error_type, error_message = detail_map[key]

        # Look for traceback block for this test
        pattern = re.compile(
            rf"_{3,}\s+{re.escape(test_name)}\s+_{3,}\n(.*?)(?=_{3,}|\Z)",
            re.DOTALL,
        )
        tb_match = pattern.search(output)
        if tb_match:
            traceback = tb_match.group(1).strip()
            # Extract error type from traceback
            err_match = _ERROR_LINE_RE.search(traceback)
            if err_match:
                error_type = err_match.group(1)
                error_message = err_match.group(2).strip()
            # Extract source file and line
            file_match = _FILE_LINE_RE.search(traceback)
            if file_match:
                source_file = file_match.group(1)
                source_line = int(file_match.group(2))

        info = FailureInfo(
            test_file=test_file,
            test_name=test_name,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback[:2000],
            source_file=source_file,
            source_line=source_line,
        )

        if info.fingerprint not in seen_fingerprints:
            seen_fingerprints.add(info.fingerprint)
            failures.append(info)

    return failures


# ──── Auto-Diagnosis Engine ────

class AutoDiagnosis:
    """Diagnoses test failures using Nexus knowledge and NLM analysis.

    The diagnosis pipeline:
    1. Parse failures from pytest output
    2. Check Nexus for prior diagnoses (by fingerprint)
    3. If cached: return immediately (free, instant)
    4. If not cached: read source files and build context
    5. Ask NLM for diagnosis (free Gemini compute)
    6. Store diagnosis in Nexus for future reuse
    7. Create fix tasks for the agent fleet

    Every diagnosis is stored, so the system gets faster over time
    as the cache fills with prior fixes.
    """

    def __init__(self) -> None:
        self._project_root = Path(__file__).resolve().parent.parent.parent

    def diagnose_output(self, pytest_output: str) -> List[Diagnosis]:
        """Parse pytest output and diagnose all failures.

        Args:
            pytest_output: Raw pytest stdout+stderr.

        Returns:
            List of Diagnosis objects, one per failure.
        """
        failures = parse_pytest_output(pytest_output)
        if not failures:
            return []

        logger.info("Diagnosing %d test failures", len(failures))
        diagnoses = []
        for failure in failures:
            diag = self._diagnose_single(failure)
            diagnoses.append(diag)

        # Store all diagnoses in Nexus
        self._store_diagnoses(diagnoses)

        return diagnoses

    def diagnose_file(self, test_file: str, test_name: str = "") -> List[Diagnosis]:
        """Run a specific test file and diagnose any failures.

        Args:
            test_file: Path to the test file.
            test_name: Optional specific test function name.

        Returns:
            List of diagnoses for failures found.
        """
        import subprocess
        import sys

        cmd = [sys.executable, "-m", "pytest", test_file, "--tb=long", "-v"]
        if test_name:
            cmd[-1] = f"{test_file}::{test_name}"
            cmd.append("--tb=long")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self._project_root),
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return [Diagnosis(
                failure=FailureInfo(
                    test_file=test_file,
                    test_name=test_name or "*",
                    error_type="TimeoutError",
                    error_message="Test timed out after 300s",
                    traceback="",
                ),
                root_cause="Test execution timed out — possible infinite loop or deadlock.",
                suggested_fix="Check for infinite loops, missing timeouts, or deadlocks in the test or source code.",
                confidence=0.5,
                source="heuristic",
            )]
        except Exception as exc:
            return [Diagnosis(
                failure=FailureInfo(
                    test_file=test_file,
                    test_name=test_name or "*",
                    error_type="ExecutionError",
                    error_message=str(exc),
                    traceback="",
                ),
                root_cause=f"Could not run test: {exc}",
                suggested_fix="Check test file exists and has no import errors.",
                confidence=0.3,
                source="heuristic",
            )]

        return self.diagnose_output(output)

    def create_fix_tasks(self, diagnoses: List[Diagnosis]) -> List[Dict[str, Any]]:
        """Create agent tasks from diagnoses.

        Args:
            diagnoses: List of Diagnosis objects.

        Returns:
            List of created task dicts with id and title.
        """
        tasks = []
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()
        except Exception as exc:
            logger.debug("Could not get task scheduler: %s", exc)
            return tasks

        for diag in diagnoses:
            if diag.confidence < 0.3:
                continue  # Skip low-confidence diagnoses

            try:
                task = scheduler.from_template(
                    "bug-fix",
                    title=f"Fix {diag.failure.test_name}: {diag.failure.error_type}",
                    description=(
                        f"## Failure\n"
                        f"Test: {diag.failure.test_file}::{diag.failure.test_name}\n"
                        f"Error: {diag.failure.error_type}: {diag.failure.error_message}\n\n"
                        f"## Diagnosis\n{diag.root_cause}\n\n"
                        f"## Suggested Fix\n{diag.suggested_fix}\n"
                    ),
                    target_files=[diag.failure.source_file] if diag.failure.source_file else [],
                )
                tasks.append({"id": task.id, "title": task.title})
            except Exception as exc:
                logger.debug("Could not create task for %s: %s", diag.failure.test_name, exc)

        return tasks

    def _diagnose_single(self, failure: FailureInfo) -> Diagnosis:
        """Diagnose a single test failure.

        Pipeline:
        1. Check Nexus cache (by fingerprint)
        2. Build context from source files
        3. Use heuristics for common patterns
        4. Ask NLM if available
        """
        # Tier 1: Check Nexus for prior diagnosis
        cached = self._check_nexus_cache(failure)
        if cached:
            logger.debug("Cache hit for %s", failure.fingerprint)
            return cached

        # Tier 2: Read source context
        context = self._build_context(failure)

        # Tier 3: Apply heuristics for common error patterns
        heuristic = self._apply_heuristics(failure, context)
        if heuristic and heuristic.confidence >= 0.8:
            return heuristic

        # Tier 4: Ask NLM for diagnosis
        nlm_diag = self._ask_nlm(failure, context)
        if nlm_diag:
            return nlm_diag

        # Tier 5: Return heuristic or best-effort
        if heuristic:
            return heuristic

        return Diagnosis(
            failure=failure,
            root_cause=f"Unknown: {failure.error_type}: {failure.error_message}",
            suggested_fix="Manual investigation required. Check the traceback for clues.",
            confidence=0.1,
            source="fallback",
        )

    def _check_nexus_cache(self, failure: FailureInfo) -> Optional[Diagnosis]:
        """Check Nexus for a prior diagnosis of this failure."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search(f"diagnosis:{failure.fingerprint}", limit=1)
            if results:
                entry = results[0]
                content = entry.get("content", "")
                # Parse stored diagnosis
                root_cause = ""
                suggested_fix = ""
                for line in content.split("\n"):
                    if line.startswith("Root cause:"):
                        root_cause = line[len("Root cause:"):].strip()
                    elif line.startswith("Fix:"):
                        suggested_fix = line[len("Fix:"):].strip()
                if root_cause:
                    return Diagnosis(
                        failure=failure,
                        root_cause=root_cause,
                        suggested_fix=suggested_fix or "See prior fix in Nexus.",
                        confidence=0.9,
                        source="nexus_cache",
                        related_entries=[str(entry.get("id", ""))],
                    )
        except Exception as exc:
            logger.debug("Nexus cache check failed: %s", exc)
        return None

    def _build_context(self, failure: FailureInfo) -> str:
        """Read source files to build diagnosis context."""
        parts = []

        # Read test file
        test_path = self._project_root / failure.test_file
        if test_path.exists():
            try:
                content = test_path.read_text(encoding="utf-8")
                # Find the failing test function
                lines = content.split("\n")
                in_test = False
                test_lines = []
                for i, line in enumerate(lines, 1):
                    if f"def {failure.test_name}" in line:
                        in_test = True
                    if in_test:
                        test_lines.append(f"{i}: {line}")
                        if len(test_lines) > 1 and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                            break
                if test_lines:
                    parts.append(f"## Test Function ({failure.test_file})\n```python\n{''.join(test_lines[:50])}\n```")
            except Exception:
                logger.debug("Could not read test file %s", failure.test_file, exc_info=True)

        # Read source file around the error line
        if failure.source_file and failure.source_file != failure.test_file:
            src_path = self._project_root / failure.source_file
            if src_path.exists():
                try:
                    content = src_path.read_text(encoding="utf-8")
                    lines = content.split("\n")
                    start = max(0, failure.source_line - 10)
                    end = min(len(lines), failure.source_line + 10)
                    snippet = "\n".join(
                        f"{i+1}: {lines[i]}" for i in range(start, end)
                    )
                    parts.append(f"## Source ({failure.source_file}:{failure.source_line})\n```python\n{snippet}\n```")
                except Exception:
                    logger.debug("Could not read source file %s", failure.source_file, exc_info=True)

        # Include traceback
        if failure.traceback:
            parts.append(f"## Traceback\n```\n{failure.traceback[:1000]}\n```")

        return "\n\n".join(parts)

    def _apply_heuristics(self, failure: FailureInfo, context: str) -> Optional[Diagnosis]:
        """Apply pattern-matching heuristics for common failures."""
        et = failure.error_type
        em = failure.error_message.lower()

        # ImportError
        if et in ("ImportError", "ModuleNotFoundError"):
            module = failure.error_message.split("'")[1] if "'" in failure.error_message else failure.error_message
            return Diagnosis(
                failure=failure,
                root_cause=f"Module '{module}' cannot be imported. Either the package is not installed or the import path is wrong.",
                suggested_fix=f"Check that '{module}' is installed (`pip install {module}`) or fix the import path to use absolute imports.",
                confidence=0.85,
                source="heuristic",
            )

        # AttributeError
        if et == "AttributeError":
            return Diagnosis(
                failure=failure,
                root_cause=f"Attribute access failed: {failure.error_message}. The object doesn't have the expected attribute/method.",
                suggested_fix="Check the object type and ensure the attribute exists. It may have been renamed or the mock is incomplete.",
                confidence=0.7,
                source="heuristic",
            )

        # TypeError (wrong arg count)
        if et == "TypeError" and ("argument" in em or "positional" in em):
            return Diagnosis(
                failure=failure,
                root_cause=f"Function signature mismatch: {failure.error_message}",
                suggested_fix="Check the function signature — the caller is passing the wrong number of arguments. A parameter may have been added or removed.",
                confidence=0.8,
                source="heuristic",
            )

        # KeyError
        if et == "KeyError":
            return Diagnosis(
                failure=failure,
                root_cause=f"Missing dictionary key: {failure.error_message}",
                suggested_fix="Use `.get(key, default)` instead of `[key]`, or ensure the key exists in the dictionary.",
                confidence=0.7,
                source="heuristic",
            )

        # AssertionError
        if et == "AssertionError":
            return Diagnosis(
                failure=failure,
                root_cause=f"Assertion failed: {failure.error_message}",
                suggested_fix="Check the expected vs actual values. The behavior or data format may have changed.",
                confidence=0.5,
                source="heuristic",
            )

        # FileNotFoundError
        if et == "FileNotFoundError":
            return Diagnosis(
                failure=failure,
                root_cause=f"File not found: {failure.error_message}",
                suggested_fix="Use tmp_path fixture for test files, or ensure the file path is correct relative to the project root.",
                confidence=0.8,
                source="heuristic",
            )

        # ConnectionError / TimeoutError
        if et in ("ConnectionError", "TimeoutError", "ConnectionRefusedError"):
            return Diagnosis(
                failure=failure,
                root_cause=f"Network connection failed: {failure.error_message}. Test is making real network calls.",
                suggested_fix="Mock the network call — tests should never make real HTTP requests. Use unittest.mock.patch on the client boundary.",
                confidence=0.9,
                source="heuristic",
            )

        return None

    def _ask_nlm(self, failure: FailureInfo, context: str) -> Optional[Diagnosis]:
        """Ask NotebookLM for a diagnosis using the NLM engine."""
        try:
            from engine.nexus.nlm_engine import get_nlm_engine
            engine = get_nlm_engine()

            # Use the codebase notebook for context
            notebooks = engine.list_notebooks()
            nb_id = None
            for nb in notebooks:
                name = nb.get("name", "").lower()
                if "cosysim" in name and ("code" in name or "arch" in name):
                    nb_id = nb.get("id") or nb.get("notebook_id")
                    break

            if not nb_id:
                return None

            question = (
                f"A test is failing. Please diagnose the root cause and suggest a fix.\n\n"
                f"Test: {failure.test_file}::{failure.test_name}\n"
                f"Error: {failure.error_type}: {failure.error_message}\n\n"
                f"{context[:3000]}\n\n"
                f"What is the root cause and how should it be fixed?"
            )

            result = engine.ask(nb_id, question)
            answer = result.get("answer", "")
            if not answer:
                return None

            # Parse answer into root cause and fix
            root_cause = answer
            suggested_fix = ""
            if "fix" in answer.lower():
                parts = re.split(r"(?i)(fix|solution|suggested|recommend)", answer, maxsplit=1)
                if len(parts) >= 2:
                    root_cause = parts[0].strip()
                    suggested_fix = "".join(parts[1:]).strip()

            return Diagnosis(
                failure=failure,
                root_cause=root_cause[:500],
                suggested_fix=suggested_fix[:500] or "See NLM analysis above.",
                confidence=0.7,
                source="nlm",
            )
        except Exception as exc:
            logger.debug("NLM diagnosis failed: %s", exc)
            return None

    def _store_diagnoses(self, diagnoses: List[Diagnosis]) -> int:
        """Store all diagnoses in Nexus for future cache hits."""
        stored = 0
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
        except Exception:
            return stored

        for diag in diagnoses:
            try:
                content = (
                    f"diagnosis:{diag.failure.fingerprint}\n"
                    f"Test: {diag.failure.test_file}::{diag.failure.test_name}\n"
                    f"Error: {diag.failure.error_type}: {diag.failure.error_message}\n"
                    f"Root cause: {diag.root_cause}\n"
                    f"Fix: {diag.suggested_fix}\n"
                    f"Source: {diag.source}\n"
                    f"Confidence: {diag.confidence}\n"
                )
                client.add_entry(
                    title=f"Diagnosis: {diag.failure.test_name} — {diag.failure.error_type}",
                    content=content,
                    content_type="note",
                    category="debugging",
                )
                stored += 1
            except Exception as exc:
                logger.debug("Could not store diagnosis: %s", exc)

        return stored

    def full_pipeline(self, pytest_output: str) -> Dict[str, Any]:
        """Run the complete auto-diagnosis pipeline.

        Args:
            pytest_output: Raw pytest output.

        Returns:
            Summary dict with diagnoses, tasks created, and stats.
        """
        diagnoses = self.diagnose_output(pytest_output)
        tasks = self.create_fix_tasks(diagnoses) if diagnoses else []

        return {
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
            "tasks": tasks,
        }


# ──── Singleton ────

_diagnosis: Optional[AutoDiagnosis] = None
_lock = threading.Lock()


def get_auto_diagnosis() -> AutoDiagnosis:
    """Get or create the singleton AutoDiagnosis instance."""
    global _diagnosis
    with _lock:
        if _diagnosis is None:
            _diagnosis = AutoDiagnosis()
    return _diagnosis


# ──── CLI ────

def main() -> None:
    """CLI entry point for auto-diagnosis.

    Usage:
        python -m engine.nexus.auto_diagnosis tests/test_foo.py
        python -m engine.nexus.auto_diagnosis tests/test_foo.py::test_bar
        python -m engine.nexus.auto_diagnosis --all
    """
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args = sys.argv[1:]
    if not args:
        logger.info("Usage: python -m engine.nexus.auto_diagnosis <test_file> [--all]")
        return

    diag = get_auto_diagnosis()

    if args[0] == "--all":
        import subprocess
        logger.info("Running full test suite...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--tb=long", "-q",
             "--ignore=tests/test_agent_loop.py", "--ignore=tests/live_wire_test.py"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(diag._project_root),
        )
        output = result.stdout + result.stderr
        summary = diag.full_pipeline(output)
    else:
        test_path = args[0]
        test_name = ""
        if "::" in test_path:
            test_path, test_name = test_path.rsplit("::", 1)
        diagnoses = diag.diagnose_file(test_path, test_name)
        summary = {
            "failures_found": len(diagnoses),
            "diagnoses": [
                {
                    "test": f"{d.failure.test_file}::{d.failure.test_name}",
                    "root_cause": d.root_cause[:200],
                    "confidence": d.confidence,
                    "source": d.source,
                }
                for d in diagnoses
            ],
        }

    logger.info("Diagnosis results:\n%s", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
