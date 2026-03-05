"""ARGUS AI Studio crawler — systematic UI flow mapper for aistudio.google.com.

Flows covered:
    1.  Home page load                             → ListPrompts, ListModels
    2.  Open a prompt                              → GetPrompt
    3.  Run generation                             → StreamGenerateContent
    4.  Change model                               → GetModel
    5.  Adjust parameters (temp, top-p, tokens)   → GetModelCapabilities
    6.  System instructions panel                  → (prompt structure)
    7.  Function calling setup                     → (tool config)
    8.  Open applet tab                            → ListApplets
    9.  Open a deployed applet                     → GetApplet
   10.  View deployment URL                        → GetApp
   11.  File manager                               → ListFiles
   12.  Tuning panel                               → ListTunedModels
   13.  Cached content panel                       → ListCachedContents
   14.  API keys / settings                        → (settings page)
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from scripts.argus.config import AISTUDIO_METHODS, TARGETS
from scripts.argus.crawlers.base_crawler import BaseCrawler, CrawlStep
from scripts.argus.network_monitor import NetworkMonitor

logger = logging.getLogger(__name__)

AISTUDIO_URL = TARGETS["aistudio"]["base_url"]

# Key routes to visit
_ROUTES = {
    "home":      "/",
    "prompts":   "/prompts",
    "applets":   "/apps",
    "files":     "/files",
    "tuning":    "/tuning",
    "cached":    "/cached-content",
    "settings":  "/settings",
}


class AIStudioCrawler(BaseCrawler):
    """Crawl AI Studio, capturing gRPC-web traffic for all major flows."""

    name = "aistudio"
    target_domain = "aistudio.google.com"

    def __init__(self, monitor: Optional[NetworkMonitor] = None) -> None:
        super().__init__(monitor)

    # ──── Main flow sequence ────

    async def run_flows(self) -> List[CrawlStep]:
        """Execute all AI Studio flows in sequence."""
        await self.get_or_open_page("aistudio.google.com", AISTUDIO_URL, reload=True)
        await asyncio.sleep(2)

        # ── Flow 1: Home page ──
        await self.step("home_page", lambda: self._wait_network_idle())

        # ── Flow 2: Navigate to prompts list ──
        await self.step("prompts_list",
                        lambda: self.navigate(f"{AISTUDIO_URL}/prompts"))

        # ── Flow 3: Open first prompt ──
        await self.step("open_prompt", self._open_first_prompt)

        # ── Flow 4: Run generation ──
        await self.step("run_generation", self._run_generation)

        # ── Flow 5: Change model ──
        await self.step("change_model", self._change_model)

        # ── Flow 6: Adjust safety/parameters ──
        await self.step("adjust_parameters", self._adjust_parameters)

        # ── Flow 7: System instructions ──
        await self.step("system_instructions", self._open_system_instructions)

        # ── Flow 8: Function calling ──
        await self.step("function_calling", self._open_function_calling)

        # ── Flow 9: Applets list ──
        await self.step("applets_list",
                        lambda: self.navigate(f"{AISTUDIO_URL}/apps"))

        # ── Flow 10: Open first applet ──
        await self.step("open_applet", self._open_first_applet)

        # ── Flow 11: Files manager ──
        await self.step("files_manager",
                        lambda: self.navigate(f"{AISTUDIO_URL}/files"))

        # ── Flow 12: Tuning panel ──
        await self.step("tuning_panel",
                        lambda: self.navigate(f"{AISTUDIO_URL}/tuning"))

        # ── Flow 13: Cached content ──
        await self.step("cached_content",
                        lambda: self.navigate(f"{AISTUDIO_URL}/cached-content"))

        # ── Flow 14: Settings ──
        await self.step("settings",
                        lambda: self.navigate(f"{AISTUDIO_URL}/settings"))

        # ── Flow 15: Get window globals (feature flags, config) ──
        await self.step("extract_globals", self._extract_page_globals)

        self._log_method_coverage()
        return self._steps

    # ──── Individual flow implementations ────

    async def _open_first_prompt(self) -> None:
        """Click the first prompt in the list."""
        try:
            await self._page.wait_for_selector(
                "a[href*='/prompts/'], mat-card, .prompt-card, "
                "[data-prompt-id], ms-prompt-item, .item-list-item",
                timeout=10_000,
            )
            # Prefer href-based navigation (avoids Angular routing issues)
            prompt_links = await self._page.query_selector_all("a[href*='/prompts/']")
            if prompt_links:
                href = await prompt_links[0].get_attribute("href")
                if href:
                    url = f"https://aistudio.google.com{href}" if href.startswith("/") else href
                    await self._page.goto(url, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    return
            # Fallback: click first card
            cards = await self._page.query_selector_all(
                "mat-card, ms-prompt-item, .item-list-item, [role='listitem']"
            )
            if cards:
                await cards[0].click()
                await asyncio.sleep(2)
            else:
                logger.debug("AIStudioCrawler: no prompt items found")
                await self.dump_dom_info("open_first_prompt")
        except Exception as exc:
            logger.debug("AIStudioCrawler: open_first_prompt: %s", exc)

    async def _run_generation(self) -> None:
        """Click the Run button to trigger StreamGenerateContent."""
        try:
            run_btn = await self.find_button("Run", "run", "Submit", "Generate")
            if not run_btn:
                run_btn = await self._page.query_selector(
                    "button:has-text('Run'), "
                    "button[aria-label*='Run'], "
                    "button[aria-label*='run'], "
                    "[data-testid='run-button'], "
                    "ms-run-button button"
                )
            if run_btn:
                await run_btn.click()
                await asyncio.sleep(5)  # Wait for streaming response
            else:
                logger.debug("AIStudioCrawler: no run button found")
                await self.dump_dom_info("run_generation")
        except Exception as exc:
            logger.debug("AIStudioCrawler: run_generation: %s", exc)

    async def _change_model(self) -> None:
        """Open model selector and switch model."""
        try:
            model_selector = await self._page.query_selector(
                "mat-select[aria-label*='model'], "
                "button:has-text('gemini'), "
                "button[aria-label*='Select model'], "
                "ms-model-selector, "
                "[aria-label*='Select model'], "
                ".model-selector, "
                "[data-testid='model-selector']"
            )
            if not model_selector:
                # Try locator
                model_selector = await self.find_button("Select model", "model")
            if model_selector:
                await model_selector.click()
                await asyncio.sleep(0.5)
                options = await self._page.query_selector_all(
                    "mat-option, [role='option'], li[data-model]"
                )
                if len(options) > 1:
                    await options[1].click()
                    await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("AIStudioCrawler: change_model: %s", exc)

    async def _adjust_parameters(self) -> None:
        """Open the parameters/settings panel and adjust a slider."""
        try:
            params_btn = await self._page.query_selector(
                "button:has-text('Parameters'), "
                "[aria-label*='parameters'], "
                "button:has-text('Settings'), "
                ".parameters-panel-toggle"
            )
            if params_btn:
                await params_btn.click()
                await asyncio.sleep(0.5)
                # Try to interact with temperature slider
                slider = await self._page.query_selector(
                    "mat-slider[aria-label*='temperature'], "
                    "input[type='range'][aria-label*='temp']"
                )
                if slider:
                    await slider.click()
                    await asyncio.sleep(0.3)
        except Exception as exc:
            logger.debug("AIStudioCrawler: adjust_parameters: %s", exc)

    async def _open_system_instructions(self) -> None:
        """Open the system instructions panel."""
        try:
            si_btn = await self._page.query_selector(
                "button:has-text('System instructions'), "
                "[aria-label*='System instructions'], "
                "mat-expansion-panel:has-text('System instructions')"
            )
            if si_btn:
                await si_btn.click()
                await asyncio.sleep(0.5)
        except Exception as exc:
            logger.debug("AIStudioCrawler: open_system_instructions: %s", exc)

    async def _open_function_calling(self) -> None:
        """Open the function calling / tools configuration."""
        try:
            fn_btn = await self._page.query_selector(
                "button:has-text('Function calling'), "
                "button:has-text('Tools'), "
                "[aria-label*='function'], "
                "mat-tab:has-text('Tools')"
            )
            if fn_btn:
                await fn_btn.click()
                await asyncio.sleep(0.5)
        except Exception as exc:
            logger.debug("AIStudioCrawler: open_function_calling: %s", exc)

    async def _open_first_applet(self) -> None:
        """Click the first applet in the apps list."""
        try:
            applets = await self._page.query_selector_all(
                "a[href*='/apps/'], mat-card[routerlink*='apps'], [data-app-id]"
            )
            if applets:
                await applets[0].click()
                await asyncio.sleep(2)
                await self._page.go_back()
        except Exception as exc:
            logger.debug("AIStudioCrawler: open_first_applet: %s", exc)

    async def _extract_page_globals(self) -> None:
        """Extract window globals and Angular services from the current page."""
        try:
            globals_data = await self.get_window_globals()
            services = await self.get_angular_services()
            logger.info(
                "AIStudioCrawler: found %d globals, %d Angular services",
                len(globals_data), len(services),
            )
            # Store findings in step notes (picked up by orchestrator)
            if self._steps:
                self._steps[-1].note(f"globals: {list(globals_data.keys())[:20]}")
                self._steps[-1].note(f"angular_services: {services[:20]}")
        except Exception as exc:
            logger.debug("AIStudioCrawler: extract_page_globals: %s", exc)

    # ──── Coverage analysis ────

    def _log_method_coverage(self) -> None:
        """Log which AI Studio methods were seen in captured gRPC-web traffic."""
        seen_methods = set()
        for step in self._steps:
            for req in step.traffic:
                if req.is_grpc_web:
                    for method in AISTUDIO_METHODS:
                        if method in req.url:
                            seen_methods.add(method)

        coverage = len(seen_methods) / len(AISTUDIO_METHODS) * 100
        logger.info(
            "AIStudioCrawler: method coverage %.0f%% (%d/%d seen)",
            coverage, len(seen_methods), len(AISTUDIO_METHODS),
        )
        logger.info("Methods seen: %s", sorted(seen_methods))
