"""Custom Copilot hook control runtime for lifecycle snapshots and diagnostics.

This module gives the Copilot control plane a reusable hook-facing runtime that
can be triggered from lifecycle hooks or manually to tail logs, inspect service
health, map listening processes, and persist the resulting snapshot into Nexus.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_LOG_DIR = REPO_ROOT / ".github" / "hooks" / "logs"
SESSION_FILE = HOOK_LOG_DIR / "current_session.json"

DEFAULT_LOG_TARGETS = {
    "hook_session": HOOK_LOG_DIR / "session.log",
    "hook_tools": HOOK_LOG_DIR / "tools.jsonl",
    "hook_errors": HOOK_LOG_DIR / "errors.jsonl",
    "runtime_debug": REPO_ROOT / "debug.log",
    "tui_autostart": REPO_ROOT / "tui_autostart.log",
}

DEFAULT_TARGETS = (
    "nexus",
    "nlm_proxy",
    "lmstudio",
    "hub",
    "nexus_panel",
    "system_control",
    "intel_hub",
    "tts",
    "bridge",
)


def _load_session_state() -> Dict[str, Any]:
    """Return the current hook/session state."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Could not parse session hook state", exc_info=True)
    return {}


def _merge_session_state(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge hook runtime data into the current session file."""
    state = _load_session_state()
    for key, value in updates.items():
        if value is not None:
            state[key] = value
    HOOK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def _tail_lines(path: Path, *, max_lines: int = 20) -> List[str]:
    """Return the last N lines from a log file."""
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        logger.debug("Could not tail %s", path, exc_info=True)
        return []


def _check_health(url: str, *, timeout: int = 3) -> Dict[str, Any]:
    """Run a lightweight health request for a service endpoint."""
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            return {
                "ok": 200 <= getattr(response, "status", 200) < 300,
                "status": int(getattr(response, "status", 200)),
                "latency_ms": latency_ms,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": int(exc.code),
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "error": str(exc),
        }


def _process_map_for_ports(ports: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    """Map listening ports to process metadata when available."""
    try:
        import psutil
    except Exception:
        return {}

    port_set = {int(port) for port in ports if int(port) > 0}
    process_map: Dict[int, Dict[str, Any]] = {}
    if not port_set:
        return process_map

    try:
        for connection in psutil.net_connections(kind="inet"):
            if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                continue
            port = int(connection.laddr.port)
            if port not in port_set or port in process_map:
                continue
            pid = int(connection.pid or 0)
            info: Dict[str, Any] = {"pid": pid}
            if pid:
                try:
                    process = psutil.Process(pid)
                    cmdline = process.cmdline()
                    info.update(
                        {
                            "name": process.name(),
                            "cmdline": cmdline[:6],
                        }
                    )
                except Exception:
                    logger.debug("Could not inspect process for port %s", port, exc_info=True)
            process_map[port] = info
    except Exception:
        logger.debug("Could not inspect listening ports", exc_info=True)
    return process_map


def collect_service_snapshot(target_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Collect health and process metadata for key control-plane services."""
    from engine.port_registry import build_health_endpoints

    endpoints = build_health_endpoints(tuple(target_ids or DEFAULT_TARGETS))
    process_map = _process_map_for_ports(endpoint["port"] for endpoint in endpoints)
    services: List[Dict[str, Any]] = []
    for endpoint in endpoints:
        port = int(endpoint.get("port", 0) or 0)
        services.append(
            {
                "id": endpoint.get("id", ""),
                "name": endpoint.get("name", endpoint.get("id", "")),
                "url": endpoint.get("url", ""),
                "port": port,
                "health": _check_health(str(endpoint.get("url", ""))),
                "process": process_map.get(port, {}),
            }
        )
    return services


def _payload_summary(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Trim hook payloads down to useful control-plane fields."""
    if not isinstance(payload, dict):
        return {}
    summary: Dict[str, Any] = {}
    for key in ("event", "toolName", "timestamp", "sessionId", "summary", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            summary[key] = value[:300]
    if "input" in payload and isinstance(payload["input"], dict):
        summary["input_keys"] = sorted(payload["input"].keys())
    return summary


def build_hook_snapshot(
    event: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    log_targets: Optional[Dict[str, Path]] = None,
    target_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Build a hook snapshot for storage or ad-hoc inspection."""
    targets = dict(log_targets or DEFAULT_LOG_TARGETS)
    return {
        "event": event,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "payload": _payload_summary(payload),
        "session_state": _load_session_state(),
        "services": collect_service_snapshot(target_ids),
        "log_tails": {
            name: _tail_lines(path)
            for name, path in targets.items()
        },
    }


def store_hook_snapshot(snapshot: Dict[str, Any]) -> Optional[str]:
    """Persist a hook snapshot into Nexus."""
    try:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()
        event = str(snapshot.get("event", "hook"))
        timestamp = str(snapshot.get("captured_at", ""))
        return client.add_entry(
            title=f"Copilot Hook Snapshot: {event} — {timestamp}",
            content=json.dumps(snapshot, indent=2),
            content_type="history",
            category="copilot-history",
            tags=["copilot", "hook", "snapshot", event, "monitoring"],
            namespace="copilot",
        )
    except Exception:
        logger.debug("Could not store hook snapshot in Nexus", exc_info=True)
        return None


def run_hook(
    event: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    store: bool = True,
    target_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Run the hook controller for a lifecycle event."""
    snapshot = build_hook_snapshot(event, payload=payload, target_ids=target_ids)
    entry_id = store_hook_snapshot(snapshot) if store else None
    snapshot["entry_id"] = entry_id or ""
    _merge_session_state(
        {
            "last_hook_event": event,
            "last_hook_at": snapshot.get("captured_at", ""),
            "last_hook_snapshot_id": entry_id or "",
        }
    )
    return snapshot


def render_hook_control_reference() -> str:
    """Render a control-plane usage guide for notebooks and docs."""
    return "\n".join(
        [
            "# Copilot Hook Control Runtime",
            "",
            "This runtime captures lifecycle snapshots that include:",
            "- hook/session log tails",
            "- tool/error log tails",
            "- control-plane service health",
            "- listening process metadata by service port",
            "",
            "## Manual usage",
            "- `python engine/nexus/copilot_hook_control.py run checkpoint --emit-json`",
            "- `python engine/nexus/copilot_hook_control.py status --emit-json`",
            "- `python engine/nexus/copilot_hook_control.py tail hook_errors`",
            "",
            "## Lifecycle use",
            "- sessionStart",
            "- preCompaction",
            "- sessionEnd",
            "- checkpoint (triggered by the session logger)",
            "",
            "## Default service targets",
            ", ".join(DEFAULT_TARGETS),
        ]
    )


def _parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse CLI args for manual hook-control operations."""
    parser = argparse.ArgumentParser(description="Copilot hook control runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Capture a lifecycle hook snapshot")
    run_parser.add_argument("event", help="Lifecycle event name")
    run_parser.add_argument("--stdin-json", action="store_true", help="Read payload JSON from stdin")
    run_parser.add_argument("--emit-json", action="store_true", help="Print the snapshot JSON")
    run_parser.add_argument("--no-store", action="store_true", help="Do not persist to Nexus")

    status_parser = subparsers.add_parser("status", help="Capture a control-plane status snapshot")
    status_parser.add_argument("--emit-json", action="store_true", help="Print the snapshot JSON")
    status_parser.add_argument("--no-store", action="store_true", help="Do not persist to Nexus")

    tail_parser = subparsers.add_parser("tail", help="Tail a known hook/runtime log")
    tail_parser.add_argument("log_key", choices=sorted(DEFAULT_LOG_TARGETS.keys()))
    tail_parser.add_argument("--lines", type=int, default=20, help="Number of lines to return")

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for hook control."""
    args = _parse_args(list(argv or sys.argv[1:]))
    if args.command == "tail":
        output = {
            "log_key": args.log_key,
            "lines": _tail_lines(DEFAULT_LOG_TARGETS[args.log_key], max_lines=int(args.lines)),
        }
        print(json.dumps(output, indent=2))
        return 0

    payload: Dict[str, Any] = {}
    if getattr(args, "stdin_json", False):
        raw = sys.stdin.read().strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                logger.debug("Could not parse stdin JSON for hook control", exc_info=True)

    event = args.event if args.command == "run" else "status"
    snapshot = run_hook(event, payload=payload, store=not getattr(args, "no_store", False))
    if getattr(args, "emit_json", False):
        print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
