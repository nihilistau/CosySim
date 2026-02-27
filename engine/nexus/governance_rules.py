"""Codified CosySim coding standards, testing requirements, and agent permissions as Nexus rules.

Provides GovernanceManager for seeding, querying, and validating against
governance rules stored in Nexus. Rules are descriptive (agents consult them)
with basic regex-based validation for coding standards.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ──── Rule Definitions ────


@dataclass
class GovernanceRule:
    """A single governance rule definition."""

    scope: str
    rule_type: str
    name: str
    condition: Dict[str, Any]
    action: Dict[str, Any]
    priority: int = 50
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


# ──── Rule Set ────


class GovernanceRuleSet:
    """Collection of all CosySim governance rule definitions."""

    @staticmethod
    def coding_standards() -> List[GovernanceRule]:
        """Coding standard rules (scope=global, type=validation)."""
        return [
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="absolute-imports",
                condition={"pattern": r"^\s*from\s+\."},
                action={"severity": "reject", "message": "Use absolute imports only, never relative imports."},
                priority=90,
                description="Reject files containing relative imports (from . or from ..).",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="type-hints-required",
                condition={"pattern": r"^\s*def\s+\w+\([^)]*\)\s*:"},
                action={"severity": "warn", "message": "Function definitions should have type hints on all parameters and return type."},
                priority=70,
                description="Warn when function definitions lack type hints.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="no-print",
                condition={"pattern": r"(?<!['\"\w])print\s*\("},
                action={"severity": "reject", "message": "Use logger instead of print(). Set up: logger = logging.getLogger(__name__)"},
                priority=90,
                description="Reject files using print() calls — use logging instead.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="logger-required",
                condition={"pattern": r"logging\.getLogger\(__name__\)", "absent": True},
                action={"severity": "warn", "message": "Python modules should define: logger = logging.getLogger(__name__)"},
                priority=60,
                description="Warn when a Python module lacks a module-level logger.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="google-docstrings",
                condition={"pattern": r"^\s*def\s+[a-z]\w*\s*\(", "requires_docstring": True},
                action={"severity": "warn", "message": "Public functions should have Google-style docstrings."},
                priority=50,
                description="Warn when public functions lack docstrings.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="future-annotations",
                condition={"pattern": r"from\s+__future__\s+import\s+annotations", "absent": True},
                action={"severity": "warn", "message": "Add 'from __future__ import annotations' for forward references."},
                priority=40,
                description="Warn when module is missing future annotations import.",
            ),
        ]

    @staticmethod
    def testing_standards() -> List[GovernanceRule]:
        """Testing standard rules (scope=global, type=quality_gate)."""
        return [
            GovernanceRule(
                scope="global",
                rule_type="quality_gate",
                name="tests-required",
                condition={"check": "test_file_exists"},
                action={"severity": "block", "message": "New modules must have a corresponding test file."},
                priority=80,
                description="Block new modules that lack a corresponding test file.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="quality_gate",
                name="mock-external",
                condition={"pattern": r"^\s*import\s+requests|^\s*from\s+(?:requests|urllib)\s+import", "without": r"mock|Mock|patch"},
                action={"severity": "warn", "message": "Tests importing requests/urllib should use mocks."},
                priority=70,
                description="Warn when test files import HTTP libraries without mocking.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="quality_gate",
                name="no-unittest",
                condition={"pattern": r"class\s+\w+\(.*unittest\.TestCase.*\)"},
                action={"severity": "warn", "message": "Use pytest with plain assert, not unittest.TestCase."},
                priority=60,
                description="Warn when tests use unittest.TestCase instead of pytest.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="quality_gate",
                name="min-test-count",
                condition={"check": "min_test_functions", "min_count": 3},
                action={"severity": "warn", "message": "Test files should have at least 3 test functions."},
                priority=40,
                description="Warn when a test file has fewer than 3 test functions.",
            ),
        ]

    @staticmethod
    def nexus_workflow() -> List[GovernanceRule]:
        """Nexus workflow rules (scope=global, type=auto_action)."""
        return [
            GovernanceRule(
                scope="global",
                rule_type="auto_action",
                name="nexus-first",
                condition={"trigger": "editing_code", "requires": "nexus_search"},
                action={"severity": "remind", "message": "Search Nexus before editing code: nexus_search('topic')"},
                priority=80,
                description="Remind agents to search Nexus before making code changes.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="auto_action",
                name="store-decisions",
                condition={"trigger": "architecture_decision"},
                action={"severity": "remind", "message": "Store architecture decisions in Nexus: nexus_add('Decision: ...', content, 'decision')"},
                priority=70,
                description="Remind agents to store architecture decisions in Nexus.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="auto_action",
                name="post-session-log",
                condition={"trigger": "session_ending"},
                action={"severity": "remind", "message": "Log session to Nexus: nexus_log_session('CosySim')"},
                priority=60,
                description="Remind agents to log sessions to Nexus on completion.",
            ),
        ]

    @staticmethod
    def agent_permissions() -> List[GovernanceRule]:
        """Agent permission rules (scope=agent:*, type=access)."""
        return [
            GovernanceRule(
                scope="agent:*",
                rule_type="access",
                name="router-read-only",
                condition={"agent_size_lt": 1_000_000_000},
                action={"allow": ["read"], "deny": ["write", "delete"], "message": "Sub-1B models have read-only access."},
                priority=90,
                description="Restrict sub-1B parameter models to read-only operations.",
            ),
            GovernanceRule(
                scope="agent:*",
                rule_type="access",
                name="worker-limited-scope",
                condition={"agent_size_lt": 10_000_000_000, "agent_size_gte": 1_000_000_000},
                action={"allow": ["read", "write"], "deny": ["delete", "admin"], "scope_limit": "assigned_files", "message": "Sub-10B models limited to assigned file scope."},
                priority=70,
                description="Restrict sub-10B parameter models to their assigned files.",
            ),
            GovernanceRule(
                scope="agent:*",
                rule_type="access",
                name="expert-full-access",
                condition={"agent_size_gte": 10_000_000_000, "or": "agent_type == 'copilot'"},
                action={"allow": ["read", "write", "delete", "admin"], "message": "10B+ models and Copilot have full access."},
                priority=50,
                description="Grant full access to 10B+ parameter models and Copilot.",
            ),
        ]

    @staticmethod
    def commit_standards() -> List[GovernanceRule]:
        """Commit standard rules (scope=global, type=validation)."""
        return [
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="conventional-commits",
                condition={"pattern": r"^(feat|fix|docs|test|chore|refactor|style|perf|ci|build|revert)(\(.+\))?:\s.+"},
                action={"severity": "reject", "message": "Commit messages must use conventional format: feat:/fix:/docs:/test:/chore:/refactor:"},
                priority=80,
                description="Validate commit messages follow conventional commit format.",
            ),
            GovernanceRule(
                scope="global",
                rule_type="validation",
                name="co-authored-by",
                condition={"pattern": r"Co-authored-by:\s+Copilot\s+<", "absent": True},
                action={"severity": "warn", "message": "Include Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com> trailer."},
                priority=60,
                description="Warn when commit is missing Co-authored-by Copilot trailer.",
            ),
        ]

    @classmethod
    def all_rules(cls) -> List[GovernanceRule]:
        """Return all governance rules across all categories."""
        return (
            cls.coding_standards()
            + cls.testing_standards()
            + cls.nexus_workflow()
            + cls.agent_permissions()
            + cls.commit_standards()
        )


# ──── Governance Manager ────


class GovernanceManager:
    """Manages CosySim governance rules in Nexus.

    Handles seeding, querying, validation, and permission checks
    against the codified rule set.
    """

    def __init__(self) -> None:
        self._rule_set = GovernanceRuleSet()
        self._client = get_nexus_client()

    def seed_rules(self) -> Dict[str, Any]:
        """Seed all governance rules into Nexus (idempotent).

        Returns:
            Dict with counts of created, skipped, and failed rules.
        """
        existing = self._client.get_rules()
        existing_names = {r.get("name", "") for r in existing}

        created = 0
        skipped = 0
        failed = 0

        for rule in self._rule_set.all_rules():
            if rule.name in existing_names:
                logger.debug("Rule '%s' already exists, skipping", rule.name)
                skipped += 1
                continue

            rule_id = self._client.add_rule(
                scope=rule.scope,
                rule_type=rule.rule_type,
                name=rule.name,
                condition=rule.condition,
                action=rule.action,
                priority=rule.priority,
            )
            if rule_id:
                logger.info("Created rule '%s' (id=%s)", rule.name, rule_id)
                created += 1
            else:
                logger.warning("Failed to create rule '%s'", rule.name)
                failed += 1

        result = {"created": created, "skipped": skipped, "failed": failed, "total": created + skipped + failed}
        logger.info("Seed complete: %s", result)
        return result

    def get_rules(self, scope: str = "global", rule_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch rules from Nexus filtered by scope and optionally type.

        Args:
            scope: Rule scope to filter by (e.g. "global", "agent:*").
            rule_type: Optional rule type filter.

        Returns:
            List of rule dicts from Nexus.
        """
        return self._client.get_rules(scope=scope, rule_type=rule_type or "")

    def validate_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Check a Python file against coding standard rules.

        Performs basic regex-based validation. Not AST-level.

        Args:
            filepath: Path to the Python file to validate.

        Returns:
            List of violation dicts with rule name, severity, message, and line info.
        """
        path = Path(filepath)
        if not path.exists():
            return [{"rule": "file-check", "severity": "error", "message": f"File not found: {filepath}"}]

        if path.suffix != ".py":
            return []

        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        violations: List[Dict[str, Any]] = []

        # Check: relative imports
        for i, line in enumerate(lines, 1):
            if re.match(r"^\s*from\s+\.", line):
                violations.append({
                    "rule": "absolute-imports",
                    "severity": "reject",
                    "message": "Use absolute imports only, never relative imports.",
                    "line": i,
                    "text": line.strip(),
                })

        # Check: print() usage (skip comments and strings on the same line)
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(r"(?<!['\"\w])print\s*\(", line):
                violations.append({
                    "rule": "no-print",
                    "severity": "reject",
                    "message": "Use logger instead of print().",
                    "line": i,
                    "text": line.strip(),
                })

        # Check: logger present
        if not re.search(r"logging\.getLogger\(__name__\)", content):
            violations.append({
                "rule": "logger-required",
                "severity": "warn",
                "message": "Module should define: logger = logging.getLogger(__name__)",
            })

        # Check: future annotations
        if not re.search(r"from\s+__future__\s+import\s+annotations", content):
            violations.append({
                "rule": "future-annotations",
                "severity": "warn",
                "message": "Add 'from __future__ import annotations' for forward references.",
            })

        # Check: public functions without docstrings
        for i, line in enumerate(lines, 1):
            match = re.match(r"^(\s*)def\s+([a-z]\w*)\s*\(", line)
            if match and not match.group(2).startswith("_"):
                indent = len(match.group(1))
                # Look for docstring on next non-empty line
                has_docstring = False
                for j in range(i, min(i + 3, len(lines))):
                    next_line = lines[j].strip()
                    if next_line == "":
                        continue
                    if next_line.startswith('"""') or next_line.startswith("'''"):
                        has_docstring = True
                    break
                if not has_docstring:
                    violations.append({
                        "rule": "google-docstrings",
                        "severity": "warn",
                        "message": f"Public function '{match.group(2)}' should have a docstring.",
                        "line": i,
                    })

        # Check: function defs without type hints (basic heuristic)
        for i, line in enumerate(lines, 1):
            match = re.match(r"^\s*def\s+\w+\(([^)]*)\)\s*:", line)
            if match:
                params = match.group(1).strip()
                # Skip empty params and self/cls-only
                if params and params not in ("self", "cls"):
                    if ":" not in params and params != "*":
                        violations.append({
                            "rule": "type-hints-required",
                            "severity": "warn",
                            "message": "Function parameters should have type hints.",
                            "line": i,
                            "text": line.strip(),
                        })

        return violations

    def validate_commit(self, message: str) -> List[Dict[str, Any]]:
        """Validate a commit message against commit standards.

        Args:
            message: The commit message to validate.

        Returns:
            List of violation dicts.
        """
        violations: List[Dict[str, Any]] = []
        first_line = message.strip().split("\n")[0] if message.strip() else ""

        # Check conventional commit format
        if not re.match(r"^(feat|fix|docs|test|chore|refactor|style|perf|ci|build|revert)(\(.+\))?:\s.+", first_line):
            violations.append({
                "rule": "conventional-commits",
                "severity": "reject",
                "message": "Commit must use conventional format: feat:/fix:/docs:/test:/chore:/refactor:",
            })

        # Check co-authored-by trailer
        if "Co-authored-by: Copilot <" not in message:
            violations.append({
                "rule": "co-authored-by",
                "severity": "warn",
                "message": "Include Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com> trailer.",
            })

        return violations

    def check_permissions(self, agent_id: str, operation: str) -> bool:
        """Check if an agent is allowed to perform an operation.

        Args:
            agent_id: Agent identifier (e.g. "copilot", "qwen3-0.6b").
            operation: Operation to check (e.g. "read", "write", "delete", "admin").

        Returns:
            True if the operation is allowed.
        """
        agent_info = _parse_agent_info(agent_id)
        rules = self._rule_set.agent_permissions()

        # Sort by priority descending — higher priority rules checked first
        for rule in sorted(rules, key=lambda r: r.priority, reverse=True):
            cond = rule.condition
            action = rule.action

            if agent_info.get("is_copilot") and "or" in cond:
                if "copilot" in cond["or"]:
                    return operation in action.get("allow", [])

            size = agent_info.get("size", 0)
            if "agent_size_lt" in cond and "agent_size_gte" in cond:
                if cond["agent_size_gte"] <= size < cond["agent_size_lt"]:
                    return operation in action.get("allow", [])
            elif "agent_size_lt" in cond:
                if size < cond["agent_size_lt"]:
                    return operation in action.get("allow", [])
            elif "agent_size_gte" in cond:
                if size >= cond["agent_size_gte"]:
                    return operation in action.get("allow", [])

        # Default deny
        return False

    def all_rules(self) -> List[Dict[str, Any]]:
        """Return all defined governance rules as dicts.

        Returns:
            List of all rule definitions.
        """
        return [r.to_dict() for r in self._rule_set.all_rules()]

    def stats(self) -> Dict[str, Any]:
        """Get rule counts grouped by scope and type.

        Returns:
            Dict with total count and breakdowns by scope and type.
        """
        rules = self._rule_set.all_rules()
        by_scope: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for rule in rules:
            by_scope[rule.scope] = by_scope.get(rule.scope, 0) + 1
            by_type[rule.rule_type] = by_type.get(rule.rule_type, 0) + 1

        return {
            "total": len(rules),
            "by_scope": by_scope,
            "by_type": by_type,
        }


# ──── Singleton ────

_manager: Optional[GovernanceManager] = None


def get_governance_manager() -> GovernanceManager:
    """Get or create the singleton GovernanceManager."""
    global _manager
    if _manager is None:
        _manager = GovernanceManager()
    return _manager


# ──── Helpers ────


def _parse_agent_info(agent_id: str) -> Dict[str, Any]:
    """Parse agent ID into structured info for permission checks.

    Args:
        agent_id: Agent identifier string.

    Returns:
        Dict with size estimate and agent type flags.
    """
    agent_id_lower = agent_id.lower()

    if agent_id_lower == "copilot":
        return {"is_copilot": True, "size": 100_000_000_000}

    # Estimate size from common model naming patterns
    size_map = {
        "0.6b": 600_000_000,
        "1b": 1_000_000_000,
        "1.5b": 1_500_000_000,
        "3b": 3_000_000_000,
        "7b": 7_000_000_000,
        "8b": 8_000_000_000,
        "9b": 9_000_000_000,
        "13b": 13_000_000_000,
        "14b": 14_000_000_000,
        "32b": 32_000_000_000,
        "70b": 70_000_000_000,
        "72b": 72_000_000_000,
    }

    for suffix, size in size_map.items():
        if suffix in agent_id_lower:
            return {"is_copilot": False, "size": size}

    # Unknown agent — default to small
    return {"is_copilot": False, "size": 0}


# ──── CLI ────


def _cli() -> None:
    """Command-line interface for governance rules."""
    parser = argparse.ArgumentParser(
        prog="python -m engine.nexus.governance_rules",
        description="CosySim governance rules manager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="Seed all rules into Nexus")
    sub.add_parser("list", help="List all defined rules")

    validate_p = sub.add_parser("validate", help="Validate a Python file")
    validate_p.add_argument("file", help="Path to file to validate")

    sub.add_parser("stats", help="Show rule statistics")

    args = parser.parse_args()
    mgr = get_governance_manager()

    if args.command == "seed":
        result = mgr.seed_rules()
        logger.info("Seed result: %s", result)

    elif args.command == "list":
        rules = mgr.all_rules()
        for rule in rules:
            logger.info(
                "[%s/%s] %s (p=%d) — %s",
                rule["scope"], rule["rule_type"], rule["name"],
                rule["priority"], rule["description"],
            )
        logger.info("Total: %d rules", len(rules))

    elif args.command == "validate":
        violations = mgr.validate_file(args.file)
        if violations:
            for v in violations:
                line_info = f" (line {v['line']})" if "line" in v else ""
                logger.warning("[%s]%s %s", v["rule"], line_info, v["message"])
            logger.info("%d violation(s) found", len(violations))
        else:
            logger.info("No violations found")

    elif args.command == "stats":
        s = mgr.stats()
        logger.info("Total rules: %d", s["total"])
        logger.info("By scope: %s", s["by_scope"])
        logger.info("By type: %s", s["by_type"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _cli()
