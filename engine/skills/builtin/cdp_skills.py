"""CDP browser debugging skills — exposes Chrome DevTools Protocol tools to agents.

Agents use these to inspect live browser state, mark timeline events, tail error logs,
and mine debug sessions for training data — all without leaving the agent context.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from engine.skills.skill import skill

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_LOGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs"


def _run_cdp(args: List[str], timeout: int = 15) -> str:
    """Run cdp_monitor.py with given subcommand args, return stdout."""
    script = _SCRIPTS_DIR / "cdp_monitor.py"
    result = subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 and result.stderr:
        return f"[CDP ERROR] {result.stderr[:300]}"
    return result.stdout.strip() or "(no output)"


def _run_inspect(args: List[str], timeout: int = 20) -> str:
    """Run cdp_inspect.py with given subcommand args, return stdout."""
    script = _SCRIPTS_DIR / "cdp_inspect.py"
    result = subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 and result.stderr:
        return f"[CDP ERROR] {result.stderr[:300]}"
    return result.stdout.strip() or "(no output)"


# ──── Timeline Markers ────

@skill(
    pack="cdp",
    description=(
        "Insert a named timeline marker into the CDP debug log. "
        "Call this immediately BEFORE making any file change so the monitor records "
        "exactly which errors appeared before vs after the change."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "timeline"],
)
def cdp_mark(message: str) -> str:
    """Mark a point in the debug timeline.

    Args:
        message: Short description of what is about to change, e.g. 'fixing navbar template'.

    Returns:
        Confirmation with timestamp of the inserted marker.
    """
    return _run_cdp(["mark", message])


# ──── Log Inspection ────

@skill(
    pack="cdp",
    description=(
        "Tail the live CDP error log. Returns the last N lines from logs/cdp.log, "
        "including browser console errors, network failures, and timeline markers."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "logs"],
)
def cdp_tail(lines: int = 40) -> str:
    """Read the last N lines of the CDP monitor log.

    Args:
        lines: Number of lines to return (default 40).

    Returns:
        Most recent log lines with timestamps and delta markers.
    """
    log_path = _LOGS_DIR / "cdp.log"
    if not log_path.exists():
        return "[cdp_tail] logs/cdp.log does not exist — is cdp_monitor running?"
    all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(all_lines[-lines:]) if all_lines else "(log is empty)"


@skill(
    pack="cdp",
    description=(
        "Return all browser errors that appeared since the last timeline marker. "
        "Useful immediately after a file change to see whether the change introduced "
        "or resolved errors."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "errors"],
)
def cdp_errors() -> str:
    """Get errors since last marker.

    Returns:
        Deduplicated list of browser console errors since the last cdp_mark call.
    """
    return _run_cdp(["errors"])


@skill(
    pack="cdp",
    description=(
        "Show the timeline: list of all markers with their timestamps and the count of "
        "browser errors that occurred between each pair of markers. "
        "Use this to understand when regressions were introduced."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "timeline"],
)
def cdp_timeline() -> str:
    """Show full debug timeline.

    Returns:
        Ordered list of timeline markers with error counts between each.
    """
    return _run_cdp(["timeline"])


# ──── DOM / CSS / Network Inspection ────

@skill(
    pack="cdp",
    description=(
        "Inspect the live DOM of a running CosySim scene in Chrome. "
        "Finds the matching tab by port and returns the full document.body.innerHTML "
        "or the outerHTML of a specific CSS selector."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "dom"],
)
def cdp_dom(port: int = 5556, selector: str = "") -> str:
    """Inspect DOM of a live scene tab.

    Args:
        port: Scene port (e.g. 5556 for penthouse/phone).
        selector: Optional CSS selector to extract a specific element.

    Returns:
        Outer HTML of matched element, or first 4000 chars of body innerHTML.
    """
    args = ["dom", "--port", str(port)]
    if selector:
        args += ["--selector", selector]
    return _run_inspect(args)


@skill(
    pack="cdp",
    description=(
        "Inspect computed CSS styles for an element in a live scene. "
        "Useful for diagnosing z-index, pointer-events, display, position issues "
        "that cause click-blocking or invisible elements."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "css"],
)
def cdp_css(port: int = 5556, selector: str = "body") -> str:
    """Get computed CSS for a DOM element.

    Args:
        port: Scene port.
        selector: CSS selector of the element to inspect.

    Returns:
        Key computed CSS properties (position, z-index, pointer-events, display, etc.).
    """
    return _run_inspect(["css", "--port", str(port), "--selector", selector])


@skill(
    pack="cdp",
    description=(
        "Take a full-page screenshot of a live scene and save it to logs/. "
        "Returns the path to the saved PNG. "
        "Use before and after a fix to visually verify the change."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "screenshot"],
)
def cdp_snap(port: int = 5556) -> str:
    """Screenshot a live scene tab.

    Args:
        port: Scene port to screenshot.

    Returns:
        Path to saved PNG screenshot file.
    """
    return _run_inspect(["snap", "--port", str(port)])


@skill(
    pack="cdp",
    description=(
        "List all Chrome tabs currently open on the debug port (9222). "
        "Returns tab ID, title, and URL for each tab. "
        "Use to find which tab corresponds to a given scene."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "tabs"],
)
def cdp_tabs() -> str:
    """List open Chrome debug tabs.

    Returns:
        JSON list of {id, title, url} for each open tab.
    """
    return _run_inspect(["tabs"])


@skill(
    pack="cdp",
    description=(
        "Evaluate a JavaScript expression in a live scene tab and return the result. "
        "Use to inspect runtime state: check if a JS object is defined, read a variable, "
        "count DOM elements, check event listeners, etc."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "js"],
)
def cdp_js(expression: str, port: int = 5556) -> str:
    """Evaluate JS in a live scene tab.

    Args:
        expression: JavaScript expression to evaluate (e.g. 'typeof CosyNavbar').
        port: Scene port of the tab to run in.

    Returns:
        JSON-serialised result of the expression.
    """
    return _run_inspect(["js", "--port", str(port), "--expr", expression])


# ──── Training Data Mining ────

@skill(
    pack="cdp",
    description=(
        "Mine the accumulated CDP debug logs to extract supervised training examples. "
        "Produces browser_debugger and error_classifier datasets in training/datasets/collected/. "
        "Returns a summary of how many examples were extracted per dataset type."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "training"],
)
def cdp_mine() -> str:
    """Mine CDP logs for training data.

    Returns:
        Summary of training examples extracted by dataset type.
    """
    script = _SCRIPTS_DIR / "cdp_data_miner.py"
    result = subprocess.run(
        [sys.executable, str(script), "run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return f"[cdp_mine ERROR] {result.stderr[:400]}"
    return result.stdout.strip() or "(miner produced no output)"


@skill(
    pack="cdp",
    description=(
        "Return a quick summary of the CDP debug session: "
        "total errors logged, number of timeline markers, "
        "most common error categories, and whether the monitor is running."
    ),
    category="SYSTEM",
    tags=["debug", "cdp", "status"],
)
def cdp_status() -> str:
    """Get CDP monitor status and log summary.

    Returns:
        Dict with event counts, marker count, top error categories, monitor PID.
    """
    events_path = _LOGS_DIR / "cdp_events.jsonl"
    markers_path = _LOGS_DIR / "cdp_markers.jsonl"

    if not events_path.exists():
        return json.dumps({"running": False, "message": "No events log found."})

    events: List[Dict[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                events.append(json.loads(line))
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})

    marker_count = 0
    if markers_path.exists():
        marker_count = sum(
            1 for line in markers_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    categories: Dict[str, int] = {}
    for ev in events:
        cat = ev.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    top_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]

    return json.dumps(
        {
            "total_events": len(events),
            "markers": marker_count,
            "top_categories": dict(top_cats),
            "log_size_kb": round(events_path.stat().st_size / 1024, 1),
        },
        indent=2,
    )
