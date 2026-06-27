"""ARGUS CDP Bridge — async WebSocket client to Chrome DevTools Protocol.

Connects to a running Chrome instance on :9223 and provides:
- Tab enumeration and selection
- Domain enable/disable (Network, Runtime, HeapProfiler, Debugger)
- Event subscription and dispatch
- Command execution with response awaiting
- Heap snapshot capture

Version: v1.63.1 [2026-06-17]
Author:  CosySim Team

Change Log:
    v1.63.1 [2026-06-17] — Fix CDPSession.evaluate() result over-nesting
                            (always returned None) + exceptionDetails check;
                            found via live CDP test against app.sesame.com
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

import websockets

from scripts.argus.config import CDP_URL

logger = logging.getLogger(__name__)


class CDPSession:
    """A single CDP session connected to one browser tab."""

    def __init__(self, ws_url: str, tab_info: Dict[str, Any]) -> None:
        self.ws_url = ws_url
        self.tab_info = tab_info
        self.tab_id = tab_info.get("id", "unknown")
        self.tab_url = tab_info.get("url", "")
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._cmd_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._recv_task: Optional[asyncio.Task] = None

    # ──── Connection lifecycle ────

    async def connect(self) -> "CDPSession":
        """Open the WebSocket connection and start the receive loop."""
        self._ws = await websockets.connect(
            self.ws_url,
            max_size=100 * 1024 * 1024,   # 100 MB — heap snapshots are large
            ping_interval=20,
            ping_timeout=30,
        )
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.debug("CDP connected to tab %s (%s)", self.tab_id[:8], self.tab_url[:60])
        return self

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()
        self._ws = None
        logger.debug("CDP disconnected from tab %s", self.tab_id[:8])

    async def __aenter__(self) -> "CDPSession":
        return await self.connect()

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    # ──── Command execution ────

    async def send(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a CDP command and wait for its response."""
        if not self._ws:
            raise RuntimeError("CDPSession not connected")
        self._cmd_id += 1
        cmd_id = self._cmd_id
        msg = {"id": cmd_id, "method": method, "params": params or {}}
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = future
        await self._ws.send(json.dumps(msg))
        try:
            result = await asyncio.wait_for(future, timeout=60.0)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            raise TimeoutError(f"CDP command {method} timed out")

    # ──── Event subscriptions ────

    def on(self, event: str, callback: Callable[[Dict], Any]) -> None:
        """Subscribe to a CDP event by name (e.g. 'Network.requestWillBeSent')."""
        self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable[[Dict], Any]) -> None:
        """Unsubscribe a previously registered callback."""
        self._listeners[event] = [
            cb for cb in self._listeners[event] if cb is not callback
        ]

    # ──── Domain helpers ────

    async def enable_network(self, max_body_size: int = 10 * 1024 * 1024) -> None:
        await self.send("Network.enable", {"maxTotalBufferSize": max_body_size,
                                           "maxResourceBufferSize": max_body_size})

    async def enable_runtime(self) -> None:
        await self.send("Runtime.enable")

    async def enable_debugger(self) -> None:
        await self.send("Debugger.enable")

    async def enable_heap_profiler(self) -> None:
        await self.send("HeapProfiler.enable")

    async def disable_network(self) -> None:
        await self.send("Network.disable")

    # ──── Runtime evaluation ────

    async def evaluate(self, expression: str, return_by_value: bool = True) -> Any:
        """Evaluate JavaScript in the page context."""
        # v1.63.1 [2026-06-17] — send() returns the CDP command result object,
        # i.e. {"result": <RemoteObject>, "exceptionDetails"?: ...}. The value
        # lives at result["result"]["value"] and exceptionDetails is a sibling
        # of "result" — the previous code over-nested by one level (always None)
        # and checked exceptionDetails in the wrong place. Found via live CDP test.
        result = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS eval error: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    # ──── Network helpers ────

    async def get_response_body(self, request_id: str) -> Optional[str]:
        """Retrieve the body of a completed network response."""
        try:
            result = await self.send("Network.getResponseBody", {"requestId": request_id})
            return result.get("result", {}).get("body")
        except Exception:
            return None

    # ──── Heap snapshot ────

    async def take_heap_snapshot(self) -> str:
        """Take a V8 heap snapshot and return the full JSON string."""
        chunks: List[str] = []

        def _on_chunk(params: Dict) -> None:
            chunks.append(params.get("chunk", ""))

        self.on("HeapProfiler.addHeapSnapshotChunk", _on_chunk)
        await self.send("HeapProfiler.takeHeapSnapshot", {"reportProgress": False,
                                                           "captureNumericValue": True,
                                                           "exposeInternals": True})
        self.off("HeapProfiler.addHeapSnapshotChunk", _on_chunk)
        return "".join(chunks)

    # ──── Internal receive loop ────

    async def _recv_loop(self) -> None:
        """Dispatch incoming CDP messages to pending futures or event listeners."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if "id" in msg:
                    # Response to a command
                    future = self._pending.pop(msg["id"], None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(RuntimeError(msg["error"].get("message")))
                        else:
                            future.set_result(msg.get("result", {}))
                elif "method" in msg:
                    # Event notification
                    for cb in self._listeners.get(msg["method"], []):
                        try:
                            result = cb(msg.get("params", {}))
                            if asyncio.iscoroutine(result):
                                asyncio.create_task(result)
                        except Exception as exc:
                            logger.warning("CDP event handler error (%s): %s", msg["method"], exc)
        except websockets.ConnectionClosed:
            logger.debug("CDP WebSocket closed for tab %s", self.tab_id[:8])
        except Exception as exc:
            logger.error("CDP recv loop error: %s", exc)
        finally:
            # Resolve any pending futures with an error
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("CDP connection closed"))
            self._pending.clear()


class CDPBridge:
    """Manages multiple CDPSessions — one per browser tab.

    Usage::

        bridge = CDPBridge()
        await bridge.connect()
        tabs = await bridge.get_tabs()
        async with bridge.session(tabs[0]) as session:
            await session.enable_network()
            ...
        await bridge.disconnect()
    """

    def __init__(self, host: str = "localhost", port: int = 0) -> None:
        if port == 0:
            from scripts.argus.config import CDP_PORT
            port = CDP_PORT
        self._base_url = f"http://{host}:{port}"
        self._sessions: Dict[str, CDPSession] = {}

    # ──── Tab discovery ────

    def get_tabs(self) -> List[Dict[str, Any]]:
        """Return all open tabs from /json endpoint (sync — no Chrome required for this)."""
        try:
            with urllib.request.urlopen(f"{self._base_url}/json", timeout=5) as r:
                tabs = json.loads(r.read())
            return [t for t in tabs if t.get("type") == "page"]
        except Exception as exc:
            raise ConnectionError(
                f"Cannot reach Chrome CDP at {self._base_url} — "
                f"start Chrome with --remote-debugging-port=9223. Error: {exc}"
            ) from exc

    def get_tab_by_url(self, url_fragment: str) -> Optional[Dict[str, Any]]:
        """Find first tab whose URL contains url_fragment."""
        for tab in self.get_tabs():
            if url_fragment in tab.get("url", ""):
                return tab
        return None

    def get_all_tabs_for_domain(self, domain: str) -> List[Dict[str, Any]]:
        """Return all tabs matching a domain substring."""
        return [t for t in self.get_tabs() if domain in t.get("url", "")]

    # ──── Session factory ────

    def session(self, tab: Dict[str, Any]) -> CDPSession:
        """Create a CDPSession for the given tab dict (use as async context manager)."""
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            raise ValueError(f"Tab has no webSocketDebuggerUrl: {tab}")
        return CDPSession(ws_url, tab)

    async def open_session(self, tab: Dict[str, Any]) -> CDPSession:
        """Open and return a connected CDPSession (caller must close)."""
        s = self.session(tab)
        await s.connect()
        self._sessions[s.tab_id] = s
        return s

    async def close_all(self) -> None:
        """Disconnect all open sessions."""
        for s in list(self._sessions.values()):
            await s.disconnect()
        self._sessions.clear()

    # ──── Convenience: enable Network on ALL tabs ────

    async def monitor_all_tabs(
        self,
        on_request: Optional[Callable] = None,
        on_response: Optional[Callable] = None,
    ) -> List[CDPSession]:
        """Enable Network on all open tabs and wire optional callbacks."""
        sessions: List[CDPSession] = []
        for tab in self.get_tabs():
            try:
                s = await self.open_session(tab)
                await s.enable_network()
                if on_request:
                    s.on("Network.requestWillBeSent", on_request)
                if on_response:
                    s.on("Network.responseReceived", on_response)
                sessions.append(s)
            except Exception as exc:
                logger.warning("Failed to attach CDP to tab %s: %s",
                               tab.get("url", "?")[:50], exc)
        return sessions


# ──── Module-level singleton ────
_bridge: Optional[CDPBridge] = None


def get_bridge() -> CDPBridge:
    """Return the module-level CDPBridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = CDPBridge()
    return _bridge
