"""ARGUS Live Debugger — Real-time CDP scene diagnostics toolbox.

Connects to running Chrome tabs via CDP and provides:
- Console log streaming with filtering
- Network error monitoring and request inspection
- JavaScript exception capture
- DOM inspection and element querying
- Screenshot capture + LMStudio vision model analysis
- Page interaction (click, type, navigate, scroll)
- Performance metrics (memory, timing, FPS)
- Scene health diagnostics (Socket.IO, 3D, panels)
- Real-time change verification

Usage::

    from scripts.argus.live_debugger import LiveDebugger

    async with LiveDebugger("localhost:5556") as dbg:
        # Stream console output
        logs = await dbg.get_console_logs(level="error")

        # Check network errors
        errors = await dbg.get_network_errors()

        # Take screenshot and analyze with vision model
        analysis = await dbg.vision_analyze("Is the 3D scene visible?")

        # Execute JavaScript
        result = await dbg.eval_js("document.title")

        # Get full scene diagnostic report
        report = await dbg.diagnose_scene()
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from scripts.argus.cdp_bridge import CDPBridge, CDPSession

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class ConsoleEntry:
    """A captured console log entry."""
    level: str
    text: str
    url: str = ""
    line: int = 0
    timestamp: float = 0.0

    def __str__(self) -> str:
        loc = f" ({self.url}:{self.line})" if self.url else ""
        return f"[{self.level.upper()}] {self.text}{loc}"


@dataclass
class NetworkEntry:
    """A captured network request/response pair."""
    request_id: str
    url: str
    method: str = "GET"
    status: int = 0
    status_text: str = ""
    mime_type: str = ""
    timestamp: float = 0.0
    error_text: str = ""
    response_body: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return self.status >= 400 or bool(self.error_text)

    def __str__(self) -> str:
        if self.error_text:
            return f"[NET ERR] {self.method} {self.url} — {self.error_text}"
        return f"[{self.status}] {self.method} {self.url}"


@dataclass
class JSException:
    """A captured unhandled JavaScript exception."""
    text: str
    url: str = ""
    line: int = 0
    column: int = 0
    stack: str = ""
    timestamp: float = 0.0

    def __str__(self) -> str:
        loc = f" at {self.url}:{self.line}:{self.column}" if self.url else ""
        return f"[EXCEPTION] {self.text}{loc}"


@dataclass
class DiagnosticReport:
    """Complete scene diagnostic report."""
    url: str
    title: str
    timestamp: float
    console_errors: List[ConsoleEntry]
    console_warnings: List[ConsoleEntry]
    network_errors: List[NetworkEntry]
    js_exceptions: List[JSException]
    dom_stats: Dict[str, Any]
    performance: Dict[str, Any]
    scene_health: Dict[str, Any]
    screenshot_path: Optional[str] = None
    vision_analysis: Optional[str] = None

    def summary(self) -> str:
        lines = [
            f"═══ SCENE DIAGNOSTIC: {self.url} ═══",
            f"Title: {self.title}",
            f"Time:  {time.strftime('%H:%M:%S', time.localtime(self.timestamp))}",
            "",
            f"Console Errors:   {len(self.console_errors)}",
            f"Console Warnings: {len(self.console_warnings)}",
            f"Network Errors:   {len(self.network_errors)}",
            f"JS Exceptions:    {len(self.js_exceptions)}",
            "",
        ]

        if self.console_errors:
            lines.append("── Console Errors ──")
            for e in self.console_errors[:10]:
                lines.append(f"  {e}")
            lines.append("")

        if self.network_errors:
            lines.append("── Network Errors ──")
            for e in self.network_errors[:10]:
                lines.append(f"  {e}")
            lines.append("")

        if self.js_exceptions:
            lines.append("── JS Exceptions ──")
            for e in self.js_exceptions[:5]:
                lines.append(f"  {e}")
            lines.append("")

        if self.dom_stats:
            lines.append("── DOM Stats ──")
            for k, v in self.dom_stats.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        if self.performance:
            lines.append("── Performance ──")
            for k, v in self.performance.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        if self.scene_health:
            lines.append("── Scene Health ──")
            for k, v in self.scene_health.items():
                icon = "✅" if v else "❌"
                lines.append(f"  {icon} {k}")
            lines.append("")

        if self.vision_analysis:
            lines.append("── Vision Analysis ──")
            lines.append(f"  {self.vision_analysis}")
            lines.append("")

        return "\n".join(lines)


# ── Live Debugger ────────────────────────────────────────────────────

class LiveDebugger:
    """Real-time CDP-powered scene debugger.

    Connects to a running Chrome tab and provides comprehensive
    diagnostics, interaction, and vision-based analysis.

    Args:
        target: URL or URL fragment to find the tab (e.g. "localhost:5556")
        capture_console: Start capturing console logs immediately
        capture_network: Start capturing network activity immediately
        max_buffer: Maximum entries to keep in each buffer
    """

    def __init__(
        self,
        target: str = "",
        capture_console: bool = True,
        capture_network: bool = True,
        max_buffer: int = 500,
    ) -> None:
        self._target = target
        self._bridge = CDPBridge()
        self._session: Optional[CDPSession] = None
        self._capture_console = capture_console
        self._capture_network = capture_network
        self._max_buffer = max_buffer

        # Buffers
        self._console_logs: Deque[ConsoleEntry] = deque(maxlen=max_buffer)
        self._network_entries: Dict[str, NetworkEntry] = {}
        self._network_log: Deque[NetworkEntry] = deque(maxlen=max_buffer)
        self._js_exceptions: Deque[JSException] = deque(maxlen=max_buffer)

        # State
        self._connected = False
        self._tab_info: Dict[str, Any] = {}

    # ── Lifecycle ────────────────────────────────────────────────────

    async def connect(self, target: Optional[str] = None) -> "LiveDebugger":
        """Connect to a Chrome tab matching the target URL fragment."""
        target = target or self._target
        if not target:
            raise ValueError("No target URL specified")

        tab = self._bridge.get_tab_by_url(target)
        if not tab:
            available = self._bridge.get_tabs()
            urls = [t.get("url", "?") for t in available]
            raise ConnectionError(
                f"No tab found matching '{target}'. "
                f"Available tabs: {urls}"
            )

        self._tab_info = tab
        self._session = await self._bridge.open_session(tab)
        self._connected = True

        # Enable domains
        await self._session.enable_runtime()

        if self._capture_console:
            self._session.on("Runtime.consoleAPICalled", self._on_console)
            self._session.on("Runtime.exceptionThrown", self._on_exception)

        if self._capture_network:
            await self._session.enable_network()
            self._session.on("Network.requestWillBeSent", self._on_request)
            self._session.on("Network.responseReceived", self._on_response)
            self._session.on("Network.loadingFailed", self._on_load_failed)

        # Enable Log domain for browser-level messages
        try:
            await self._session.send("Log.enable")
            self._session.on("Log.entryAdded", self._on_log_entry)
        except Exception:
            pass

        logger.info("LiveDebugger connected to %s", tab.get("url", "?"))
        return self

    async def disconnect(self) -> None:
        """Disconnect from the Chrome tab."""
        if self._session:
            await self._session.disconnect()
            self._session = None
        self._connected = False
        logger.info("LiveDebugger disconnected")

    async def __aenter__(self) -> "LiveDebugger":
        return await self.connect()

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    def _ensure_connected(self) -> CDPSession:
        if not self._session or not self._connected:
            raise RuntimeError("LiveDebugger not connected. Call connect() first.")
        return self._session

    # ── CDP Event Handlers ───────────────────────────────────────────

    def _on_console(self, params: Dict) -> None:
        """Handle Runtime.consoleAPICalled events."""
        args = params.get("args", [])
        parts = []
        for arg in args:
            if arg.get("type") == "string":
                parts.append(arg.get("value", ""))
            elif "description" in arg:
                parts.append(arg["description"])
            elif "value" in arg:
                parts.append(str(arg["value"]))
            else:
                parts.append(str(arg.get("type", "?")))

        text = " ".join(parts)
        level = params.get("type", "log")

        # Extract source location
        stack = params.get("stackTrace", {})
        frames = stack.get("callFrames", [])
        url = frames[0].get("url", "") if frames else ""
        line = frames[0].get("lineNumber", 0) if frames else 0

        entry = ConsoleEntry(
            level=level,
            text=text,
            url=url,
            line=line,
            timestamp=params.get("timestamp", time.time()),
        )
        self._console_logs.append(entry)

    def _on_exception(self, params: Dict) -> None:
        """Handle Runtime.exceptionThrown events."""
        details = params.get("exceptionDetails", {})
        exception = details.get("exception", {})
        text = exception.get("description", details.get("text", "Unknown exception"))

        stack_trace = details.get("stackTrace", {})
        frames = stack_trace.get("callFrames", [])
        stack_lines = []
        for f in frames[:5]:
            stack_lines.append(
                f"  at {f.get('functionName', '?')} ({f.get('url', '?')}:{f.get('lineNumber', 0)})"
            )

        entry = JSException(
            text=text,
            url=details.get("url", ""),
            line=details.get("lineNumber", 0),
            column=details.get("columnNumber", 0),
            stack="\n".join(stack_lines),
            timestamp=params.get("timestamp", time.time()),
        )
        self._js_exceptions.append(entry)

    def _on_request(self, params: Dict) -> None:
        """Handle Network.requestWillBeSent events."""
        req = params.get("request", {})
        request_id = params.get("requestId", "")
        entry = NetworkEntry(
            request_id=request_id,
            url=req.get("url", ""),
            method=req.get("method", "GET"),
            timestamp=params.get("timestamp", time.time()),
        )
        self._network_entries[request_id] = entry

    def _on_response(self, params: Dict) -> None:
        """Handle Network.responseReceived events."""
        request_id = params.get("requestId", "")
        resp = params.get("response", {})
        entry = self._network_entries.get(request_id)
        if entry:
            entry.status = resp.get("status", 0)
            entry.status_text = resp.get("statusText", "")
            entry.mime_type = resp.get("mimeType", "")
            self._network_log.append(entry)

    def _on_load_failed(self, params: Dict) -> None:
        """Handle Network.loadingFailed events."""
        request_id = params.get("requestId", "")
        entry = self._network_entries.get(request_id)
        if entry:
            entry.error_text = params.get("errorText", "Failed")
            entry.status = 0
            self._network_log.append(entry)

    def _on_log_entry(self, params: Dict) -> None:
        """Handle Log.entryAdded events (browser-level logs)."""
        entry_data = params.get("entry", {})
        entry = ConsoleEntry(
            level=entry_data.get("level", "info"),
            text=entry_data.get("text", ""),
            url=entry_data.get("url", ""),
            line=entry_data.get("lineNumber", 0),
            timestamp=entry_data.get("timestamp", time.time()),
        )
        self._console_logs.append(entry)

    # ── Console API ──────────────────────────────────────────────────

    def get_console_logs(
        self,
        level: Optional[str] = None,
        pattern: Optional[str] = None,
        limit: int = 50,
    ) -> List[ConsoleEntry]:
        """Get captured console logs, optionally filtered.

        Args:
            level: Filter by level (error, warning, log, info, debug)
            pattern: Filter by text substring (case-insensitive)
            limit: Maximum entries to return
        """
        logs = list(self._console_logs)
        if level:
            logs = [e for e in logs if e.level == level]
        if pattern:
            p = pattern.lower()
            logs = [e for e in logs if p in e.text.lower()]
        return logs[-limit:]

    def get_errors(self) -> List[ConsoleEntry]:
        """Get all console errors."""
        return self.get_console_logs(level="error")

    def get_warnings(self) -> List[ConsoleEntry]:
        """Get all console warnings."""
        return self.get_console_logs(level="warning")

    def get_exceptions(self) -> List[JSException]:
        """Get all captured JS exceptions."""
        return list(self._js_exceptions)

    def clear_console(self) -> None:
        """Clear the console log buffer."""
        self._console_logs.clear()

    # ── Network API ──────────────────────────────────────────────────

    def get_network_log(
        self,
        errors_only: bool = False,
        pattern: Optional[str] = None,
        limit: int = 50,
    ) -> List[NetworkEntry]:
        """Get captured network entries.

        Args:
            errors_only: Only return entries with status >= 400 or load failures
            pattern: Filter by URL substring
            limit: Maximum entries to return
        """
        entries = list(self._network_log)
        if errors_only:
            entries = [e for e in entries if e.is_error]
        if pattern:
            p = pattern.lower()
            entries = [e for e in entries if p in e.url.lower()]
        return entries[-limit:]

    def get_network_errors(self) -> List[NetworkEntry]:
        """Get all network errors (status >= 400 or failed loads)."""
        return self.get_network_log(errors_only=True)

    async def get_response_body(self, request_id: str) -> Optional[str]:
        """Get the response body for a specific request."""
        session = self._ensure_connected()
        return await session.get_response_body(request_id)

    def clear_network(self) -> None:
        """Clear the network log buffer."""
        self._network_entries.clear()
        self._network_log.clear()

    # ── JavaScript Execution ─────────────────────────────────────────

    async def eval_js(self, expression: str) -> Any:
        """Evaluate JavaScript in the page context and return the result.

        Args:
            expression: JavaScript expression to evaluate

        Returns:
            The evaluated result (primitives returned by value)
        """
        session = self._ensure_connected()
        return await session.evaluate(expression)

    async def eval_js_safe(self, expression: str) -> Dict[str, Any]:
        """Evaluate JS and return {ok, value, error} without raising."""
        try:
            value = await self.eval_js(expression)
            return {"ok": True, "value": value, "error": None}
        except Exception as exc:
            return {"ok": False, "value": None, "error": str(exc)}

    # ── DOM Inspection ───────────────────────────────────────────────

    async def query_selector(self, selector: str) -> Optional[Dict]:
        """Query a DOM element and return its properties."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return {{
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                classes: [...el.classList],
                text: el.textContent?.slice(0, 200) || '',
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
                rect: {{ x: rect.x, y: rect.y, w: rect.width, h: rect.height }},
                zIndex: style.zIndex,
                pointerEvents: style.pointerEvents,
                opacity: style.opacity,
                display: style.display,
                position: style.position,
                childCount: el.children.length,
                innerHTML_len: el.innerHTML.length,
            }};
        }})()
        """
        return await self.eval_js(js)

    async def query_selector_all(self, selector: str, limit: int = 50) -> List[Dict]:
        """Query all matching elements and return basic info."""
        js = f"""
        (() => {{
            const els = document.querySelectorAll({json.dumps(selector)});
            return [...els].slice(0, {limit}).map(el => {{
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return {{
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    classes: [...el.classList].join(' '),
                    visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
                    rect: {{ x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }},
                    zIndex: style.zIndex,
                    pointerEvents: style.pointerEvents,
                    text: el.textContent?.slice(0, 100) || '',
                }};
            }});
        }})()
        """
        return await self.eval_js(js) or []

    async def get_dom_stats(self) -> Dict[str, Any]:
        """Get DOM statistics for the page."""
        js = """
        (() => {
            const all = document.querySelectorAll('*');
            const visible = [...all].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            });
            return {
                total_elements: all.length,
                visible_elements: visible.length,
                scripts: document.querySelectorAll('script').length,
                stylesheets: document.querySelectorAll('link[rel=stylesheet]').length,
                images: document.querySelectorAll('img').length,
                canvases: document.querySelectorAll('canvas').length,
                iframes: document.querySelectorAll('iframe').length,
                forms: document.querySelectorAll('form').length,
                buttons: document.querySelectorAll('button').length,
                inputs: document.querySelectorAll('input, textarea, select').length,
                event_listeners_count: typeof getEventListeners === 'function' ? 'available' : 'unavailable',
                body_classes: document.body?.className || '',
                document_ready_state: document.readyState,
            };
        })()
        """
        return await self.eval_js(js) or {}

    async def get_element_at_point(self, x: int, y: int) -> Optional[Dict]:
        """Get the topmost element at screen coordinates."""
        js = f"""
        (() => {{
            const el = document.elementFromPoint({x}, {y});
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return {{
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                classes: [...el.classList],
                text: el.textContent?.slice(0, 100) || '',
                zIndex: style.zIndex,
                pointerEvents: style.pointerEvents,
                rect: {{ x: rect.x, y: rect.y, w: rect.width, h: rect.height }},
            }};
        }})()
        """
        return await self.eval_js(js)

    async def check_z_index_stack(self) -> List[Dict]:
        """Get all positioned elements with explicit z-index values, sorted."""
        js = """
        (() => {
            const all = document.querySelectorAll('*');
            const stacked = [];
            for (const el of all) {
                const style = getComputedStyle(el);
                const z = parseInt(style.zIndex);
                if (!isNaN(z) && style.position !== 'static') {
                    const rect = el.getBoundingClientRect();
                    stacked.push({
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        classes: [...el.classList].join(' '),
                        zIndex: z,
                        position: style.position,
                        pointerEvents: style.pointerEvents,
                        display: style.display,
                        visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                    });
                }
            }
            return stacked.sort((a, b) => b.zIndex - a.zIndex);
        })()
        """
        return await self.eval_js(js) or []

    # ── Page Interaction ─────────────────────────────────────────────

    async def click(self, selector: str) -> bool:
        """Click an element by CSS selector."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.click();
            return true;
        }})()
        """
        return await self.eval_js(js) or False

    async def click_at(self, x: int, y: int) -> None:
        """Dispatch a click at specific coordinates via CDP Input domain."""
        session = self._ensure_connected()
        for event_type in ("mousePressed", "mouseReleased"):
            await session.send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })

    async def type_text(self, selector: str, text: str) -> bool:
        """Focus an element and type text into it."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.focus();
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }})()
        """
        return await self.eval_js(js) or False

    async def scroll_to(self, selector: str) -> bool:
        """Scroll an element into view."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            return true;
        }})()
        """
        return await self.eval_js(js) or False

    async def navigate(self, url: str) -> None:
        """Navigate the tab to a new URL."""
        session = self._ensure_connected()
        await session.send("Page.navigate", {"url": url})

    async def reload(self) -> None:
        """Reload the current page."""
        session = self._ensure_connected()
        await session.send("Page.reload", {"ignoreCache": True})

    # ── Screenshot + Vision ──────────────────────────────────────────

    async def take_screenshot(
        self,
        save_path: Optional[str] = None,
        full_page: bool = False,
    ) -> str:
        """Take a PNG screenshot and return the file path.

        Args:
            save_path: Where to save. Defaults to data/argus/screenshots/
            full_page: Capture the full scrollable page

        Returns:
            Path to the saved screenshot file
        """
        session = self._ensure_connected()
        params: Dict[str, Any] = {"format": "png", "quality": 90}
        if full_page:
            metrics = await session.send("Page.getLayoutMetrics")
            content = metrics.get("result", metrics).get("contentSize", {})
            if content:
                params["clip"] = {
                    "x": 0, "y": 0,
                    "width": content.get("width", 1920),
                    "height": content.get("height", 1080),
                    "scale": 1,
                }

        result = await session.send("Page.captureScreenshot", params)
        b64_data = result.get("result", result).get("data", "")
        if not b64_data:
            raise RuntimeError("Screenshot capture returned empty data")

        if not save_path:
            screenshot_dir = Path("data/argus/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            save_path = str(screenshot_dir / f"debug_{ts}.png")

        with open(save_path, "wb") as f:
            f.write(base64.b64decode(b64_data))

        logger.info("Screenshot saved: %s", save_path)
        return save_path

    async def get_screenshot_base64(self) -> str:
        """Take a screenshot and return raw base64 PNG data."""
        session = self._ensure_connected()
        result = await session.send("Page.captureScreenshot", {"format": "png"})
        return result.get("result", result).get("data", "")

    async def vision_analyze(
        self,
        question: str = "Describe what you see on this page. Note any visual issues.",
        model: Optional[str] = None,
    ) -> str:
        """Take a screenshot and analyze it with LMStudio vision model.

        Args:
            question: What to ask the vision model about the screenshot
            model: Vision model to use (default from config)

        Returns:
            The vision model's analysis text
        """
        b64 = await self.get_screenshot_base64()
        if not b64:
            return "ERROR: Failed to capture screenshot"

        data_url = f"data:image/png;base64,{b64}"

        try:
            from engine.lmstudio.lms_client import get_lms_client
            client = get_lms_client()
        except Exception as exc:
            return f"ERROR: Cannot connect to LMStudio: {exc}"

        if not model:
            try:
                from engine.config import get_config
                model = get_config().get("lmstudio.models.vision", "qwen/qwen3-vl-4b")
            except Exception:
                model = "qwen/qwen3-vl-4b"

        try:
            response = client.chat(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
                max_tokens=1000,
            )
            return response.get("choices", [{}])[0].get("message", {}).get("content", "No response")
        except Exception as exc:
            return f"ERROR: Vision analysis failed: {exc}"

    # ── Performance Metrics ──────────────────────────────────────────

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get Chrome performance metrics."""
        session = self._ensure_connected()
        try:
            result = await session.send("Performance.getMetrics")
            metrics = {}
            for m in result.get("result", result).get("metrics", []):
                metrics[m["name"]] = m["value"]
            return metrics
        except Exception:
            return {}

    async def get_memory_info(self) -> Dict[str, Any]:
        """Get JavaScript heap memory usage."""
        js = """
        (() => {
            if (performance.memory) {
                return {
                    used_heap_mb: Math.round(performance.memory.usedJSHeapSize / 1048576),
                    total_heap_mb: Math.round(performance.memory.totalJSHeapSize / 1048576),
                    heap_limit_mb: Math.round(performance.memory.jsHeapSizeLimit / 1048576),
                };
            }
            return { note: 'performance.memory not available (non-Chromium or flag missing)' };
        })()
        """
        return await self.eval_js(js) or {}

    async def get_fps_estimate(self, duration_ms: int = 1000) -> float:
        """Estimate current FPS by counting animation frames."""
        js = f"""
        new Promise(resolve => {{
            let count = 0;
            const start = performance.now();
            function tick() {{
                count++;
                if (performance.now() - start < {duration_ms}) {{
                    requestAnimationFrame(tick);
                }} else {{
                    resolve(count / ((performance.now() - start) / 1000));
                }}
            }}
            requestAnimationFrame(tick);
        }})
        """
        session = self._ensure_connected()
        result = await session.send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
            "awaitPromise": True,
        })
        value = result.get("result", {}).get("result", {}).get("value", 0)
        return round(value, 1) if value else 0.0

    # ── Scene-Specific Diagnostics ───────────────────────────────────

    async def check_scene_health(self) -> Dict[str, bool]:
        """Check CosySim-specific scene health indicators."""
        checks = {}

        # Socket.IO connected
        r = await self.eval_js_safe("typeof io !== 'undefined' && io.connected !== undefined")
        checks["socketio_loaded"] = r.get("ok", False) and r.get("value") is not None

        r = await self.eval_js_safe("""
            (() => {
                if (typeof PENTHOUSE !== 'undefined' && PENTHOUSE.socket) return PENTHOUSE.socket.connected;
                if (typeof io !== 'undefined') {
                    const m = io.managers || {};
                    return Object.values(m).some(mgr => mgr.engine && mgr.engine.readyState === 'open');
                }
                return false;
            })()
        """)
        checks["socket_connected"] = r.get("value", False) is True

        # Three.js loaded
        r = await self.eval_js_safe("typeof THREE !== 'undefined'")
        checks["threejs_loaded"] = r.get("value", False) is True

        # 3D canvas visible
        r = await self.eval_js_safe("""
            (() => {
                const c = document.querySelector('canvas');
                if (!c) return false;
                const r = c.getBoundingClientRect();
                return r.width > 100 && r.height > 100;
            })()
        """)
        checks["canvas_visible"] = r.get("value", False) is True

        # Scene-specific objects
        for name in ["penthouse3D", "lab3D", "PENTHOUSE", "LabBreak"]:
            r = await self.eval_js_safe(f"typeof window.{name} !== 'undefined'")
            if r.get("value", False) is True:
                checks[f"{name}_initialized"] = True

        # Content gate dismissed
        r = await self.eval_js_safe("""
            (() => {
                const gate = document.getElementById('penthouse-gate');
                return !gate || gate.hidden || gate.style.display === 'none';
            })()
        """)
        checks["content_gate_clear"] = r.get("value", False) is True

        # Director panel exists
        r = await self.eval_js_safe("document.getElementById('ph-director-panel') !== null")
        checks["director_panel_exists"] = r.get("value", False) is True

        # Chat dock exists
        r = await self.eval_js_safe("document.getElementById('ph-chat-dock') !== null")
        checks["chat_dock_exists"] = r.get("value", False) is True

        # No blocking overlays
        r = await self.eval_js_safe("""
            (() => {
                const center = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
                if (!center) return true;
                const style = getComputedStyle(center);
                const z = parseInt(style.zIndex) || 0;
                return z < 9000;
            })()
        """)
        checks["no_blocking_overlay"] = r.get("value", False) is True

        return checks

    async def check_click_targets(self, selectors: List[str]) -> Dict[str, Dict]:
        """Check if specific elements are clickable (not blocked by overlays)."""
        results = {}
        for sel in selectors:
            info = await self.query_selector(sel)
            if not info:
                results[sel] = {"exists": False, "clickable": False, "reason": "not found"}
                continue

            blocked = False
            reason = ""
            if not info.get("visible"):
                blocked = True
                reason = "not visible"
            elif info.get("pointerEvents") == "none":
                blocked = True
                reason = "pointer-events: none"
            elif info.get("display") == "none":
                blocked = True
                reason = "display: none"
            else:
                rect = info.get("rect", {})
                cx = int(rect.get("x", 0) + rect.get("w", 0) / 2)
                cy = int(rect.get("y", 0) + rect.get("h", 0) / 2)
                top_el = await self.get_element_at_point(cx, cy)
                if top_el and top_el.get("id") != info.get("id"):
                    top_z = int(top_el.get("zIndex") or 0)
                    el_z = int(info.get("zIndex") or 0)
                    if top_z > el_z:
                        blocked = True
                        reason = f"blocked by #{top_el.get('id', '?')} (z-index {top_z})"

            results[sel] = {
                "exists": True,
                "visible": info.get("visible", False),
                "clickable": not blocked,
                "reason": reason or "ok",
                "zIndex": info.get("zIndex"),
                "rect": info.get("rect"),
            }
        return results

    # ── Full Diagnostic Report ───────────────────────────────────────

    async def diagnose_scene(
        self,
        include_vision: bool = False,
        vision_question: str = "Describe any visual issues, broken layouts, or missing elements.",
    ) -> DiagnosticReport:
        """Generate a complete diagnostic report for the current page.

        Args:
            include_vision: Also take a screenshot and analyze with vision model
            vision_question: What to ask the vision model

        Returns:
            DiagnosticReport with all captured data
        """
        title = await self.eval_js("document.title") or "Unknown"
        url = await self.eval_js("window.location.href") or "Unknown"

        # Gather all diagnostics
        dom_stats = await self.get_dom_stats()
        scene_health = await self.check_scene_health()

        # Performance
        perf = {}
        try:
            mem = await self.get_memory_info()
            perf.update(mem)
        except Exception:
            pass

        try:
            fps = await self.get_fps_estimate(500)
            perf["fps"] = fps
        except Exception:
            pass

        # Optional vision
        screenshot_path = None
        vision_analysis = None
        if include_vision:
            try:
                screenshot_path = await self.take_screenshot()
                vision_analysis = await self.vision_analyze(vision_question)
            except Exception as exc:
                vision_analysis = f"Vision failed: {exc}"

        return DiagnosticReport(
            url=url,
            title=title,
            timestamp=time.time(),
            console_errors=self.get_errors(),
            console_warnings=self.get_warnings(),
            network_errors=self.get_network_errors(),
            js_exceptions=self.get_exceptions(),
            dom_stats=dom_stats,
            performance=perf,
            scene_health=scene_health,
            screenshot_path=screenshot_path,
            vision_analysis=vision_analysis,
        )

    # ── Watch Mode ───────────────────────────────────────────────────

    async def watch(
        self,
        duration_seconds: float = 30,
        on_error: Optional[Callable[[str], None]] = None,
        on_network_error: Optional[Callable[[NetworkEntry], None]] = None,
    ) -> DiagnosticReport:
        """Watch the page for a duration, collecting all errors.

        Args:
            duration_seconds: How long to monitor
            on_error: Callback for each console error
            on_network_error: Callback for each network error

        Returns:
            DiagnosticReport after the watch period
        """
        self.clear_console()
        self.clear_network()
        self._js_exceptions.clear()

        start = time.time()
        prev_errors = 0
        prev_net_errors = 0

        while time.time() - start < duration_seconds:
            await asyncio.sleep(0.5)

            errors = self.get_errors()
            if len(errors) > prev_errors:
                for e in errors[prev_errors:]:
                    if on_error:
                        on_error(str(e))
                prev_errors = len(errors)

            net_errors = self.get_network_errors()
            if len(net_errors) > prev_net_errors:
                for e in net_errors[prev_net_errors:]:
                    if on_network_error:
                        on_network_error(e)
                prev_net_errors = len(net_errors)

        return await self.diagnose_scene()

    # ── Utility ──────────────────────────────────────────────────────

    async def wait_for_element(
        self,
        selector: str,
        timeout: float = 10.0,
        interval: float = 0.3,
    ) -> bool:
        """Wait for an element to appear in the DOM."""
        start = time.time()
        while time.time() - start < timeout:
            result = await self.eval_js_safe(
                f"document.querySelector({json.dumps(selector)}) !== null"
            )
            if result.get("value") is True:
                return True
            await asyncio.sleep(interval)
        return False

    async def wait_for_network_idle(
        self,
        timeout: float = 10.0,
        idle_time: float = 1.0,
    ) -> bool:
        """Wait until no network requests for idle_time seconds."""
        start = time.time()
        last_count = len(self._network_log)
        idle_start = time.time()

        while time.time() - start < timeout:
            await asyncio.sleep(0.3)
            current = len(self._network_log)
            if current != last_count:
                last_count = current
                idle_start = time.time()
            elif time.time() - idle_start >= idle_time:
                return True
        return False

    def get_tab_info(self) -> Dict[str, Any]:
        """Return info about the connected tab."""
        return dict(self._tab_info)

    @staticmethod
    def list_tabs() -> List[Dict[str, str]]:
        """List all Chrome tabs available for debugging."""
        bridge = CDPBridge()
        tabs = bridge.get_tabs()
        return [{"url": t.get("url", "?"), "title": t.get("title", "?"), "id": t.get("id", "?")} for t in tabs]


# ── Convenience Functions ────────────────────────────────────────────

async def quick_diagnose(target: str, include_vision: bool = False) -> str:
    """One-shot scene diagnostic — connect, diagnose, disconnect.

    Args:
        target: URL fragment to find the tab (e.g. "localhost:5556")
        include_vision: Include vision model screenshot analysis

    Returns:
        Formatted diagnostic report string
    """
    async with LiveDebugger(target) as dbg:
        await asyncio.sleep(2)  # Let some events accumulate
        report = await dbg.diagnose_scene(include_vision=include_vision)
        return report.summary()


async def quick_watch(target: str, seconds: float = 15) -> str:
    """Watch a scene for errors over a time period.

    Args:
        target: URL fragment
        seconds: How long to watch

    Returns:
        Formatted diagnostic report string
    """
    async with LiveDebugger(target) as dbg:
        report = await dbg.watch(
            duration_seconds=seconds,
            on_error=lambda e: logger.warning("LIVE: %s", e),
        )
        return report.summary()


def diagnose_sync(target: str, include_vision: bool = False) -> str:
    """Synchronous wrapper for quick_diagnose."""
    return asyncio.run(quick_diagnose(target, include_vision))


def watch_sync(target: str, seconds: float = 15) -> str:
    """Synchronous wrapper for quick_watch."""
    return asyncio.run(quick_watch(target, seconds))
