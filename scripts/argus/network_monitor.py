"""ARGUS Network Monitor — real-time CDP traffic capture and buffering.

Attaches to all open Chrome tabs, enables the Network domain, and streams
every request/response pair into an in-memory buffer. Callers can drain the
buffer at any time to get all traffic since the last drain.

Designed to wrap Playwright crawl steps:
    monitor = NetworkMonitor()
    await monitor.start()
    # ... playwright does things ...
    traffic = await monitor.drain()   # get everything that happened
    await monitor.stop()

Playwright-native capture is preferred over CDP-bridge when a page object
is available:
    await monitor.attach_playwright_page(page)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

from scripts.argus.cdp_bridge import CDPBridge, CDPSession

logger = logging.getLogger(__name__)


@dataclass
class CapturedRequest:
    """A single request/response pair captured from CDP Network events."""

    request_id: str
    url: str
    method: str
    headers: Dict[str, str]
    post_data: Optional[str]
    timestamp: float
    response_status: Optional[int] = None
    response_headers: Optional[Dict[str, str]] = None
    response_body: Optional[str] = None
    response_mime: Optional[str] = None
    finished_at: Optional[float] = None
    tab_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.timestamp and self.finished_at:
            return (self.finished_at - self.timestamp) * 1000
        return None

    @property
    def is_batchexecute(self) -> bool:
        return "batchexecute" in self.url

    @property
    def is_grpc_web(self) -> bool:
        return "$rpc/" in self.url or "clients6.google.com" in self.url

    @property
    def is_google_api(self) -> bool:
        return any(d in self.url for d in (
            "notebooklm.google.com",
            "gemini.google.com",
            "aistudio.google.com",
            "alkalimakersuite-pa.clients6.google.com",
            "generativelanguage.googleapis.com",
            "webchannel-alkalimakersuite",
        ))


class NetworkMonitor:
    """Attaches CDP to all Chrome tabs and buffers captured traffic.

    Usage::

        monitor = NetworkMonitor()
        await monitor.start()

        # Do stuff in Playwright
        captured = await monitor.drain()          # all requests so far
        google_only = monitor.filter_google(captured)

        await monitor.stop()
    """

    def __init__(self, bridge: Optional[CDPBridge] = None) -> None:
        self._bridge = bridge or CDPBridge()
        self._sessions: List[CDPSession] = []
        self._buffer: Deque[CapturedRequest] = deque()
        self._in_flight: Dict[str, CapturedRequest] = {}  # request_id -> partial
        self._lock = asyncio.Lock()
        self._running = False

    # ──── Lifecycle ────

    async def start(self) -> None:
        """Connect to all open tabs and enable network monitoring."""
        if self._running:
            return
        tabs = self._bridge.get_tabs()
        logger.info("ARGUS NetworkMonitor: attaching to %d tabs", len(tabs))
        for tab in tabs:
            try:
                s = await self._bridge.open_session(tab)
                await s.enable_network()
                s.on("Network.requestWillBeSent",
                     lambda p, _s=s: asyncio.create_task(self._on_request(p, _s)))
                s.on("Network.responseReceived",
                     lambda p, _s=s: asyncio.create_task(self._on_response(p, _s)))
                s.on("Network.loadingFinished",
                     lambda p, _s=s: asyncio.create_task(self._on_finished(p, _s)))
                s.on("Network.loadingFailed",
                     lambda p: asyncio.create_task(self._on_failed(p)))
                self._sessions.append(s)
            except Exception as exc:
                logger.warning("Monitor: skip tab %s — %s", tab.get("url", "?")[:50], exc)
        self._running = True

    async def stop(self) -> None:
        """Disable network monitoring and disconnect all sessions."""
        self._running = False
        for s in self._sessions:
            try:
                await s.disable_network()
                await s.disconnect()
            except Exception:
                pass
        self._sessions.clear()
        self._in_flight.clear()

    async def attach_to_new_tabs(self) -> int:
        """Scan for new tabs and attach to any not yet monitored. Returns count added."""
        known_ids = {s.tab_id for s in self._sessions}
        added = 0
        for tab in self._bridge.get_tabs():
            if tab.get("id") not in known_ids:
                try:
                    s = await self._bridge.open_session(tab)
                    await s.enable_network()
                    s.on("Network.requestWillBeSent",
                         lambda p, _s=s: asyncio.create_task(self._on_request(p, _s)))
                    s.on("Network.responseReceived",
                         lambda p, _s=s: asyncio.create_task(self._on_response(p, _s)))
                    s.on("Network.loadingFinished",
                         lambda p, _s=s: asyncio.create_task(self._on_finished(p, _s)))
                    self._sessions.append(s)
                    added += 1
                except Exception as exc:
                    logger.debug("attach_to_new_tabs skip: %s", exc)
        return added

    # ──── Playwright-native page capture ────

    async def attach_playwright_page(self, page: Any) -> None:
        """Register Playwright page-level request/response listeners.

        This is more reliable than CDPBridge for pages opened by Playwright.
        Call this immediately after opening a page or navigating.

        Args:
            page: A Playwright Page object.
        """
        # Track pages we've already wired to avoid double-registration
        if not hasattr(self, "_pw_pages"):
            self._pw_pages: Set[int] = set()
        page_id = id(page)
        if page_id in self._pw_pages:
            return
        self._pw_pages.add(page_id)

        # Track in-flight requests by Playwright Request object identity
        pw_in_flight: Dict[int, CapturedRequest] = {}

        def on_request(request: Any) -> None:
            rid = id(request)
            try:
                post_data = request.post_data
            except Exception:
                # Binary body (e.g. gzip) — fall back to hex string
                try:
                    raw = request.post_data_buffer
                    post_data = raw.hex() if raw else None
                except Exception:
                    post_data = None
            pw_in_flight[rid] = CapturedRequest(
                request_id=str(rid),
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
                post_data=post_data,
                timestamp=time.time(),
                tab_url=page.url,
            )

        async def on_response(response: Any) -> None:
            rid = id(response.request)
            captured = pw_in_flight.get(rid)
            if not captured:
                return
            captured.response_status = response.status
            captured.response_headers = dict(response.headers)
            captured.response_mime = response.headers.get("content-type", "")
            captured.finished_at = time.time()
            # Fetch body for Google API calls
            if captured.is_google_api:
                try:
                    body = await response.body()
                    captured.response_body = body.decode("utf-8", errors="replace")
                except Exception:
                    pass
            pw_in_flight.pop(rid, None)
            async with self._lock:
                self._buffer.append(captured)
            if captured.is_google_api:
                logger.debug(
                    "ARGUS capture: %s %s [%s]",
                    captured.method, captured.url[:80], captured.response_status
                )

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        logger.debug("NetworkMonitor: wired Playwright capture to page %s", page.url[:60])



    async def drain(self, google_only: bool = True) -> List[CapturedRequest]:
        """Return and clear all buffered requests since the last drain.

        Args:
            google_only: If True, only return requests to Google APIs.
        """
        async with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
        if google_only:
            items = [r for r in items if r.is_google_api]
        return items

    async def peek(self, google_only: bool = True) -> List[CapturedRequest]:
        """Return buffered requests WITHOUT clearing the buffer."""
        async with self._lock:
            items = list(self._buffer)
        if google_only:
            items = [r for r in items if r.is_google_api]
        return items

    def buffer_size(self) -> int:
        return len(self._buffer)

    # ──── Filtering helpers ────

    @staticmethod
    def filter_batchexecute(requests: List[CapturedRequest]) -> List[CapturedRequest]:
        return [r for r in requests if r.is_batchexecute]

    @staticmethod
    def filter_grpc(requests: List[CapturedRequest]) -> List[CapturedRequest]:
        return [r for r in requests if r.is_grpc_web]

    @staticmethod
    def filter_google(requests: List[CapturedRequest]) -> List[CapturedRequest]:
        return [r for r in requests if r.is_google_api]

    # ──── CDP event handlers ────

    async def _on_request(self, params: Dict, session: CDPSession) -> None:
        req = params.get("request", {})
        url = req.get("url", "")
        request_id = params.get("requestId", "")
        captured = CapturedRequest(
            request_id=request_id,
            url=url,
            method=req.get("method", "GET"),
            headers=req.get("headers", {}),
            post_data=req.get("postData"),
            timestamp=params.get("timestamp", time.time()),
            tab_url=session.tab_url,
        )
        async with self._lock:
            self._in_flight[request_id] = captured

    async def _on_response(self, params: Dict, session: CDPSession) -> None:
        request_id = params.get("requestId", "")
        resp = params.get("response", {})
        async with self._lock:
            req = self._in_flight.get(request_id)
            if req:
                req.response_status = resp.get("status")
                req.response_headers = resp.get("headers", {})
                req.response_mime = resp.get("mimeType")

    async def _on_finished(self, params: Dict, session: CDPSession) -> None:
        request_id = params.get("requestId", "")
        async with self._lock:
            req = self._in_flight.pop(request_id, None)
        if req:
            req.finished_at = params.get("timestamp", time.time())
            # Fetch body for Google API calls
            if req.is_google_api and req.response_status == 200:
                try:
                    body = await session.get_response_body(request_id)
                    req.response_body = body
                except Exception:
                    pass
            async with self._lock:
                self._buffer.append(req)

    async def _on_failed(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        async with self._lock:
            req = self._in_flight.pop(request_id, None)
            if req:
                req.extra["error"] = params.get("errorText", "failed")
                self._buffer.append(req)
