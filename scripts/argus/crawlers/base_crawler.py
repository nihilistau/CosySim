"""ARGUS base Playwright crawler — attach to running Chrome and drive navigation.

Connects to the running Chrome instance via CDP (connect_over_cdp),
wraps Playwright page interaction, and integrates with the NetworkMonitor
so every crawl step automatically captures traffic.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from scripts.argus.config import (
    ACTION_TIMEOUT_MS,
    CDP_URL,
    NAV_TIMEOUT_MS,
    NETWORK_IDLE_MS,
    REPORTS_DIR,
)
from scripts.argus.network_monitor import CapturedRequest, NetworkMonitor

logger = logging.getLogger(__name__)


class CrawlStep:
    """Result of a single crawl action."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.traffic: List[CapturedRequest] = []
        self.screenshot_path: Optional[Path] = None
        self.error: Optional[str] = None
        self.notes: List[str] = []

    def finish(self) -> "CrawlStep":
        self.finished_at = time.time()
        return self

    @property
    def duration_ms(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return 0.0

    @property
    def ok(self) -> bool:
        return self.error is None

    def note(self, msg: str) -> None:
        self.notes.append(msg)
        logger.debug("[%s] %s", self.name, msg)


class BaseCrawler:
    """Playwright crawler that attaches to the running Chrome instance.

    Subclass this for each target (NLM, Gemini, AI Studio) and
    override `run_flows()` to define the crawl sequence.
    """

    name: str = "base"
    target_domain: str = ""

    def __init__(self, monitor: Optional[NetworkMonitor] = None) -> None:
        self._monitor = monitor
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._steps: List[CrawlStep] = []

    @property
    def context(self) -> Optional[BrowserContext]:
        """The active Playwright BrowserContext (available after start())."""
        return self._context

    # ──── Lifecycle ────

    async def start(self) -> "BaseCrawler":
        """Launch Playwright and attach to the running Chrome via CDP."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
        # Use the existing default context (preserves cookies / login state)
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = await self._browser.new_context()
        logger.info("ARGUS %s crawler attached to Chrome", self.name)
        return self

    async def stop(self) -> None:
        """Detach from Chrome (does NOT close the browser)."""
        # Don't close pages/contexts — that would close the user's browser
        if self._playwright:
            await self._playwright.stop()
        logger.info("ARGUS %s crawler detached", self.name)

    async def __aenter__(self) -> "BaseCrawler":
        return await self.start()

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    # ──── Page management ────

    async def open_page(self, url: str) -> Page:
        """Open a new page (tab) at the given URL."""
        page = await self._context.new_page()
        self._page = page
        page.set_default_timeout(ACTION_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        if self._monitor:
            await self._monitor.attach_playwright_page(page)
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(0.3)
        if self._monitor:
            await self._monitor.attach_to_new_tabs()
        return page

    async def get_or_open_page(
        self,
        url_fragment: str,
        fallback_url: str,
        reload: bool = False,
    ) -> Page:
        """Find an existing tab matching url_fragment, or open fallback_url.

        Args:
            url_fragment: Substring to match in the existing tab URL.
            fallback_url: URL to open if no matching tab is found.
            reload:       If True and an existing tab is found, reload it so that
                          fresh network traffic is captured by the monitor.
        """
        _error_suffixes = ("/404", "/error", "/not-found", "/notfound", "?error=")
        for page in self._context.pages:
            if url_fragment in page.url:
                # Skip error/404 pages — navigate to the correct URL instead
                if any(page.url.endswith(s) or s in page.url for s in _error_suffixes):
                    logger.info(
                        "%s: skipping error page %s, navigating to %s",
                        self.name, page.url[:80], fallback_url,
                    )
                    self._page = page
                    if self._monitor:
                        await self._monitor.attach_playwright_page(page)
                    await page.goto(fallback_url, wait_until="domcontentloaded")
                    await asyncio.sleep(1.5)
                    return page
                self._page = page
                if self._monitor:
                    await self._monitor.attach_playwright_page(page)
                if reload:
                    logger.info("%s: reloading existing tab %s", self.name, page.url[:80])
                    await page.reload(wait_until="domcontentloaded")
                    await asyncio.sleep(1.5)
                return page
        return await self.open_page(fallback_url)

    async def close_extra_pages(self) -> None:
        """Close all pages except the first (cleanup after crawl)."""
        pages = self._context.pages
        for page in pages[1:]:
            try:
                await page.close()
            except Exception:
                pass

    # ──── Navigation helpers ────

    async def navigate(self, url: str, wait: str = "domcontentloaded") -> None:
        """Navigate to URL and wait for network idle."""
        assert self._page, "No page open — call open_page() first"
        await self._page.goto(url, wait_until=wait)
        await self._wait_network_idle()

    async def _wait_network_idle(self, timeout: int = NETWORK_IDLE_MS) -> None:
        """Wait for network activity to settle."""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            # networkidle can time out on SPAs — that's OK
            await asyncio.sleep(timeout / 1000)

    # ──── Action helpers ────

    async def click(self, selector: str, timeout: int = ACTION_TIMEOUT_MS) -> None:
        await self._page.click(selector, timeout=timeout)
        await asyncio.sleep(0.3)

    async def fill(self, selector: str, text: str) -> None:
        await self._page.fill(selector, text)

    async def press_enter(self, selector: str) -> None:
        await self._page.press(selector, "Enter")

    async def wait_for_selector(self, selector: str,
                                 timeout: int = ACTION_TIMEOUT_MS) -> None:
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def scroll_to_bottom(self) -> None:
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)

    # ──── Screenshot ────

    async def screenshot(self, label: str) -> Path:
        path = REPORTS_DIR / f"{self.name}_{label}_{int(time.time())}.png"
        await self._page.screenshot(path=str(path), full_page=False, timeout=5_000)
        logger.debug("Screenshot: %s", path)
        return path

    # ──── Step execution with traffic capture ────

    async def step(
        self,
        name: str,
        action: Callable,
        capture_traffic: bool = True,
    ) -> CrawlStep:
        """Execute an action as a named crawl step, capturing traffic.

        Args:
            name:             Human-readable step name.
            action:           Async callable to execute.
            capture_traffic:  Whether to drain NetworkMonitor after the action.

        Returns:
            CrawlStep with traffic and timing.
        """
        s = CrawlStep(name)
        logger.info("ARGUS %s: step [%s]", self.name, name)
        try:
            await action()
            await asyncio.sleep(0.5)  # Let network activity settle
            if capture_traffic and self._monitor:
                s.traffic = await self._monitor.drain()
                s.note(f"captured {len(s.traffic)} requests "
                       f"({sum(1 for r in s.traffic if r.is_batchexecute)} batchexecute, "
                       f"{sum(1 for r in s.traffic if r.is_grpc_web)} gRPC-web)")
            try:
                s.screenshot_path = await self.screenshot(name.replace(" ", "_"))
            except Exception:
                pass
        except Exception as exc:
            s.error = str(exc)
            logger.warning("ARGUS %s: step [%s] failed: %s", self.name, name, exc)
        self._steps.append(s.finish())
        return s

    # ──── JS evaluation helpers ────

    async def get_window_globals(self) -> Dict[str, Any]:
        """Extract interesting global variables from the page."""
        try:
            return await self._page.evaluate("""() => {
                const interesting = {};
                const keys = Object.keys(window).filter(k =>
                    k.includes('Config') || k.includes('config') ||
                    k.includes('Flag') || k.includes('flag') ||
                    k.includes('Feature') || k.includes('feature') ||
                    k.includes('API') || k.includes('api') ||
                    k.startsWith('__') || k.includes('google')
                );
                for (const k of keys.slice(0, 50)) {
                    try { interesting[k] = JSON.stringify(window[k]).slice(0, 500); }
                    catch (e) { interesting[k] = String(window[k]).slice(0, 200); }
                }
                return interesting;
            }""")
        except Exception:
            return {}

    async def get_angular_services(self) -> List[str]:
        """Try to enumerate Angular injected service names from the page."""
        try:
            return await self._page.evaluate("""() => {
                try {
                    const el = document.querySelector('[ng-version]') ||
                               document.querySelector('app-root') ||
                               document.body;
                    const injector = window.ng?.getInjector?.(el);
                    if (!injector) return [];
                    return Object.keys(injector._def?.providers || {}).slice(0, 100);
                } catch(e) { return []; }
            }""")
        except Exception:
            return []

    # ──── JS injection helpers ────

    async def inject_fetch(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fire a fetch() from within the page context so NetworkMonitor captures it.

        Because this runs as page JS, the browser's own cookies/auth are used.
        The Playwright page listener captures the resulting request.

        Args:
            url:     Full or relative URL to fetch.
            method:  HTTP method (default POST).
            headers: Optional extra headers dict.
            body:    Optional request body string.

        Returns:
            Dict with status and responseText, or None on error.
        """
        headers = headers or {}
        js = f"""
        async () => {{
            try {{
                const resp = await fetch({url!r}, {{
                    method: {method!r},
                    headers: {headers!r},
                    body: {body!r},
                    credentials: 'include',
                }});
                const text = await resp.text();
                return {{ status: resp.status, body: text.slice(0, 2000) }};
            }} catch(e) {{
                return {{ status: -1, error: String(e) }};
            }}
        }}"""
        try:
            return await self._page.evaluate(js)
        except Exception as exc:
            logger.debug("%s: inject_fetch failed: %s", self.name, exc)
            return None

    async def dump_dom_info(self, label: str = "") -> Dict[str, Any]:
        """Extract visible interactive elements for selector debugging.

        Returns a dict with buttons, inputs, links, and aria-labels found.
        Useful for diagnosing selector failures.
        """
        try:
            info = await self._page.evaluate("""() => {
                const sel = (s) => [...document.querySelectorAll(s)]
                    .map(e => ({
                        tag: e.tagName,
                        text: (e.innerText || e.textContent || '').trim().slice(0, 80),
                        label: e.getAttribute('aria-label') || '',
                        role: e.getAttribute('role') || '',
                        id: e.id || '',
                        cls: e.className.toString().slice(0, 60),
                        href: e.href || '',
                        placeholder: e.placeholder || '',
                        testid: e.getAttribute('data-testid') || '',
                    }));
                return {
                    buttons: sel('button, [role=button]').slice(0, 30),
                    inputs: sel('input, textarea, [contenteditable=true]').slice(0, 15),
                    links: sel('a[href]').slice(0, 20),
                    url: window.location.href,
                };
            }""")
            prefix = f"{self.name}[{label}]" if label else self.name
            logger.info("%s dom: %d buttons, %d inputs, %d links at %s",
                        prefix, len(info.get("buttons", [])), len(info.get("inputs", [])),
                        len(info.get("links", [])), info.get("url", "?"))
            logger.debug("%s dom dump: %s", prefix, info)
            return info
        except Exception as exc:
            logger.debug("%s: dump_dom_info failed: %s", self.name, exc)
            return {}

    async def find_element_by_text(self, *texts: str, timeout: int = 5_000) -> Any:
        """Find the first clickable element whose visible text contains any of *texts.

        Uses Playwright's locator API for robustness. Returns None if nothing found.
        """
        for text in texts:
            try:
                loc = self._page.get_by_text(text, exact=False)
                el = loc.first
                await el.wait_for(state="visible", timeout=timeout)
                return el
            except Exception:
                pass
        return None

    async def find_button(self, *labels: str, timeout: int = 5_000) -> Any:
        """Find the first button matching any of the given aria-labels or visible text."""
        for label in labels:
            # Try aria-label first (most reliable)
            try:
                loc = self._page.get_by_role("button", name=label)
                el = loc.first
                await el.wait_for(state="visible", timeout=timeout)
                return el
            except Exception:
                pass
            # Fallback to text match
            try:
                loc = self._page.locator(f"button:has-text('{label}')")
                el = loc.first
                await el.wait_for(state="visible", timeout=timeout)
                return el
            except Exception:
                pass
        return None

    # ──── Subclass interface ────

    async def run_flows(self) -> List[CrawlStep]:
        """Override in subclass to define the full crawl sequence."""
        raise NotImplementedError(f"{self.__class__.__name__}.run_flows() not implemented")

    async def run(self) -> List[CrawlStep]:
        """Full run: start → run_flows → stop → return steps."""
        async with self:
            steps = await self.run_flows()
        return steps

    @property
    def steps(self) -> List[CrawlStep]:
        return self._steps

    @property
    def all_traffic(self) -> List[CapturedRequest]:
        """Flatten all captured traffic across all steps."""
        result: List[CapturedRequest] = []
        for s in self._steps:
            result.extend(s.traffic)
        return result
