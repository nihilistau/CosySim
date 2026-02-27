"""Tests for engine.nexus.governance_rules module."""
from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from engine.nexus.governance_rules import (
    GovernanceManager,
    GovernanceRuleSet,
    _parse_agent_info,
)


# ──── Fixtures ────


@pytest.fixture()
def mock_client():
    """Mock NexusClient that returns empty rules by default."""
    with patch("engine.nexus.governance_rules.get_nexus_client") as mock_get:
        client = MagicMock()
        client.get_rules.return_value = []
        client.add_rule.return_value = "rule-id-123"
        mock_get.return_value = client
        yield client


@pytest.fixture()
def manager(mock_client):
    """GovernanceManager with mocked Nexus client."""
    return GovernanceManager()


# ──── Rule Set Tests ────


def test_all_rules_returns_expected_count():
    """All rule categories are included in the full set."""
    rules = GovernanceRuleSet.all_rules()
    assert len(rules) == 18
    names = [r.name for r in rules]
    assert "absolute-imports" in names
    assert "tests-required" in names
    assert "nexus-first" in names
    assert "router-read-only" in names
    assert "conventional-commits" in names


def test_coding_standards_have_correct_scope():
    """Coding standards are scoped globally with validation type."""
    for rule in GovernanceRuleSet.coding_standards():
        assert rule.scope == "global"
        assert rule.rule_type == "validation"


def test_agent_permissions_have_access_type():
    """Agent permissions use access rule type."""
    for rule in GovernanceRuleSet.agent_permissions():
        assert rule.scope == "agent:*"
        assert rule.rule_type == "access"


# ──── Seed Tests ────


def test_seed_rules_creates_all(manager, mock_client):
    """Seeding into empty Nexus creates all rules."""
    result = manager.seed_rules()
    assert result["created"] == 18
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert mock_client.add_rule.call_count == 18


def test_seed_rules_idempotent(manager, mock_client):
    """Calling seed twice skips already-existing rules."""
    # First seed — all created
    manager.seed_rules()

    # Simulate Nexus now having all rules
    mock_client.get_rules.return_value = [
        {"name": r.name} for r in GovernanceRuleSet.all_rules()
    ]
    mock_client.add_rule.reset_mock()

    result = manager.seed_rules()
    assert result["created"] == 0
    assert result["skipped"] == 18
    assert mock_client.add_rule.call_count == 0


def test_seed_handles_partial_existing(manager, mock_client):
    """Seeding skips only rules that already exist."""
    mock_client.get_rules.return_value = [
        {"name": "absolute-imports"},
        {"name": "no-print"},
    ]
    result = manager.seed_rules()
    assert result["skipped"] == 2
    assert result["created"] == 16


def test_seed_handles_failures(manager, mock_client):
    """Failed rule creation is tracked."""
    mock_client.add_rule.return_value = None  # Simulate failure
    result = manager.seed_rules()
    assert result["failed"] == 18
    assert result["created"] == 0


# ──── Validate File Tests ────


def test_validate_catches_relative_imports(tmp_path, manager):
    """Relative imports are flagged as violations."""
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""\
        from __future__ import annotations
        import logging
        from .utils import helper
        logger = logging.getLogger(__name__)
    """))
    violations = manager.validate_file(str(f))
    rules = [v["rule"] for v in violations]
    assert "absolute-imports" in rules


def test_validate_catches_print(tmp_path, manager):
    """print() calls are flagged as violations."""
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""\
        from __future__ import annotations
        import logging
        logger = logging.getLogger(__name__)
        def do_thing() -> None:
            \"\"\"Do a thing.\"\"\"
            print("hello")
    """))
    violations = manager.validate_file(str(f))
    rules = [v["rule"] for v in violations]
    assert "no-print" in rules


def test_validate_passes_clean_file(tmp_path, manager):
    """A well-formed file produces no violations."""
    f = tmp_path / "clean.py"
    f.write_text(textwrap.dedent("""\
        \"\"\"Clean module.\"\"\"
        from __future__ import annotations

        import logging

        from engine.config import get_config

        logger = logging.getLogger(__name__)


        def do_thing(name: str) -> str:
            \"\"\"Do a thing.\"\"\"
            return name
    """))
    violations = manager.validate_file(str(f))
    assert len(violations) == 0


def test_validate_missing_logger(tmp_path, manager):
    """Missing module-level logger is warned."""
    f = tmp_path / "no_logger.py"
    f.write_text(textwrap.dedent("""\
        from __future__ import annotations
        def helper(x: int) -> int:
            \"\"\"Help.\"\"\"
            return x + 1
    """))
    violations = manager.validate_file(str(f))
    rules = [v["rule"] for v in violations]
    assert "logger-required" in rules


def test_validate_missing_future_annotations(tmp_path, manager):
    """Missing future annotations import is warned."""
    f = tmp_path / "no_future.py"
    f.write_text(textwrap.dedent("""\
        import logging
        logger = logging.getLogger(__name__)
        def helper(x: int) -> int:
            \"\"\"Help.\"\"\"
            return x + 1
    """))
    violations = manager.validate_file(str(f))
    rules = [v["rule"] for v in violations]
    assert "future-annotations" in rules


def test_validate_nonexistent_file(manager):
    """Non-existent file returns file-check error."""
    violations = manager.validate_file("/no/such/file.py")
    assert len(violations) == 1
    assert violations[0]["rule"] == "file-check"


def test_validate_non_python_file(tmp_path, manager):
    """Non-Python files return no violations."""
    f = tmp_path / "readme.md"
    f.write_text("# Hello")
    violations = manager.validate_file(str(f))
    assert len(violations) == 0


def test_validate_skips_comment_print(tmp_path, manager):
    """print() in comments is not flagged."""
    f = tmp_path / "commented.py"
    f.write_text(textwrap.dedent("""\
        from __future__ import annotations
        import logging
        logger = logging.getLogger(__name__)
        # print("this is a comment")
        def helper(x: int) -> int:
            \"\"\"Help.\"\"\"
            return x
    """))
    violations = manager.validate_file(str(f))
    rules = [v["rule"] for v in violations]
    assert "no-print" not in rules


# ──── Validate Commit Tests ────


def test_validate_commit_conventional_format(manager):
    """Valid conventional commit passes."""
    msg = "feat: add governance rules\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    violations = manager.validate_commit(msg)
    assert len(violations) == 0


def test_validate_commit_all_prefixes(manager):
    """All standard prefixes are accepted."""
    for prefix in ["feat", "fix", "docs", "test", "chore", "refactor", "style", "perf", "ci", "build", "revert"]:
        msg = f"{prefix}: something\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
        violations = manager.validate_commit(msg)
        assert not any(v["rule"] == "conventional-commits" for v in violations), f"Prefix '{prefix}' should be valid"


def test_validate_commit_scoped(manager):
    """Scoped conventional commits are accepted."""
    msg = "feat(auth): add login\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    violations = manager.validate_commit(msg)
    assert len(violations) == 0


def test_validate_commit_rejects_bad_format(manager):
    """Non-conventional commit messages are rejected."""
    violations = manager.validate_commit("Updated some stuff")
    rules = [v["rule"] for v in violations]
    assert "conventional-commits" in rules


def test_validate_commit_missing_coauthor(manager):
    """Missing co-author trailer is warned."""
    violations = manager.validate_commit("feat: add thing")
    rules = [v["rule"] for v in violations]
    assert "co-authored-by" in rules


# ──── Permission Tests ────


def test_permissions_copilot_full_access(manager):
    """Copilot agent has full access."""
    assert manager.check_permissions("copilot", "read") is True
    assert manager.check_permissions("copilot", "write") is True
    assert manager.check_permissions("copilot", "delete") is True
    assert manager.check_permissions("copilot", "admin") is True


def test_permissions_small_model_read_only(manager):
    """Sub-1B models have read-only access."""
    assert manager.check_permissions("qwen3-0.6b", "read") is True
    assert manager.check_permissions("qwen3-0.6b", "write") is False
    assert manager.check_permissions("qwen3-0.6b", "delete") is False


def test_permissions_worker_model_limited(manager):
    """Sub-10B models can read and write but not delete/admin."""
    assert manager.check_permissions("llama-7b", "read") is True
    assert manager.check_permissions("llama-7b", "write") is True
    assert manager.check_permissions("llama-7b", "delete") is False
    assert manager.check_permissions("llama-7b", "admin") is False


def test_permissions_expert_model_full(manager):
    """10B+ models have full access."""
    assert manager.check_permissions("qwen-14b", "read") is True
    assert manager.check_permissions("qwen-14b", "write") is True
    assert manager.check_permissions("qwen-14b", "delete") is True
    assert manager.check_permissions("qwen-14b", "admin") is True


def test_permissions_unknown_agent_denied(manager):
    """Unknown agents default to smallest tier."""
    assert manager.check_permissions("unknown-model", "write") is False


# ──── Stats Tests ────


def test_stats_returns_correct_counts(manager):
    """Stats reflect all defined rule categories."""
    s = manager.stats()
    assert s["total"] == 18
    assert s["by_scope"]["global"] == 15
    assert s["by_scope"]["agent:*"] == 3
    assert s["by_type"]["validation"] == 8
    assert s["by_type"]["quality_gate"] == 4
    assert s["by_type"]["auto_action"] == 3
    assert s["by_type"]["access"] == 3


# ──── Helper Tests ────


def test_parse_agent_info_copilot():
    """Copilot is identified correctly."""
    info = _parse_agent_info("copilot")
    assert info["is_copilot"] is True


def test_parse_agent_info_model_sizes():
    """Model size is parsed from common naming patterns."""
    assert _parse_agent_info("qwen3-0.6b")["size"] == 600_000_000
    assert _parse_agent_info("llama-7b")["size"] == 7_000_000_000
    assert _parse_agent_info("qwen-72b")["size"] == 72_000_000_000


def test_parse_agent_info_unknown():
    """Unknown agents default to size 0."""
    info = _parse_agent_info("mystery-model")
    assert info["size"] == 0
    assert info["is_copilot"] is False


# ──── All Rules Dict Tests ────


def test_all_rules_returns_dicts(manager):
    """all_rules() returns serializable dicts."""
    rules = manager.all_rules()
    assert isinstance(rules, list)
    assert all(isinstance(r, dict) for r in rules)
    assert all("name" in r and "scope" in r for r in rules)
