"""Tests for Copilot validation auto-repair integration."""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from engine.nexus.copilot_validation import auto_repair


def _make_validation_report(
    *,
    ok: bool = True,
    issue_count: int = 0,
    nexus_sync_issues: List[Dict[str, Any]] | None = None,
    hook_issues: List[Dict[str, Any]] | None = None,
    runtime_issues: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build a synthetic validation report for testing."""
    return {
        "ok": ok,
        "issue_count": issue_count,
        "sections": {
            "nexus_sync": {
                "ok": not bool(nexus_sync_issues),
                "issues": nexus_sync_issues or [],
            },
            "hook_integrity": {
                "ok": not bool(hook_issues),
                "issues": hook_issues or [],
            },
            "runtime_health": {
                "ok": not bool(runtime_issues),
                "issues": runtime_issues or [],
            },
        },
    }


# ── No Issues → No Repair ────────────────────────────────────────────────────


def test_no_issues_returns_clean():
    """When validation passes, auto_repair returns immediately with no actions."""
    clean_report = _make_validation_report(ok=True, issue_count=0)
    with patch(
        "engine.nexus.copilot_validation.run_copilot_validation",
        return_value=clean_report,
    ):
        result = auto_repair()

    assert result["repaired"] is False
    assert result["actions"] == []
    assert "No issues" in result["message"]


# ── Dry-Run ───────────────────────────────────────────────────────────────────


def test_dry_run_does_not_sync():
    """dry_run=True diagnoses but never calls any sync method."""
    drift_report = _make_validation_report(
        ok=False,
        issue_count=2,
        nexus_sync_issues=[
            {"code": "content_drift", "source": "instructions/python.md"},
            {"code": "missing_entry", "source": "instructions/testing.md"},
        ],
    )
    with patch(
        "engine.nexus.copilot_validation.run_copilot_validation",
        return_value=drift_report,
    ):
        with patch("engine.nexus.copilot_validation.get_copilot_config") as mock_cfg:
            result = auto_repair(dry_run=True)
            mock_cfg.assert_not_called()

    assert result["repaired"] is False
    assert "Dry-run" in result["message"]


# ── Issue Classification & Routing ────────────────────────────────────────────


def test_instruction_drift_triggers_instruction_sync():
    """content_drift on an instruction source → sync_instructions_to_nexus."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        nexus_sync_issues=[
            {"code": "content_drift", "source": "instructions/python.md"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_instructions_to_nexus" in result["actions"]
    mock_cfg.sync_instructions_to_nexus.assert_called_once()


def test_agent_drift_triggers_agent_sync():
    """content_drift on an agent source → sync_agents_to_nexus."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        nexus_sync_issues=[
            {"code": "content_drift", "source": "agents/scene-builder.agent.md"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_agents_to_nexus" in result["actions"]
    mock_cfg.sync_agents_to_nexus.assert_called_once()


def test_hook_integrity_issues_trigger_hook_sync():
    """Hook integrity failures → sync_hooks_to_nexus."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        hook_issues=[
            {"code": "hook_missing", "source": "cosysim-hooks.json"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_hooks_to_nexus" in result["actions"]
    mock_cfg.sync_hooks_to_nexus.assert_called_once()


def test_seed_state_missing_triggers_full_sync():
    """seed_state_missing issues → sync_all_to_nexus (full sync)."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        nexus_sync_issues=[
            {"code": "seed_state_missing", "source": "seed_state"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_all_to_nexus" in result["actions"]
    mock_cfg.sync_all_to_nexus.assert_called_once()


def test_runtime_health_empty_config_triggers_full_sync():
    """empty_config_surface runtime issue → full sync."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        runtime_issues=[
            {"code": "empty_config_surface", "source": "runtime"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_all_to_nexus" in result["actions"]
    mock_cfg.sync_all_to_nexus.assert_called_once()


def test_duplicate_exact_title_triggers_full_sync():
    """duplicate_exact_title → full sync."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        nexus_sync_issues=[
            {"code": "duplicate_exact_title", "source": "instructions/python.md"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_all_to_nexus" in result["actions"]


# ── Combined Issues ───────────────────────────────────────────────────────────


def test_combined_instruction_and_hook_issues():
    """Multiple issue types → multiple sync calls (not full sync)."""
    before = _make_validation_report(
        ok=False,
        issue_count=3,
        nexus_sync_issues=[
            {"code": "content_drift", "source": "instructions/python.md"},
            {"code": "content_drift", "source": "agents/test-writer.agent.md"},
        ],
        hook_issues=[
            {"code": "hook_stale", "source": "session-logger/hooks.json"},
        ],
    )
    after = _make_validation_report(ok=True, issue_count=0)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert "sync_instructions_to_nexus" in result["actions"]
    assert "sync_agents_to_nexus" in result["actions"]
    assert "sync_hooks_to_nexus" in result["actions"]
    assert "sync_all_to_nexus" not in result["actions"]
    assert result["repaired"] is True


# ── Result Shape ──────────────────────────────────────────────────────────────


def test_repair_result_shape():
    """auto_repair result has all expected keys."""
    clean = _make_validation_report(ok=True, issue_count=0)
    with patch(
        "engine.nexus.copilot_validation.run_copilot_validation",
        return_value=clean,
    ):
        result = auto_repair()

    assert "before" in result
    assert "after" in result
    assert "repaired" in result
    assert "actions" in result
    assert "message" in result


def test_repair_counts_reported():
    """before_issues / after_issues are present when repair occurs."""
    before = _make_validation_report(
        ok=False,
        issue_count=3,
        nexus_sync_issues=[
            {"code": "content_drift", "source": "instructions/python.md"},
        ],
    )
    after = _make_validation_report(ok=False, issue_count=1)

    mock_cfg = MagicMock()
    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            side_effect=[before, after],
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
        patch(
            "engine.nexus.copilot_validation.seed_copilot_rules",
            create=True,
        ),
    ):
        result = auto_repair()

    assert result["before_issues"] == 3
    assert result["after_issues"] == 1
    assert result["repaired"] is True


# ── Error Handling ────────────────────────────────────────────────────────────


def test_sync_failure_returns_error():
    """If sync_all raises, auto_repair returns error dict without crashing."""
    before = _make_validation_report(
        ok=False,
        issue_count=1,
        nexus_sync_issues=[
            {"code": "seed_state_missing", "source": "seed"},
        ],
    )
    mock_cfg = MagicMock()
    mock_cfg.sync_all_to_nexus.side_effect = RuntimeError("Nexus down")

    with (
        patch(
            "engine.nexus.copilot_validation.run_copilot_validation",
            return_value=before,
        ),
        patch(
            "engine.nexus.copilot_validation.get_copilot_config",
            return_value=mock_cfg,
        ),
    ):
        result = auto_repair()

    assert result["repaired"] is False
    assert "error" in result
    assert "Nexus down" in result["error"]
