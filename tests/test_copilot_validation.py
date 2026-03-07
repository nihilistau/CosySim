"""Tests for engine.nexus.copilot_validation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from engine.nexus import copilot_validation as mod


class _FakeSyncConfig:
    def __init__(self, entries: dict[str, dict]) -> None:
        self.entries = entries

    def _find_existing_entry(self, client, query: str, title: str, category: str):  # noqa: ANN001
        return self.entries.get(title)

    def _entry_field(self, entry, field: str, default=""):  # noqa: ANN001
        return entry.get(field, default)


class _FakeClient:
    def __init__(self, entries_by_category: dict[str, list[dict]] | None = None) -> None:
        self.entries_by_category = entries_by_category or {}

    def list_entries(self, content_type: str = "", category: str = "", limit: int = 20) -> list[dict]:
        return list(self.entries_by_category.get(category, []))[:limit]


class _FakeConfig:
    def __init__(self, *, instructions: int = 2, agents: int = 3, hooks: int = 4) -> None:
        self._status = {
            "instructions": instructions,
            "agents": agents,
            "hooks": hooks,
            "cached_preferences": 0,
            "project_root": "C:\\Temp\\CosySim",
        }

    def status(self) -> dict:
        return dict(self._status)


class _FakeBridge:
    def __init__(self, onboarding: dict, session_context: dict) -> None:
        self._onboarding = onboarding
        self._session_context = session_context
        self.metrics = SimpleNamespace(to_dict=lambda: {"domains_touched": 0, "files_edited": 0})

    def get_onboarding_context(self) -> dict:
        return self._onboarding

    def session_start(self, task_description: str = "") -> dict:
        return dict(self._session_context)


def _write_hook_runtime(root: Path) -> None:
    hooks_dir = root / ".github" / "hooks"
    scripts_dir = hooks_dir / "scripts"
    session_logger_dir = hooks_dir / "session-logger"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    session_logger_dir.mkdir(parents=True, exist_ok=True)

    main_hooks = {
        "hooks": {
            "sessionStart": [
                {"powershell": "python engine/nexus/nexus_session_logger.py start"},
                {"powershell": "python -c \"get_copilot_bridge().session_start('x')\""},
            ],
            "userPromptSubmitted": [
                {"powershell": "python engine/nexus/nexus_session_logger.py prompt"},
            ],
            "sessionEnd": [
                {"powershell": "python -c \"get_copilot_bridge().session_end('x')\""},
                {"powershell": "python engine/nexus/nexus_session_logger.py end"},
            ],
            "preCompaction": [
                {"powershell": "python engine/nexus/nexus_session_logger.py compact"},
            ],
            "postToolUse": [
                {"powershell": "pwsh -File .github/hooks/scripts/log-tool-usage.ps1"},
                {"powershell": "python -c \"get_copilot_bridge().track_tool_use('x', {})\""},
            ],
            "preToolUse": [
                {"powershell": "pwsh -File .github/hooks/scripts/check-tool-safety.ps1"},
            ],
            "errorOccurred": [
                {"powershell": "pwsh -File .github/hooks/scripts/log-errors.ps1"},
                {"powershell": "python -c \"get_copilot_bridge().track_error('x', 'y')\""},
            ],
        }
    }
    session_hooks = {
        "hooks": {
            "sessionStart": [{"args": ["engine/nexus/nexus_session_logger.py", "start"]}],
            "userPromptSubmitted": [{"args": ["engine/nexus/nexus_session_logger.py", "prompt"]}],
            "sessionEnd": [{"args": ["engine/nexus/nexus_session_logger.py", "end"]}],
            "preCompaction": [{"args": ["engine/nexus/nexus_session_logger.py", "compact"]}],
        }
    }

    (hooks_dir / "cosysim-hooks.json").write_text(json.dumps(main_hooks), encoding="utf-8")
    (session_logger_dir / "hooks.json").write_text(json.dumps(session_hooks), encoding="utf-8")

    for script_name in (
        "log-session.ps1",
        "log-tool-usage.ps1",
        "check-tool-safety.ps1",
        "log-errors.ps1",
    ):
        (scripts_dir / script_name).write_text("# hook", encoding="utf-8")

    nexus_dir = root / "engine" / "nexus"
    nexus_dir.mkdir(parents=True, exist_ok=True)
    (nexus_dir / "nexus_session_logger.py").write_text("# logger", encoding="utf-8")
    (nexus_dir / "copilot_bridge.py").write_text("# bridge", encoding="utf-8")


def test_validate_nexus_sync_reports_current_sources(tmp_path: Path) -> None:
    """Validator passes when Nexus entries match disk content."""
    source_file = tmp_path / "guide.md"
    source_file.write_text("latest guidance", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[Copilot Rules] Guide",
        "category": "copilot-rules",
        "tags": ["copilot", "guide"],
    }
    state = {str(source_file): mod._file_hash(source_file)}
    sync_config = _FakeSyncConfig({
        "[Copilot Rules] Guide": {
            "title": "[Copilot Rules] Guide",
            "content": "latest guidance",
            "content_type": "document",
            "category": "copilot-rules",
            "tags": ["copilot", "guide"],
        }
    })

    report = mod.validate_nexus_sync(
        sources=[source],
        state=state,
        client=_FakeClient({
            "copilot-rules": [sync_config.entries["[Copilot Rules] Guide"]],
        }),
        sync_config=sync_config,
    )

    assert report["ok"] is True
    assert report["current_count"] == 1
    assert report["stale_count"] == 0


def test_validate_nexus_sync_flags_missing_entry_even_when_hash_matches(tmp_path: Path) -> None:
    """Missing Nexus mirrors should fail validation."""
    source_file = tmp_path / "guide.md"
    source_file.write_text("latest guidance", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[Copilot Rules] Guide",
        "category": "copilot-rules",
        "tags": ["copilot", "guide"],
    }
    state = {str(source_file): mod._file_hash(source_file)}
    sync_config = _FakeSyncConfig({})

    report = mod.validate_nexus_sync(
        sources=[source],
        state=state,
        client=_FakeClient(),
        sync_config=sync_config,
    )

    assert report["ok"] is False
    assert report["current_count"] == 0
    assert report["stale_count"] == 1
    assert any(issue["code"] == "missing_entry" for issue in report["issues"])


def test_validate_nexus_sync_prefers_exact_current_mirror_among_duplicates(tmp_path: Path) -> None:
    """Validator should pass when category listing contains both stale and current duplicates."""
    source_file = tmp_path / "guide.md"
    source_file.write_text("latest guidance", encoding="utf-8")
    source = {
        "path": source_file,
        "title": "[Copilot Rules] Guide",
        "category": "copilot-rules",
        "tags": ["copilot", "guide"],
    }
    state = {str(source_file): mod._file_hash(source_file)}
    sync_config = _FakeSyncConfig({
        "[Copilot Rules] Guide": {
            "title": "[Copilot Rules] Guide",
            "content": "stale guidance",
            "content_type": "document",
            "category": "copilot-rules",
            "tags": ["copilot", "guide", "stale"],
        }
    })
    client = _FakeClient({
        "copilot-rules": [
            {
                "title": "[Copilot Rules] Guide",
                "content": "stale guidance",
                "content_type": "document",
                "category": "copilot-rules",
                "tags": ["copilot", "guide", "stale"],
            },
            {
                "title": "[Copilot Rules] Guide",
                "content": "latest guidance",
                "content_type": "document",
                "category": "copilot-rules",
                "tags": ["copilot", "guide"],
            },
        ]
    })

    report = mod.validate_nexus_sync(
        sources=[source],
        state=state,
        client=client,
        sync_config=sync_config,
    )

    assert report["ok"] is True
    assert report["current_count"] == 1
    assert report["stale_count"] == 0
    assert report["warning_source_count"] == 1
    assert any(issue["code"] == "duplicate_exact_title" for issue in report["issues"])


def test_validate_hook_integrity_passes_with_required_manifests(tmp_path: Path) -> None:
    """Hook validation passes when manifests and scripts are present."""
    _write_hook_runtime(tmp_path)

    report = mod.validate_hook_integrity(project_root=tmp_path)

    assert report["ok"] is True
    assert report["issues"] == []


def test_validate_hook_integrity_flags_missing_required_script(tmp_path: Path) -> None:
    """Missing hook runtime files should fail validation."""
    _write_hook_runtime(tmp_path)
    (tmp_path / ".github" / "hooks" / "scripts" / "check-tool-safety.ps1").unlink()

    report = mod.validate_hook_integrity(project_root=tmp_path)

    assert report["ok"] is False
    assert any(issue["code"] == "missing_hook_file" for issue in report["issues"])


def test_validate_runtime_health_reports_expected_surfaces() -> None:
    """Runtime validation passes when onboarding and runtime context are complete."""
    onboarding = {
        "rules": [{"title": "rule"}],
        "resume_handoff": {},
        "capture_policy": {
            "nexus_first": True,
            "backfill_external_discoveries": True,
            "preferred_capture": ["knowledge_entry", "qa_pair"],
        },
        "system_inventory": {
            "summary": {
                "domain_count": 10,
                "nexus_first": True,
            }
        },
    }
    bridge = _FakeBridge(
        onboarding=onboarding,
        session_context={
            "onboarding": onboarding,
            "runtime_context": {"guidance": ["Backfill discoveries into Nexus."]},
            "startup_services": {
                "nexus": {"loaded": True},
                "task_scheduler": {"loaded": True},
                "operator_inbox": {"loaded": True},
                "system_inventory": {"loaded": True},
            },
        },
    )

    report = mod.validate_runtime_health(
        bridge=bridge,
        config=_FakeConfig(),
    )

    assert report["ok"] is True
    assert report["runtime_context_loaded"] is True
    assert report["system_inventory_summary"]["domain_count"] == 10


def test_validate_runtime_health_flags_missing_capture_policy() -> None:
    """Missing runtime governance surfaces should fail validation."""
    onboarding = {
        "rules": [],
        "system_inventory": {"summary": {"domain_count": 0, "nexus_first": False}},
    }
    bridge = _FakeBridge(
        onboarding=onboarding,
        session_context={"onboarding": onboarding},
    )

    report = mod.validate_runtime_health(
        bridge=bridge,
        config=_FakeConfig(),
    )

    assert report["ok"] is False
    assert any(issue["code"] == "capture_policy_missing" for issue in report["issues"])
    assert any(issue["code"] == "runtime_context_missing" for issue in report["issues"])


def test_run_copilot_validation_aggregates_section_results(monkeypatch, tmp_path: Path) -> None:
    """Combined validation report should aggregate section outcomes."""
    monkeypatch.setattr(
        mod,
        "validate_nexus_sync",
        lambda **kwargs: {"ok": True, "issues": []},
    )
    monkeypatch.setattr(
        mod,
        "validate_hook_integrity",
        lambda project_root=None: {"ok": False, "issues": [{"severity": "error", "code": "hook"}]},
    )
    monkeypatch.setattr(
        mod,
        "validate_runtime_health",
        lambda **kwargs: {"ok": True, "issues": [{"severity": "warning", "code": "warn"}]},
    )

    report = mod.run_copilot_validation(project_root=tmp_path)

    assert report["ok"] is False
    assert report["error_count"] == 1
    assert report["warning_count"] == 1


def test_autonomy_skill_returns_validation_report(monkeypatch) -> None:
    """Autonomy skill should expose the validation report as JSON."""
    monkeypatch.setattr(mod, "run_copilot_validation", lambda **kwargs: {"ok": True, "issue_count": 0})

    from engine.skills.builtin.autonomy_skills import copilot_validate_runtime

    result = json.loads(copilot_validate_runtime())
    assert result["ok"] is True
