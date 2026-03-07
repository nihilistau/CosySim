"""Copilot validation — checks sync drift, hook integrity, and runtime health.

This module validates the Copilot control plane across three surfaces:
1. Nexus sync drift for Copilot rules and mirrored documentation
2. Hook manifest integrity for logging, safety, and bridge callbacks
3. Runtime health for CopilotSelfConfig and CopilotBridge onboarding surfaces
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from engine.nexus.client import get_nexus_client
from engine.nexus.copilot_bridge import CopilotBridge, get_copilot_bridge
from engine.nexus.copilot_self_config import CopilotSelfConfig, get_copilot_config
from engine.nexus.seed_copilot_rules import REPO_ROOT, _file_hash, _get_sources, _load_state

logger = logging.getLogger(__name__)

MAIN_HOOKS_FILE = REPO_ROOT / ".github" / "hooks" / "cosysim-hooks.json"
SESSION_LOGGER_HOOKS_FILE = REPO_ROOT / ".github" / "hooks" / "session-logger" / "hooks.json"

REQUIRED_MAIN_HOOK_CHECKS = (
    ("sessionStart", "nexus_session_logger.py start"),
    ("sessionStart", "get_copilot_bridge().session_start"),
    ("sessionStart", "copilot_hook_control.py run sessionStart"),
    ("userPromptSubmitted", "nexus_session_logger.py prompt"),
    ("sessionEnd", "get_copilot_bridge().session_end"),
    ("sessionEnd", "copilot_hook_control.py run sessionEnd"),
    ("sessionEnd", "nexus_session_logger.py end"),
    ("preCompaction", "nexus_session_logger.py compact"),
    ("preCompaction", "copilot_hook_control.py run preCompaction"),
    ("postToolUse", "log-tool-usage.ps1"),
    ("postToolUse", "get_copilot_bridge().track_tool_use"),
    ("preToolUse", "check-tool-safety.ps1"),
    ("errorOccurred", "log-errors.ps1"),
    ("errorOccurred", "copilot_hook_control.py run errorOccurred"),
    ("errorOccurred", "get_copilot_bridge().track_error"),
)

REQUIRED_SESSION_LOGGER_CHECKS = (
    ("sessionStart", "engine/nexus/nexus_session_logger.py start"),
    ("userPromptSubmitted", "engine/nexus/nexus_session_logger.py prompt"),
    ("sessionEnd", "engine/nexus/nexus_session_logger.py end"),
    ("preCompaction", "engine/nexus/nexus_session_logger.py compact"),
)

REQUIRED_HOOK_FILES = (
    ".github/hooks/scripts/log-session.ps1",
    ".github/hooks/scripts/log-tool-usage.ps1",
    ".github/hooks/scripts/check-tool-safety.ps1",
    ".github/hooks/scripts/log-errors.ps1",
    "engine/nexus/nexus_session_logger.py",
    "engine/nexus/copilot_bridge.py",
    "engine/nexus/copilot_hook_control.py",
)


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    source: str = "",
) -> Dict[str, str]:
    """Build a structured validation issue."""
    payload = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if source:
        payload["source"] = source
    return payload


def _has_errors(issues: List[Dict[str, str]]) -> bool:
    """Return True when any issue is an error."""
    return any(issue.get("severity") == "error" for issue in issues)


def _read_source_content(source: Dict[str, Any]) -> str:
    """Read a sync source exactly as the seeder would."""
    path = source["path"]
    max_chars = source.get("max_chars", 0)
    content = path.read_text(encoding="utf-8", errors="replace")
    if max_chars:
        content = content[-max_chars:]
    return content


def _matching_entries(
    client: Any,
    sync_config: CopilotSelfConfig,
    title: str,
    category: str,
) -> List[Any]:
    """Return exact title/category matches from Nexus."""
    matches: List[Any] = []
    if hasattr(client, "list_entries"):
        try:
            for entry in client.list_entries(category=category, limit=200):
                if (
                    sync_config._entry_field(entry, "title", "") == title  # noqa: SLF001
                    and sync_config._entry_field(entry, "category", "") == category  # noqa: SLF001
                ):
                    matches.append(entry)
        except Exception as exc:
            logger.debug("Category listing failed for %s: %s", title, exc)

    if matches:
        return matches

    existing = sync_config._find_existing_entry(  # noqa: SLF001 - fallback shared with sync path
        client,
        title,
        title,
        category,
    )
    return [existing] if existing is not None else []


def _entry_drift_issues(
    sync_config: CopilotSelfConfig,
    existing: Any,
    *,
    title: str,
    path: Path,
    category: str,
    content: str,
    expected_type: str,
    expected_tags: List[str],
) -> List[Dict[str, str]]:
    """Compare a Nexus entry against the expected on-disk source state."""
    source_issues: List[Dict[str, str]] = []
    existing_content = sync_config._entry_field(existing, "content", "")  # noqa: SLF001
    existing_type = sync_config._entry_field(existing, "content_type", "")  # noqa: SLF001
    existing_tags = sync_config._normalized_tags(  # noqa: SLF001
        category,
        list(sync_config._entry_field(existing, "tags", []) or []),  # noqa: SLF001
    )
    normalized_expected_tags = sync_config._normalized_tags(category, expected_tags)  # noqa: SLF001
    if existing_content != content:
        source_issues.append(
            _issue(
                "content_drift",
                f"{title} has drifted between disk and Nexus.",
                source=str(path),
            )
        )
    if existing_type != expected_type:
        source_issues.append(
            _issue(
                "type_drift",
                f"{title} has content_type={existing_type!r} in Nexus, expected {expected_type!r}.",
                source=str(path),
            )
        )
    if existing_tags != normalized_expected_tags:
        source_issues.append(
            _issue(
                "tags_drift",
                f"{title} has drifted tags in Nexus.",
                source=str(path),
            )
        )
    return source_issues


def _hook_commands_for_event(hooks: Dict[str, Any], event: str) -> List[Dict[str, Any]]:
    """Return hook command payloads for an event."""
    event_hooks = hooks.get(event, [])
    return event_hooks if isinstance(event_hooks, list) else []


def _hook_contains_text(hooks: Dict[str, Any], event: str, text: str) -> bool:
    """Return True when a hook event contains the expected text."""
    for hook in _hook_commands_for_event(hooks, event):
        powershell = hook.get("powershell", "")
        bash = hook.get("bash", "")
        args = " ".join(str(item) for item in hook.get("args", []))
        if text in powershell or text in bash or text in args:
            return True
    return False


def validate_nexus_sync(
    *,
    sources: Optional[List[Dict[str, Any]]] = None,
    state: Optional[Dict[str, str]] = None,
    client: Any = None,
    sync_config: Optional[CopilotSelfConfig] = None,
) -> Dict[str, Any]:
    """Validate that Copilot sources are mirrored into Nexus without drift."""
    selected_sources = list(sources) if sources is not None else _get_sources()
    seed_state = dict(state) if state is not None else _load_state()
    issues: List[Dict[str, str]] = []
    stale_sources: List[Dict[str, Any]] = []
    warning_sources: List[Dict[str, Any]] = []

    try:
        nexus_client = client or get_nexus_client()
        config = sync_config or get_copilot_config()
    except Exception as exc:
        issues.append(
            _issue(
                "nexus_unavailable",
                f"Could not initialize Copilot Nexus validation: {exc}",
            )
        )
        return {
            "ok": False,
            "source_count": len(selected_sources),
            "current_count": 0,
            "stale_count": len(selected_sources),
            "issues": issues,
            "stale_sources": [
                {"title": source["title"], "path": str(source["path"])}
                for source in selected_sources
            ],
        }

    current_count = 0
    for source in selected_sources:
        path = source["path"]
        title = source["title"]
        category = source["category"]
        source_issues: List[Dict[str, str]] = []
        content = _read_source_content(source)
        expected_tags = list(source.get("tags", []))
        expected_type = source.get("content_type", "document")

        matches = _matching_entries(nexus_client, config, title, category)
        if not matches:
            source_issues.append(
                _issue(
                    "missing_entry",
                    f"{title} is not mirrored into Nexus.",
                    source=str(path),
                    )
                )
        else:
            exact_match_found = False
            drift_candidates: List[Dict[str, str]] = []
            for existing in matches:
                drift = _entry_drift_issues(
                    config,
                    existing,
                    title=title,
                    path=path,
                    category=category,
                    content=content,
                    expected_type=expected_type,
                    expected_tags=expected_tags,
                )
                if not drift:
                    exact_match_found = True
                    break
                if not drift_candidates:
                    drift_candidates = drift
            if not exact_match_found:
                source_issues.extend(drift_candidates)
            elif len(matches) > 1:
                source_issues.append(
                    _issue(
                        "duplicate_exact_title",
                        f"{title} has multiple Nexus mirrors in category {category!r}; the validator found a current one but duplicates remain.",
                        severity="warning",
                        source=str(path),
                    )
                )

        state_hash = seed_state.get(str(path))
        current_hash = _file_hash(path, source.get("max_chars", 0))
        if not state_hash:
            source_issues.append(
                _issue(
                    "seed_state_missing",
                    f"{title} is not tracked in the Copilot seed state file yet.",
                    severity="warning",
                    source=str(path),
                )
            )
        elif state_hash != current_hash:
            source_issues.append(
                _issue(
                    "seed_state_stale",
                    f"{title} changed on disk after the last recorded Copilot rules seed.",
                    severity="warning",
                    source=str(path),
                )
            )

        if source_issues:
            payload = {
                "title": title,
                "path": str(path),
                "issues": source_issues,
            }
            if _has_errors(source_issues):
                stale_sources.append(payload)
            else:
                warning_sources.append(payload)
                current_count += 1
            issues.extend(source_issues)
        else:
            current_count += 1

    return {
        "ok": not _has_errors(issues),
        "source_count": len(selected_sources),
        "current_count": current_count,
        "stale_count": len(stale_sources),
        "warning_source_count": len(warning_sources),
        "issues": issues,
        "stale_sources": stale_sources,
        "warning_sources": warning_sources,
    }


def validate_hook_integrity(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Validate hook manifests and referenced scripts for Copilot runtime safety."""
    root = project_root or REPO_ROOT
    main_hooks_path = root / ".github" / "hooks" / "cosysim-hooks.json"
    session_hooks_path = root / ".github" / "hooks" / "session-logger" / "hooks.json"
    issues: List[Dict[str, str]] = []

    if not main_hooks_path.exists():
        issues.append(_issue("missing_main_manifest", "Main Copilot hook manifest is missing."))
        main_hooks: Dict[str, Any] = {}
    else:
        main_hooks = json.loads(main_hooks_path.read_text(encoding="utf-8")).get("hooks", {})

    if not session_hooks_path.exists():
        issues.append(_issue("missing_session_manifest", "Session logger hook manifest is missing."))
        session_hooks: Dict[str, Any] = {}
    else:
        session_hooks = json.loads(session_hooks_path.read_text(encoding="utf-8")).get("hooks", {})

    for event, expected in REQUIRED_MAIN_HOOK_CHECKS:
        if not _hook_contains_text(main_hooks, event, expected):
            issues.append(
                _issue(
                    "missing_hook_check",
                    f"Main hook manifest event {event!r} is missing {expected!r}.",
                    source=str(main_hooks_path),
                )
            )

    for event, expected in REQUIRED_SESSION_LOGGER_CHECKS:
        if not _hook_contains_text(session_hooks, event, expected):
            issues.append(
                _issue(
                    "missing_session_hook_check",
                    f"Session logger hook manifest event {event!r} is missing {expected!r}.",
                    source=str(session_hooks_path),
                )
            )

    missing_files = []
    for relative_path in REQUIRED_HOOK_FILES:
        target = root / relative_path
        if not target.exists():
            missing_files.append(str(target))
            issues.append(
                _issue(
                    "missing_hook_file",
                    f"Required Copilot runtime file is missing: {relative_path}",
                    source=str(target),
                )
            )

    return {
        "ok": not _has_errors(issues),
        "issues": issues,
        "checked_files": [str(main_hooks_path), str(session_hooks_path)],
        "missing_files": missing_files,
    }


def validate_runtime_health(
    *,
    bridge: Optional[CopilotBridge] = None,
    config: Optional[CopilotSelfConfig] = None,
) -> Dict[str, Any]:
    """Validate Copilot runtime onboarding and health surfaces."""
    issues: List[Dict[str, str]] = []
    runtime_bridge = bridge or get_copilot_bridge()
    runtime_config = config or get_copilot_config()

    config_status = runtime_config.status()
    for key in ("instructions", "agents", "hooks"):
        if config_status.get(key, 0) <= 0:
            issues.append(
                _issue(
                    "empty_config_surface",
                    f"Copilot config status reports no {key}.",
                )
            )

    onboarding = runtime_bridge.get_onboarding_context()
    if onboarding.get("error"):
        issues.append(
            _issue(
                "onboarding_error",
                f"Copilot onboarding context failed: {onboarding['error']}",
            )
        )

    capture_policy = onboarding.get("capture_policy", {})
    if not capture_policy.get("nexus_first"):
        issues.append(_issue("capture_policy_missing", "Copilot capture policy is missing nexus_first enforcement."))
    if not capture_policy.get("backfill_external_discoveries"):
        issues.append(_issue("backfill_policy_missing", "Copilot capture policy is missing external discovery backfill enforcement."))

    preferred_capture = list(capture_policy.get("preferred_capture", []))
    if "knowledge_entry" not in preferred_capture or "qa_pair" not in preferred_capture:
        issues.append(
            _issue(
                "preferred_capture_incomplete",
                "Copilot capture policy should prefer both knowledge entries and Q&A pairs.",
                severity="warning",
            )
        )

    system_inventory = onboarding.get("system_inventory", {})
    summary = system_inventory.get("summary", {}) if isinstance(system_inventory, dict) else {}
    if summary.get("domain_count", 0) <= 0:
        issues.append(_issue("inventory_missing", "Onboarding context is missing the canonical system inventory summary."))
    if not summary.get("nexus_first"):
        issues.append(_issue("inventory_policy_missing", "System inventory summary does not report nexus_first=true."))

    if not onboarding.get("rules"):
        issues.append(
            _issue(
                "rules_missing",
                "Onboarding context did not load any Copilot/coding/global rules from Nexus.",
                severity="warning",
            )
        )

    if "resume_handoff" not in onboarding:
        issues.append(
            _issue(
                "resume_handoff_missing",
                "Onboarding context does not expose a resume handoff slot.",
                severity="warning",
            )
        )
    if "context_packet" not in onboarding:
        issues.append(
            _issue(
                "context_packet_missing",
                "Onboarding context does not expose a persisted context packet slot.",
                severity="warning",
            )
        )
    if "control_context_packet" not in onboarding:
        issues.append(
            _issue(
                "control_context_packet_missing",
                "Onboarding context does not expose a control flywheel startup packet slot.",
                severity="warning",
            )
        )

    session_context = runtime_bridge.session_start("copilot runtime validation")
    if "onboarding" not in session_context:
        issues.append(_issue("session_onboarding_missing", "CopilotBridge.session_start() did not attach onboarding context."))
    if "startup_services" not in session_context:
        issues.append(_issue("startup_services_missing", "CopilotBridge.session_start() did not warm/load startup services."))
    if "runtime_context" not in session_context:
        issues.append(_issue("runtime_context_missing", "CopilotBridge.session_start() did not attach runtime context for a runtime task."))
    else:
        guidance = session_context["runtime_context"].get("guidance", [])
        if not any("backfill" in item.lower() for item in guidance if isinstance(item, str)):
            issues.append(
                _issue(
                    "runtime_guidance_missing",
                    "Runtime context guidance does not remind Copilot to backfill external discoveries.",
                    severity="warning",
                )
            )

    startup_services = session_context.get("startup_services", {})
    for key in ("nexus", "task_scheduler", "operator_inbox", "system_inventory"):
        state = startup_services.get(key, {}) if isinstance(startup_services, dict) else {}
        if not state.get("loaded"):
            issues.append(
                _issue(
                    f"startup_service_{key}_not_loaded",
                    f"Startup service '{key}' did not report loaded=true during session_start().",
                    severity="warning",
                )
            )

    metrics = runtime_bridge.metrics.to_dict()
    if "domains_touched" not in metrics:
        issues.append(_issue("metrics_surface_missing", "CopilotBridge metrics do not expose domains_touched."))

    return {
        "ok": not _has_errors(issues),
        "issues": issues,
        "config_status": config_status,
        "onboarding_rule_count": len(onboarding.get("rules", [])),
        "system_inventory_summary": summary,
        "runtime_context_loaded": "runtime_context" in session_context,
        "metrics": metrics,
    }


def run_copilot_validation(
    *,
    project_root: Optional[Path] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    state: Optional[Dict[str, str]] = None,
    client: Any = None,
    sync_config: Optional[CopilotSelfConfig] = None,
    bridge: Optional[CopilotBridge] = None,
    config: Optional[CopilotSelfConfig] = None,
) -> Dict[str, Any]:
    """Run the full Copilot validation report."""
    nexus_sync = validate_nexus_sync(
        sources=sources,
        state=state,
        client=client,
        sync_config=sync_config,
    )
    hook_integrity = validate_hook_integrity(project_root=project_root)
    runtime_health = validate_runtime_health(bridge=bridge, config=config)

    sections = {
        "nexus_sync": nexus_sync,
        "hook_integrity": hook_integrity,
        "runtime_health": runtime_health,
    }
    all_issues = [issue for section in sections.values() for issue in section.get("issues", [])]
    error_count = sum(1 for issue in all_issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in all_issues if issue.get("severity") == "warning")
    return {
        "ok": error_count == 0,
        "sections": sections,
        "issue_count": len(all_issues),
        "error_count": error_count,
        "warning_count": warning_count,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for Copilot validation."""
    parser = argparse.ArgumentParser(description="Validate Copilot sync, hooks, and runtime health.")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print the full report as JSON.")
    args = parser.parse_args(argv)

    report = run_copilot_validation()
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        status = "OK" if report["ok"] else "FAILED"
        print(f"Copilot validation: {status}")
        for name, section in report["sections"].items():
            section_status = "OK" if section["ok"] else "FAILED"
            print(f"- {name}: {section_status}")
            for issue in section.get("issues", []):
                print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
