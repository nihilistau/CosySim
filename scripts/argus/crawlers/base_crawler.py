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
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def get_or_open_page(self, url_fragment: str, fallback_url: str) -> Page:
        """Find an existing tab matching url_fragment, or open fallback_url."""
        for page in self._context.pages:
            if url_fragment in page.url:
                self._page = page
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
            await self._page.wait_for_load_state("networkidle",
                                                  timeout=NAV_TIMEOUT_MS)
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
        await self._page.screenshot(path=str(path), full_page=True)
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
