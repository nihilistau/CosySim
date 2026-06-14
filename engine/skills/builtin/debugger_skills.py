"""Debugger skills — MCP-accessible real-time scene diagnostics.

Exposes the ARGUS LiveDebugger as MCP skills so that agents can:
- Run full scene diagnostics
- Stream console errors
- Monitor network failures
- Inspect DOM elements
- Execute JavaScript
- Take & analyze screenshots with vision models
- Check click targets for overlay blocking issues
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=60)
    return asyncio.run(coro)


def _get_debugger(target: str) -> Any:
    """Lazy import to avoid circular dependencies."""
    from scripts.argus.live_debugger import LiveDebugger
    return LiveDebugger(target)


# ── Full Diagnostics ─────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Run a full diagnostic scan on a running CosySim scene. Returns console errors, network failures, JS exceptions, DOM stats, scene health checks, and performance metrics.",
    category="SYSTEM",
    cooldown=5.0,
    cost=2.0,
    tags=["debug", "cdp", "argus", "diagnostics"],
)
def debug_scene(port: int = 5556, include_vision: bool = False) -> str:
    """Full diagnostic scan of a running scene.

    Args:
        port: The port the scene is running on (e.g. 5555 for penthouse)
        include_vision: Also take a screenshot and analyze with vision model
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            await asyncio.sleep(2)  # Collect some events
            report = await dbg.diagnose_scene(include_vision=include_vision)
            return report.summary()
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except ConnectionError:
        return f"ERROR: No Chrome tab found for {target}. Is the scene running and Chrome open with --remote-debugging-port=9223?"
    except Exception as exc:
        return f"ERROR: Diagnostic failed: {exc}"


@skill(
    pack="debugger",
    description="Watch a running scene for errors over a time period. Captures all console errors, network failures, and JS exceptions during the observation window.",
    category="SYSTEM",
    cooldown=5.0,
    cost=3.0,
    tags=["debug", "cdp", "watch", "monitoring"],
)
def debug_watch(port: int = 5556, seconds: int = 15) -> str:
    """Watch a scene for errors over a time period.

    Args:
        port: Scene port number
        seconds: How long to watch (default 15)
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            report = await dbg.watch(
                duration_seconds=seconds,
                on_error=lambda e: logger.warning("LIVE ERROR: %s", e),
            )
            return report.summary()
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Watch failed: {exc}"


# ── Console ──────────────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Stream console logs from a running scene for N seconds. Filter by level (error, warning, log) and text pattern.",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["debug", "console", "logs"],
)
def debug_console(
    port: int = 5556,
    seconds: int = 5,
    level: str = "",
    pattern: str = "",
) -> str:
    """Stream console logs from a scene.

    Args:
        port: Scene port number
        seconds: How long to listen
        level: Filter by level (error, warning, log, info, debug)
        pattern: Filter by text substring
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            await asyncio.sleep(seconds)
            logs = dbg.get_console_logs(
                level=level or None,
                pattern=pattern or None,
                limit=100,
            )
            if not logs:
                return f"No console logs captured in {seconds}s"
            lines = [str(entry) for entry in logs]
            return f"Console logs ({len(lines)} entries in {seconds}s):\n" + "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Console capture failed: {exc}"


# ── Network ──────────────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Monitor network traffic from a running scene. Captures requests and responses, optionally filtered to errors only.",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.0,
    tags=["debug", "network", "http"],
)
def debug_network(
    port: int = 5556,
    seconds: int = 5,
    errors_only: bool = True,
) -> str:
    """Capture network activity from a scene.

    Args:
        port: Scene port number
        seconds: How long to capture
        errors_only: Only show failed requests (status >= 400 or load errors)
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            await asyncio.sleep(seconds)
            entries = dbg.get_network_log(errors_only=errors_only, limit=50)
            if not entries:
                return f"No {'network errors' if errors_only else 'network traffic'} in {seconds}s"
            lines = [str(e) for e in entries]
            return f"Network ({len(lines)} entries):\n" + "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Network capture failed: {exc}"


# ── JavaScript Execution ─────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Execute JavaScript in a running scene and return the result. Useful for inspecting state, checking variables, or triggering actions.",
    category="SYSTEM",
    cooldown=1.0,
    cost=1.0,
    tags=["debug", "javascript", "eval"],
)
def debug_eval(port: int = 5556, js: str = "document.title") -> str:
    """Execute JavaScript in a scene's page context.

    Args:
        port: Scene port number
        js: JavaScript expression to evaluate
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            result = await dbg.eval_js_safe(js)
            if result["ok"]:
                import json
                try:
                    formatted = json.dumps(result["value"], indent=2, default=str)
                except (TypeError, ValueError):
                    formatted = str(result["value"])
                return f"Result:\n{formatted}"
            return f"JS Error: {result['error']}"
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: JS eval failed: {exc}"


# ── DOM Inspection ───────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Inspect a DOM element by CSS selector. Returns tag, id, classes, visibility, position, z-index, pointer-events, and child count.",
    category="SYSTEM",
    cooldown=1.0,
    cost=1.0,
    tags=["debug", "dom", "css", "inspect"],
)
def debug_dom(port: int = 5556, selector: str = "body") -> str:
    """Inspect a DOM element.

    Args:
        port: Scene port number
        selector: CSS selector (e.g. '#my-panel', '.chat-dock', 'canvas')
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            info = await dbg.query_selector(selector)
            if not info:
                return f"Element not found: {selector}"
            import json
            return f"Element {selector}:\n{json.dumps(info, indent=2)}"
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: DOM inspection failed: {exc}"


@skill(
    pack="debugger",
    description="Check the z-index stacking order of all positioned elements. Helps diagnose overlay blocking issues where elements cover interactive targets.",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.5,
    tags=["debug", "dom", "z-index", "overlay"],
)
def debug_z_stack(port: int = 5556) -> str:
    """Get the z-index stacking order of all positioned elements.

    Args:
        port: Scene port number
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            stack = await dbg.check_z_index_stack()
            if not stack:
                return "No positioned elements with explicit z-index found"
            lines = ["Z-Index Stack (highest first):"]
            for el in stack[:30]:
                vis = "✅" if el.get("visible") else "❌"
                pe = el.get("pointerEvents", "auto")
                pe_flag = " (pointer-events:none)" if pe == "none" else ""
                lines.append(
                    f"  z={el['zIndex']:>5}  {vis} {el['tag']}"
                    f"#{el.get('id', '')}.{el.get('classes', '')}"
                    f"  {el.get('position')}{pe_flag}"
                )
            return "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Z-stack check failed: {exc}"


@skill(
    pack="debugger",
    description="Check if specific UI elements are clickable (not blocked by overlays). Provide CSS selectors to test.",
    category="SYSTEM",
    cooldown=2.0,
    cost=1.5,
    tags=["debug", "click", "overlay", "interaction"],
)
def debug_click_test(port: int = 5556, selectors: str = "") -> str:
    """Test if elements are clickable or blocked by overlays.

    Args:
        port: Scene port number
        selectors: Comma-separated CSS selectors to test (e.g. '#btn-send,.side-panel,canvas')
    """
    if not selectors:
        return "ERROR: Provide comma-separated CSS selectors to test"

    target = f"localhost:{port}"
    selector_list = [s.strip() for s in selectors.split(",") if s.strip()]

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            results = await dbg.check_click_targets(selector_list)
            lines = ["Click Target Report:"]
            for sel, info in results.items():
                if not info["exists"]:
                    lines.append(f"  ❌ {sel} — NOT FOUND")
                elif info["clickable"]:
                    lines.append(f"  ✅ {sel} — clickable (z={info.get('zIndex', '?')})")
                else:
                    lines.append(f"  🚫 {sel} — BLOCKED: {info['reason']}")
            return "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Click test failed: {exc}"


# ── Screenshot + Vision ──────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Take a screenshot of a running scene and optionally analyze it with LMStudio vision model. Returns the file path and analysis.",
    category="SYSTEM",
    cooldown=5.0,
    cost=3.0,
    tags=["debug", "screenshot", "vision", "visual"],
)
def debug_screenshot(
    port: int = 5556,
    analyze: bool = True,
    question: str = "Describe what you see. Note any visual issues, broken layouts, missing elements, or error messages.",
) -> str:
    """Take a screenshot and analyze with vision model.

    Args:
        port: Scene port number
        analyze: Also run vision model analysis
        question: What to ask the vision model about the screenshot
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            path = await dbg.take_screenshot()
            lines = [f"Screenshot saved: {path}"]

            if analyze:
                analysis = await dbg.vision_analyze(question)
                lines.append(f"\nVision Analysis:\n{analysis}")

            return "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Screenshot failed: {exc}"


# ── Page Interaction ─────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Click a DOM element in a running scene by CSS selector.",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["debug", "click", "interact"],
)
def debug_click(port: int = 5556, selector: str = "") -> str:
    """Click an element in a running scene.

    Args:
        port: Scene port number
        selector: CSS selector of the element to click
    """
    if not selector:
        return "ERROR: Provide a CSS selector to click"

    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            success = await dbg.click(selector)
            return f"Clicked {selector}: {'success' if success else 'element not found'}"
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Click failed: {exc}"


@skill(
    pack="debugger",
    description="Navigate a scene tab to a different URL.",
    category="SYSTEM",
    cooldown=2.0,
    cost=0.5,
    tags=["debug", "navigate"],
)
def debug_navigate(port: int = 5556, url: str = "") -> str:
    """Navigate the scene tab to a new URL.

    Args:
        port: Scene port number (used to find the tab)
        url: URL to navigate to
    """
    if not url:
        return "ERROR: Provide a URL to navigate to"

    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            await dbg.navigate(url)
            return f"Navigated to {url}"
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Navigation failed: {exc}"


# ── Performance ──────────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Get performance metrics from a running scene including FPS, memory usage, and Chrome metrics.",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.5,
    tags=["debug", "performance", "fps", "memory"],
)
def debug_perf(port: int = 5556) -> str:
    """Get performance metrics for a scene.

    Args:
        port: Scene port number
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            mem = await dbg.get_memory_info()
            fps = await dbg.get_fps_estimate(1000)
            chrome_metrics = await dbg.get_performance_metrics()

            lines = ["Performance Report:"]
            lines.append(f"  FPS: {fps}")
            if mem:
                lines.append(f"  JS Heap Used: {mem.get('used_heap_mb', '?')} MB")
                lines.append(f"  JS Heap Total: {mem.get('total_heap_mb', '?')} MB")
                lines.append(f"  JS Heap Limit: {mem.get('heap_limit_mb', '?')} MB")

            if chrome_metrics:
                important = ["JSHeapUsedSize", "JSHeapTotalSize", "Nodes", "Documents",
                             "Frames", "LayoutCount", "RecalcStyleCount", "TaskDuration"]
                for key in important:
                    if key in chrome_metrics:
                        lines.append(f"  {key}: {chrome_metrics[key]}")

            return "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Performance check failed: {exc}"


# ── Tab Listing ──────────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="List all open Chrome tabs available for debugging via CDP.",
    category="SYSTEM",
    cooldown=1.0,
    cost=0.5,
    tags=["debug", "tabs", "cdp"],
)
def debug_list_tabs() -> str:
    """List all Chrome tabs available for CDP debugging."""
    try:
        from scripts.argus.live_debugger import LiveDebugger
        tabs = LiveDebugger.list_tabs()
        if not tabs:
            return "No Chrome tabs found. Is Chrome running with --remote-debugging-port=9223?"
        lines = ["Open Chrome tabs:"]
        for i, tab in enumerate(tabs):
            lines.append(f"  {i+1}. {tab['title'][:60]} — {tab['url'][:80]}")
        return "\n".join(lines)
    except ConnectionError:
        return "ERROR: Cannot connect to Chrome CDP. Start Chrome with --remote-debugging-port=9223"
    except Exception as exc:
        return f"ERROR: Tab listing failed: {exc}"


# ── Scene Health ─────────────────────────────────────────────────────

@skill(
    pack="debugger",
    description="Quick health check for a CosySim scene — checks Socket.IO, Three.js, canvas, director panel, chat dock, and overlay blocking.",
    category="SYSTEM",
    cooldown=3.0,
    cost=1.0,
    tags=["debug", "health", "scene"],
)
def debug_health(port: int = 5556) -> str:
    """Quick scene health check.

    Args:
        port: Scene port number
    """
    target = f"localhost:{port}"

    async def _run() -> str:
        dbg = _get_debugger(target)
        try:
            await dbg.connect()
            health = await dbg.check_scene_health()
            lines = ["Scene Health Check:"]
            for check, passed in health.items():
                icon = "✅" if passed else "❌"
                lines.append(f"  {icon} {check}")
            return "\n".join(lines)
        finally:
            await dbg.disconnect()

    try:
        return _run_async(_run())
    except Exception as exc:
        return f"ERROR: Health check failed: {exc}"
