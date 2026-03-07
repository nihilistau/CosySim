"""Tests for Copilot hook scripts that enforce Nexus-first behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPTS_DIR = REPO_ROOT / ".github" / "hooks" / "scripts"
HOOKS_FILE = REPO_ROOT / ".github" / "hooks" / "cosysim-hooks.json"
SESSION_LOGGER_HOOKS_FILE = REPO_ROOT / ".github" / "hooks" / "session-logger" / "hooks.json"


def _copy_hook_script(tmp_path: Path, script_name: str) -> Path:
    hooks_root = tmp_path / ".github" / "hooks"
    scripts_dir = hooks_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    source = HOOK_SCRIPTS_DIR / script_name
    target = scripts_dir / script_name
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _run_hook(script_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        cwd=str(REPO_ROOT),
    )


def test_log_tool_usage_marks_successful_notebooklm_consult_without_overwriting_session(
    tmp_path: Path,
) -> None:
    """Successful NotebookLM queries should merge consultation state into the session file."""
    script_path = _copy_hook_script(tmp_path, "log-tool-usage.ps1")
    logs_dir = script_path.parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    session_file = logs_dir / "current_session.json"
    session_file.write_text(
        json.dumps({"session_id": "abc123", "prompts": 2}, indent=2),
        encoding="utf-8",
    )

    result = _run_hook(
        script_path,
        {
            "toolName": "functions.notebooklm-ask_question",
            "timestamp": "2026-03-06T12:00:00Z",
            "sessionId": "abc123",
        },
    )

    assert result.returncode == 0
    session = json.loads(session_file.read_text(encoding="utf-8"))
    assert session["session_id"] == "abc123"
    assert session["prompts"] == 2
    assert session["nexus_consulted"] is True
    assert session["nexus_last_tool"] == "functions.notebooklm-ask_question"
    assert session["nexus_last_success_at"] == "2026-03-06T12:00:00Z"


def test_check_tool_safety_denies_parallel_apply_patch_without_prior_consult(
    tmp_path: Path,
) -> None:
    """Nested apply_patch calls inside parallel require prior successful knowledge consultation."""
    script_path = _copy_hook_script(tmp_path, "check-tool-safety.ps1")

    result = _run_hook(
        script_path,
        {
            "toolName": "multi_tool_use.parallel",
            "input": {
                "tool_uses": [
                    {
                        "recipient_name": "functions.apply_patch",
                        "parameters": {
                            "input": "\n".join(
                                [
                                    "*** Begin Patch",
                                    "*** Update File: docs\\guide.md",
                                    "@@",
                                    "-old",
                                    "+new",
                                    "*** End Patch",
                                ]
                            )
                        },
                    }
                ]
            },
        },
    )

    assert result.returncode == 0
    decision = json.loads(result.stdout.strip())
    assert decision["decision"] == "deny"
    assert "Nexus-first required" in decision["reason"]


def test_check_tool_safety_allows_parallel_apply_patch_after_prior_consult(
    tmp_path: Path,
) -> None:
    """Previously successful Nexus consultation should satisfy later parallel edit enforcement."""
    script_path = _copy_hook_script(tmp_path, "check-tool-safety.ps1")
    logs_dir = script_path.parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "current_session.json").write_text(
        json.dumps({"session_id": "abc123", "nexus_consulted": True}, indent=2),
        encoding="utf-8",
    )

    result = _run_hook(
        script_path,
        {
            "toolName": "multi_tool_use.parallel",
            "input": {
                "tool_uses": [
                    {
                        "recipient_name": "functions.apply_patch",
                        "parameters": {
                            "input": "\n".join(
                                [
                                    "*** Begin Patch",
                                    "*** Update File: docs\\guide.md",
                                    "@@",
                                    "-old",
                                    "+new",
                                    "*** End Patch",
                                ]
                            )
                        },
                    }
                ]
            },
        },
    )

    assert result.returncode == 0
    decision = json.loads(result.stdout.strip())
    assert decision["decision"] == "approve"


def test_main_hook_manifest_invokes_session_logger_across_lifecycle() -> None:
    """The main hook pack should keep runtime session history in sync."""
    hooks = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))["hooks"]

    assert any("nexus_session_logger.py start" in hook.get("powershell", "") for hook in hooks["sessionStart"])
    assert any("copilot_hook_control.py run sessionStart" in hook.get("powershell", "") for hook in hooks["sessionStart"])
    assert any("nexus_session_logger.py prompt" in hook.get("powershell", "") for hook in hooks["userPromptSubmitted"])
    assert any("nexus_session_logger.py compact" in hook.get("powershell", "") for hook in hooks["preCompaction"])
    assert any("copilot_hook_control.py run preCompaction" in hook.get("powershell", "") for hook in hooks["preCompaction"])
    assert any("nexus_session_logger.py end" in hook.get("powershell", "") for hook in hooks["sessionEnd"])
    assert any("copilot_hook_control.py run sessionEnd" in hook.get("powershell", "") for hook in hooks["sessionEnd"])
    assert any("copilot_hook_control.py run errorOccurred" in hook.get("powershell", "") for hook in hooks["errorOccurred"])


def test_session_logger_hook_pack_includes_compaction_export() -> None:
    """The standalone session logger hook pack should preserve compaction snapshots too."""
    hooks = json.loads(SESSION_LOGGER_HOOKS_FILE.read_text(encoding="utf-8"))["hooks"]

    assert "preCompaction" in hooks
    assert hooks["preCompaction"][0]["args"] == ["engine/nexus/nexus_session_logger.py", "compact"]
    assert hooks["preCompaction"][1]["args"] == ["engine/nexus/copilot_hook_control.py", "run", "preCompaction"]
    assert hooks["sessionStart"][1]["args"] == ["engine/nexus/copilot_hook_control.py", "run", "sessionStart"]
    assert hooks["sessionEnd"][1]["args"] == ["engine/nexus/copilot_hook_control.py", "run", "sessionEnd"]
