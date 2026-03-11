"""Smart test runner for CosySim — tiered, git-diff-aware, timing-cached.

Selects and orders tests intelligently based on git changes, tier levels,
and historical timing data. Replaces brute-force full-suite runs with
targeted, speed-ranked execution.

Usage:
    python scripts/smart_test_runner.py                    # Auto: git-diff + tier 2
    python scripts/smart_test_runner.py --tier 1           # Quick smoke test
    python scripts/smart_test_runner.py --tier 3           # Integration
    python scripts/smart_test_runner.py --full             # Everything
    python scripts/smart_test_runner.py --changed          # Only changed file tests
    python scripts/smart_test_runner.py --file tests/test_penthouse*.py
    python scripts/smart_test_runner.py --report           # Generate timing report
"""
from __future__ import annotations

import argparse
import datetime
import glob as glob_mod
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ──── Constants ───────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
DEFAULT_TIMING_CACHE = ROOT / "data" / "test_timing.json"
DEFAULT_REPORTS_DIR = ROOT / "data" / "test_reports"

logger = logging.getLogger(__name__)

# ──── Tier Definitions ────────────────────────────────────────────────────────

TIER_DEFINITIONS: Dict[int, Dict[str, Any]] = {
    1: {
        "label": "Smoke (<30s)",
        "timeout": 30,
        "patterns": [
            "test_scene_imports*",
            "test_skill*",
            "test_config*",
            "test_config_validator*",
            "test_decorators*",
            "test_port_registry*",
        ],
    },
    2: {
        "label": "Core (<2min)",
        "timeout": 120,
        "patterns": [
            "test_penthouse*",
            "test_phone*",
            "test_lab*",
            "test_lounge*",
            "test_tavern*",
            "test_casino*",
            "test_gallery*",
            "test_arena*",
            "test_realm*",
            "test_neoncity*",
            "test_heist*",
            "test_games*",
            "test_coders*",
            "test_hub*",
            "test_intel_hub*",
            "test_multiplayer*",
            "test_database*",
            "test_event_chain*",
            "test_dialog_system*",
            "test_stream_processor*",
            "test_character*",
            "test_scene_state*",
            "test_scene_rules*",
            "test_router*",
            "test_governance*",
            "test_skills*",
            "test_memory_skills*",
            "test_social_skills*",
            "test_world_skills*",
            "test_announcer*",
            "test_navbar*",
            "test_tts*",
        ],
    },
    3: {
        "label": "Integration (<5min)",
        "timeout": 300,
        "patterns": [
            "test_pipeline*",
            "test_copilot*",
            "test_nexus*",
            "test_nlm*",
            "test_news*",
            "test_training*",
            "test_benchmark*",
            "test_lmstudio*",
            "test_lms*",
            "test_argus*",
            "test_har*",
            "test_model*",
            "test_vam*",
            "test_integration*",
        ],
    },
    4: {
        "label": "Full (everything)",
        "timeout": 1800,
        "patterns": ["test_*"],
    },
}

SKIP_PATTERNS: List[str] = [
    "test_agent_loop.py",
    "live_wire_test.py",
]

# ──── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    """Result of a single test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    test_files: List[str] = field(default_factory=list)
    slowest_tests: List[Dict[str, Any]] = field(default_factory=list)
    return_code: int = 0
    tier: Optional[int] = None
    timestamp: str = ""
    raw_output: str = ""


# ──── Source → Test Mapping ───────────────────────────────────────────────────


def map_source_to_tests(changed_file: str) -> List[str]:
    """Map a changed source file to its corresponding test file(s).

    Args:
        changed_file: Relative path of the changed file from repo root.

    Returns:
        List of glob patterns that match potential test files.
    """
    p = Path(changed_file)
    patterns: List[str] = []

    if not changed_file.endswith(".py"):
        return patterns

    stem = p.stem

    # Already a test file — return itself
    if stem.startswith("test_"):
        return [str(TESTS_DIR / p.name)]

    # engine/skills/builtin/X_skills.py → tests/test_X_skills.py
    if "skills" in p.parts and stem.endswith("_skills"):
        patterns.append(str(TESTS_DIR / f"test_{stem}.py"))

    # content/scenes/<scene_name>/*.py → tests/test_<scene_name>*.py
    if "scenes" in p.parts:
        try:
            idx = list(p.parts).index("scenes")
            scene_name = p.parts[idx + 1] if idx + 1 < len(p.parts) else None
            if scene_name:
                patterns.append(str(TESTS_DIR / f"test_{scene_name}*.py"))
        except (ValueError, IndexError):
            pass

    # engine/foo/bar.py → tests/test_bar.py
    if not patterns:
        patterns.append(str(TESTS_DIR / f"test_{stem}.py"))

    # engine/nexus/*.py → also pick up test_nexus*.py
    if "nexus" in p.parts and f"test_{stem}.py" not in str(patterns):
        patterns.append(str(TESTS_DIR / "test_nexus*.py"))

    # engine/mcp/*.py → test_mcp* or test matching
    if "mcp" in p.parts:
        patterns.append(str(TESTS_DIR / f"test_{stem}.py"))

    return patterns


# ──── Git Diff Detection ──────────────────────────────────────────────────────


def get_changed_files(ref: str = "HEAD") -> List[str]:
    """Get list of changed files via git diff.

    Args:
        ref: Git ref to diff against. Defaults to HEAD (unstaged + staged).

    Returns:
        List of changed file paths relative to repo root.
    """
    changed: List[str] = []

    try:
        # Unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if result.returncode == 0:
            changed.extend(result.stdout.strip().splitlines())

        # Staged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if result.returncode == 0:
            changed.extend(result.stdout.strip().splitlines())

        # Committed but not pushed (vs ref)
        if ref != "HEAD":
            result = subprocess.run(
                ["git", "diff", "--name-only", ref],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            if result.returncode == 0:
                changed.extend(result.stdout.strip().splitlines())

    except FileNotFoundError:
        logger.warning("git not found in PATH — cannot detect changes")

    # Deduplicate and filter to .py files
    seen: set[str] = set()
    unique: List[str] = []
    for f in changed:
        f = f.strip()
        if f and f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def resolve_test_files_from_changes(changed_files: List[str]) -> List[str]:
    """Resolve changed source files to existing test file paths.

    Args:
        changed_files: List of changed file paths.

    Returns:
        Sorted list of unique, existing test file paths.
    """
    test_patterns: List[str] = []
    for cf in changed_files:
        test_patterns.extend(map_source_to_tests(cf))

    resolved: set[str] = set()
    for pattern in test_patterns:
        # Use glob to resolve wildcards
        matches = glob_mod.glob(pattern)
        for m in matches:
            mp = Path(m)
            if mp.exists() and mp.name not in SKIP_PATTERNS:
                resolved.add(str(mp))

    return sorted(resolved)


# ──── Tier-Based File Collection ──────────────────────────────────────────────


def collect_tier_files(tier: int) -> List[str]:
    """Collect test files for a given tier (cumulative — tier N includes 1..N).

    Args:
        tier: Tier level (1-4).

    Returns:
        Sorted list of test file paths.
    """
    collected: set[str] = set()

    for t in range(1, tier + 1):
        tier_def = TIER_DEFINITIONS.get(t)
        if not tier_def:
            continue
        for pattern in tier_def["patterns"]:
            matches = glob_mod.glob(str(TESTS_DIR / pattern))
            for m in matches:
                mp = Path(m)
                if mp.is_file() and mp.name not in SKIP_PATTERNS:
                    collected.add(str(mp))

    return sorted(collected)


# ──── Timing Cache ────────────────────────────────────────────────────────────


def load_timing_cache(cache_path: Path) -> Dict[str, float]:
    """Load test timing data from JSON cache.

    Args:
        cache_path: Path to the timing cache JSON file.

    Returns:
        Dict mapping test file paths to duration in seconds.
    """
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Failed to load timing cache: %s", exc)
        return {}


def save_timing_cache(
    cache_path: Path,
    existing: Dict[str, float],
    new_timings: Dict[str, float],
) -> None:
    """Merge and save timing data to cache.

    Args:
        cache_path: Path to the timing cache JSON file.
        existing: Previously loaded timing data.
        new_timings: New timing data from the current run.
    """
    merged = {**existing, **new_timings}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, sort_keys=True)
        logger.debug("Timing cache updated: %s entries", len(merged))
    except OSError as exc:
        logger.warning("Failed to save timing cache: %s", exc)


def order_by_speed(
    test_files: List[str], timings: Dict[str, float]
) -> List[str]:
    """Order test files by historical speed — fastest first.

    Files without timing data are placed after known-fast files but
    before known-slow ones (assumed median).

    Args:
        test_files: List of test file paths.
        timings: Historical timing data.

    Returns:
        Reordered list of test file paths.
    """
    if not timings:
        return test_files

    known_times = [t for t in timings.values() if t > 0]
    median = sorted(known_times)[len(known_times) // 2] if known_times else 5.0

    def sort_key(path: str) -> float:
        # Normalize path for lookup
        name = Path(path).name
        for key, val in timings.items():
            if Path(key).name == name:
                return val
        return median

    return sorted(test_files, key=sort_key)


# ──── Pytest Execution ────────────────────────────────────────────────────────


def parse_pytest_output(output: str) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """Parse pytest output for pass/fail/skip counts and slowest tests.

    Args:
        output: Raw stdout from pytest.

    Returns:
        Tuple of (passed, failed, skipped, errors, slowest_tests).
    """
    passed = 0
    failed = 0
    skipped = 0
    errors = 0
    slowest: List[Dict[str, Any]] = []

    # Parse summary line: "X passed, Y failed, Z skipped, W error"
    summary_pattern = re.compile(
        r"(?:=+ )?"
        r"(?:(\d+) passed)?"
        r"(?:,?\s*(\d+) failed)?"
        r"(?:,?\s*(\d+) skipped)?"
        r"(?:,?\s*(\d+) warnings?)?"
        r"(?:,?\s*(\d+) errors?)?"
        r"(?:,?\s*(\d+) deselected)?"
    )
    for line in output.splitlines():
        m = summary_pattern.search(line)
        if m:
            if m.group(1):
                passed = max(passed, int(m.group(1)))
            if m.group(2):
                failed = max(failed, int(m.group(2)))
            if m.group(3):
                skipped = max(skipped, int(m.group(3)))
            if m.group(5):
                errors = max(errors, int(m.group(5)))

    # Parse --durations output: "Xs call     tests/test_foo.py::test_bar"
    dur_pattern = re.compile(r"(\d+\.\d+)s\s+(call|setup|teardown)\s+(.+)")
    for line in output.splitlines():
        m = dur_pattern.search(line)
        if m and m.group(2) == "call":
            slowest.append({
                "test": m.group(3).strip(),
                "duration": float(m.group(1)),
            })

    # Sort by duration descending, keep top 10
    slowest.sort(key=lambda x: x["duration"], reverse=True)
    return passed, failed, skipped, errors, slowest[:10]


def extract_file_timings(output: str) -> Dict[str, float]:
    """Extract per-file timing from pytest durations output.

    Args:
        output: Raw stdout from pytest.

    Returns:
        Dict mapping test file paths to total duration.
    """
    file_times: Dict[str, float] = {}
    dur_pattern = re.compile(r"(\d+\.\d+)s\s+call\s+(\S+?)::(\S+)")

    for line in output.splitlines():
        m = dur_pattern.search(line)
        if m:
            duration = float(m.group(1))
            test_path = m.group(2).strip()
            file_times[test_path] = file_times.get(test_path, 0.0) + duration

    return file_times


def run_pytest(
    test_files: List[str],
    parallel_workers: int = 0,
    extra_args: Optional[List[str]] = None,
    timeout: int = 600,
) -> TestResult:
    """Execute pytest with the given test files.

    Args:
        test_files: List of test file paths to run.
        parallel_workers: Number of parallel workers (0 = sequential).
        extra_args: Additional pytest arguments.
        timeout: Maximum runtime in seconds.

    Returns:
        TestResult with parsed output.
    """
    if not test_files:
        logger.info("No test files to run")
        return TestResult(timestamp=_now_iso())

    cmd: List[str] = [
        sys.executable, "-m", "pytest",
        "-v",
        "--tb=short",
        "--no-header",
        f"--durations=20",
        "--strict-markers",
    ]

    if parallel_workers > 1:
        cmd.extend(["-n", str(parallel_workers)])

    if extra_args:
        cmd.extend(extra_args)

    cmd.extend(test_files)

    logger.info("Running %d test file(s)...", len(test_files))
    logger.debug("Command: %s", " ".join(cmd))

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("Test run timed out after %ds", timeout)
        return TestResult(
            duration_seconds=float(timeout),
            test_files=test_files,
            return_code=-1,
            timestamp=_now_iso(),
            raw_output=f"TIMEOUT after {timeout}s",
        )

    elapsed = time.monotonic() - start
    output = proc.stdout + "\n" + proc.stderr
    passed, failed, skipped, errors, slowest = parse_pytest_output(output)

    return TestResult(
        total=passed + failed + skipped + errors,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_seconds=round(elapsed, 2),
        test_files=test_files,
        slowest_tests=slowest,
        return_code=proc.returncode,
        timestamp=_now_iso(),
        raw_output=output,
    )


# ──── Report Generation ───────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def print_summary(result: TestResult) -> None:
    """Print a human-readable test summary to the console via logging.

    Args:
        result: TestResult from a run.
    """
    tier_label = f" (Tier {result.tier})" if result.tier else ""
    status = "PASSED" if result.return_code == 0 else "FAILED"

    lines = [
        "",
        f"{'=' * 70}",
        f"  TEST SUMMARY{tier_label} — {status}",
        f"{'=' * 70}",
        f"  Files:    {len(result.test_files)}",
        f"  Total:    {result.total}",
        f"  Passed:   {result.passed}",
        f"  Failed:   {result.failed}",
        f"  Skipped:  {result.skipped}",
        f"  Errors:   {result.errors}",
        f"  Duration: {result.duration_seconds:.1f}s",
        f"{'─' * 70}",
    ]

    if result.slowest_tests:
        lines.append("  Slowest tests:")
        for i, t in enumerate(result.slowest_tests[:10], 1):
            lines.append(f"    {i:2d}. {t['duration']:7.2f}s  {t['test']}")
        lines.append(f"{'=' * 70}")

    for line in lines:
        logger.info(line)


def save_report(result: TestResult, reports_dir: Path) -> Path:
    """Save test result as a JSON report.

    Args:
        result: TestResult from a run.
        reports_dir: Directory to save reports in.

    Returns:
        Path to the saved report file.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tier_suffix = f"_tier{result.tier}" if result.tier else ""
    report_path = reports_dir / f"test_report_{ts}{tier_suffix}.json"

    report_data = {
        "timestamp": result.timestamp,
        "tier": result.tier,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
        "duration_seconds": result.duration_seconds,
        "test_files": [str(Path(f).name) for f in result.test_files],
        "slowest_tests": result.slowest_tests,
        "return_code": result.return_code,
        "status": "PASSED" if result.return_code == 0 else "FAILED",
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    logger.info("Report saved: %s", report_path)
    return report_path


def generate_timing_report(cache_path: Path) -> None:
    """Print a timing report from the cached data.

    Args:
        cache_path: Path to the timing cache JSON file.
    """
    timings = load_timing_cache(cache_path)
    if not timings:
        logger.info("No timing data available. Run tests first to populate cache.")
        return

    sorted_timings = sorted(timings.items(), key=lambda x: x[1], reverse=True)
    total = sum(v for v in timings.values())

    lines = [
        "",
        f"{'=' * 70}",
        f"  TEST TIMING REPORT — {len(timings)} files",
        f"{'=' * 70}",
        f"  Total accumulated time: {total:.1f}s ({total / 60:.1f} min)",
        f"{'─' * 70}",
        "  Slowest files:",
    ]

    for i, (name, dur) in enumerate(sorted_timings[:20], 1):
        pct = (dur / total * 100) if total > 0 else 0
        lines.append(f"    {i:2d}. {dur:7.2f}s ({pct:4.1f}%)  {Path(name).name}")

    fastest = sorted_timings[-10:] if len(sorted_timings) > 10 else []
    if fastest:
        lines.append(f"{'─' * 70}")
        lines.append("  Fastest files:")
        for name, dur in reversed(fastest):
            lines.append(f"        {dur:7.2f}s  {Path(name).name}")

    lines.append(f"{'=' * 70}")

    for line in lines:
        logger.info(line)


# ──── Smart Test Runner (Main Orchestrator) ───────────────────────────────────


class SmartTestRunner:
    """Orchestrates intelligent test selection, ordering, and execution.

    Attributes:
        timing_cache_path: Path to the test timing JSON cache.
        reports_dir: Path to save test reports.
        parallel_workers: Number of pytest-xdist workers.
        skip_patterns: File name patterns to always skip.
    """

    def __init__(
        self,
        timing_cache_path: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
        parallel_workers: int = 0,
        skip_patterns: Optional[List[str]] = None,
    ) -> None:
        self.timing_cache_path = timing_cache_path or DEFAULT_TIMING_CACHE
        self.reports_dir = reports_dir or DEFAULT_REPORTS_DIR
        self.parallel_workers = parallel_workers
        self.skip_patterns = skip_patterns or list(SKIP_PATTERNS)
        self._timings = load_timing_cache(self.timing_cache_path)

    def _filter_skipped(self, files: List[str]) -> List[str]:
        """Remove files matching skip patterns.

        Args:
            files: List of test file paths.

        Returns:
            Filtered list.
        """
        return [
            f for f in files
            if Path(f).name not in self.skip_patterns
        ]

    def run_changed(self, ref: str = "HEAD") -> TestResult:
        """Run tests only for files changed since the given ref.

        Args:
            ref: Git ref to diff against.

        Returns:
            TestResult from the run.
        """
        changed = get_changed_files(ref)
        if not changed:
            logger.info("No changed files detected")
            return TestResult(timestamp=_now_iso())

        logger.info("Changed files: %s", ", ".join(changed))
        test_files = resolve_test_files_from_changes(changed)
        test_files = self._filter_skipped(test_files)

        if not test_files:
            logger.info("No matching test files for changed sources")
            return TestResult(timestamp=_now_iso())

        logger.info("Resolved %d test file(s) from changes", len(test_files))
        test_files = order_by_speed(test_files, self._timings)
        return self._execute(test_files, tier=None)

    def run_tier(self, tier: int) -> TestResult:
        """Run all tests up to the specified tier.

        Args:
            tier: Tier level (1-4).

        Returns:
            TestResult from the run.
        """
        tier = max(1, min(4, tier))
        tier_def = TIER_DEFINITIONS[tier]
        logger.info("Running Tier %d: %s", tier, tier_def["label"])

        test_files = collect_tier_files(tier)
        test_files = self._filter_skipped(test_files)
        test_files = order_by_speed(test_files, self._timings)

        logger.info("Collected %d test file(s) for tier %d", len(test_files), tier)
        return self._execute(test_files, tier=tier, timeout=tier_def["timeout"])

    def run_full(self) -> TestResult:
        """Run the complete test suite (tier 4).

        Returns:
            TestResult from the run.
        """
        return self.run_tier(4)

    def run_files(self, patterns: List[str]) -> TestResult:
        """Run specific test files by glob pattern.

        Args:
            patterns: List of file paths or glob patterns.

        Returns:
            TestResult from the run.
        """
        test_files: List[str] = []
        for pattern in patterns:
            # Handle relative patterns
            if not os.path.isabs(pattern):
                pattern = str(ROOT / pattern)
            matches = glob_mod.glob(pattern)
            test_files.extend(m for m in matches if Path(m).is_file())

        test_files = self._filter_skipped(sorted(set(test_files)))
        test_files = order_by_speed(test_files, self._timings)

        if not test_files:
            logger.info("No test files matched the given patterns")
            return TestResult(timestamp=_now_iso())

        logger.info("Running %d specified test file(s)", len(test_files))
        return self._execute(test_files, tier=None)

    def run_auto(self) -> TestResult:
        """Auto mode: run git-diff tests, fall back to tier 2 if no changes.

        Returns:
            TestResult from the run.
        """
        changed = get_changed_files()
        if changed:
            logger.info("Auto mode: detected %d changed file(s), running affected tests", len(changed))
            test_files = resolve_test_files_from_changes(changed)
            test_files = self._filter_skipped(test_files)

            if test_files:
                test_files = order_by_speed(test_files, self._timings)
                return self._execute(test_files, tier=None)

        logger.info("Auto mode: no targeted changes, falling back to tier 2")
        return self.run_tier(2)

    def _execute(
        self,
        test_files: List[str],
        tier: Optional[int] = None,
        timeout: int = 600,
    ) -> TestResult:
        """Execute pytest and process results.

        Args:
            test_files: Ordered list of test file paths.
            tier: Optional tier label for the report.
            timeout: Maximum runtime in seconds.

        Returns:
            TestResult with parsed output and updated cache.
        """
        result = run_pytest(
            test_files,
            parallel_workers=self.parallel_workers,
            timeout=timeout,
        )
        result.tier = tier

        # Update timing cache from durations output
        new_timings = extract_file_timings(result.raw_output)
        if new_timings:
            save_timing_cache(self.timing_cache_path, self._timings, new_timings)
            self._timings.update(new_timings)

        # Print summary and save report
        print_summary(result)
        save_report(result, self.reports_dir)

        return result


# ──── Configuration Loading ───────────────────────────────────────────────────


def load_config_from_yaml() -> Dict[str, Any]:
    """Load smart runner config from CosySim's default.yaml.

    Returns:
        Dict with smart_runner configuration, or empty dict on failure.
    """
    config_path = ROOT / "config" / "default.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("testing", {}).get("smart_runner", {})
    except ImportError:
        logger.debug("PyYAML not available, using defaults")
        return {}
    except Exception as exc:
        logger.warning("Failed to load config: %s", exc)
        return {}


# ──── CLI ─────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the smart test runner.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="CosySim Smart Test Runner — tiered, git-aware, timing-cached",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                         Auto: git-diff + tier 2 fallback
  %(prog)s --tier 1                Quick smoke tests (<30s)
  %(prog)s --tier 3                Integration tests (<5min)
  %(prog)s --full                  Full suite (tier 4)
  %(prog)s --changed               Only git-changed file tests
  %(prog)s --file "tests/test_penthouse*.py"
  %(prog)s --report                Show timing report from cache
        """,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--tier", type=int, choices=[1, 2, 3, 4],
        help="Run tests for the specified tier (cumulative)",
    )
    mode.add_argument(
        "--full", action="store_true",
        help="Run the complete test suite (tier 4)",
    )
    mode.add_argument(
        "--changed", action="store_true",
        help="Only run tests for git-changed files",
    )
    mode.add_argument(
        "--file", nargs="+", dest="files",
        help="Run specific test file(s) or glob patterns",
    )
    mode.add_argument(
        "--report", action="store_true",
        help="Show timing report from cache (no tests run)",
    )

    parser.add_argument(
        "--workers", "-j", type=int, default=0,
        help="Number of parallel workers (requires pytest-xdist)",
    )
    parser.add_argument(
        "--timing-cache", type=str, default=None,
        help=f"Path to timing cache JSON (default: {DEFAULT_TIMING_CACHE})",
    )
    parser.add_argument(
        "--reports-dir", type=str, default=None,
        help=f"Path to save reports (default: {DEFAULT_REPORTS_DIR})",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug logging",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the smart test runner CLI.

    Args:
        argv: Command line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code (0 = success, non-zero = failure).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load YAML config for defaults
    yaml_cfg = load_config_from_yaml()

    timing_cache = Path(args.timing_cache) if args.timing_cache else (
        Path(yaml_cfg.get("timing_cache", str(DEFAULT_TIMING_CACHE)))
        if not os.path.isabs(str(yaml_cfg.get("timing_cache", "")))
        and yaml_cfg.get("timing_cache")
        else DEFAULT_TIMING_CACHE
    )
    reports_dir = Path(args.reports_dir) if args.reports_dir else (
        Path(yaml_cfg.get("reports_dir", str(DEFAULT_REPORTS_DIR)))
        if yaml_cfg.get("reports_dir")
        else DEFAULT_REPORTS_DIR
    )

    workers = args.workers or yaml_cfg.get("parallel_workers", 0)

    # Handle --report (no tests run)
    if args.report:
        generate_timing_report(timing_cache)
        return 0

    # Build runner
    skip_pats = yaml_cfg.get("skip_patterns", list(SKIP_PATTERNS))
    runner = SmartTestRunner(
        timing_cache_path=timing_cache,
        reports_dir=reports_dir,
        parallel_workers=workers,
        skip_patterns=skip_pats,
    )

    # Dispatch to appropriate mode
    if args.tier:
        result = runner.run_tier(args.tier)
    elif args.full:
        result = runner.run_full()
    elif args.changed:
        result = runner.run_changed()
    elif args.files:
        result = runner.run_files(args.files)
    else:
        result = runner.run_auto()

    return result.return_code


if __name__ == "__main__":
    sys.exit(main())
