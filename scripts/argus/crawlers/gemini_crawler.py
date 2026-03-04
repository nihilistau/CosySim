"""ARGUS Gemini crawler — systematic UI flow mapper for gemini.google.com.

Flows covered:
    1.  Home page load                             → ListModels, GetFeatureFlags
    2.  New conversation                           → (session init)
    3.  Send a text message                        → ProxyUnaryCall (boaYGb)
    4.  Send message with model switch             → k9yDXd, XqsOBb
    5.  View conversation history                  → (list panel)
    6.  Linked notebooks bridge                    → NXpLKc (ListLinkedNotebooks)
    7.  File upload dialog                         → BgXnQc (CreateFile)
    8.  Count tokens                               → mMEAEd
    9.  View extensions / integrations             → feature flag discovery
   10.  Delete a conversation                      → (cleanup)
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from scripts.argus.config import GEMINI_RPCIDS, TARGETS
from scripts.argus.crawlers.base_crawler import BaseCrawler, CrawlStep
from scripts.argus.network_monitor import NetworkMonitor

logger = logging.getLogger(__name__)

GEMINI_URL = TARGETS["gemini"]["base_url"]


class GeminiCrawler(BaseCrawler):
    """Crawl Gemini, triggering all known rpcids and capturing traffic."""

    name = "gemini"
    target_domain = "gemini.google.com"

    def __init__(self, monitor: Optional[NetworkMonitor] = None) -> None:
        super().__init__(monitor)

    # ──── Main flow sequence ────

    async def run_flows(self) -> List[CrawlStep]:
        """Execute all Gemini flows in sequence."""
        await self.get_or_open_page("gemini.google.com", GEMINI_URL)
        await asyncio.sleep(2)

        # ── Flow 1: Home page (loads models list + feature flags) ──
        await self.step("home_page_load",
                        lambda: self._wait_network_idle())

        # ── Flow 2: New conversation ──
        await self.step("new_conversation",
                        self._start_new_conversation)

        # ── Flow 3: Send a simple message ──
        await self.step("send_message",
                        self._send_message)

        # ── Flow 4: Switch model ──
        await self.step("switch_model",
                        self._switch_model)

        # ── Flow 5: Send another message (different model) ──
        await self.step("send_message_new_model",
                        lambda: self._send_message("Explain what you are in one sentence."))

        # ── Flow 6: Open linked notebooks bridge ──
        await self.step("linked_notebooks",
                        self._open_linked_notebooks)

        # ── Flow 7: File upload dialog (triggers CreateFile) ──
        await self.step("file_upload_dialog",
                        self._open_file_upload)

        # ── Flow 8: View conversation history sidebar ──
        await self.step("conversation_history",
                        self._open_history_panel)

        # ── Flow 9: Extensions / integrations panel ──
        await self.step("extensions_panel",
                        self._open_extensions_panel)

        # ── Flow 10: Settings page ──
        await self.step("settings_page",
                        self._open_settings)

        # Log coverage
        self._log_rpcid_coverage()

        return self._steps

    # ──── Individual flow implementations ────

    async def _start_new_conversation(self) -> None:
        """Click 'New chat' to start a fresh conversation."""
        try:
            new_chat = await self._page.query_selector(
                "button:has-text('New chat'), "
                "[aria-label*='New chat'], "
                "[aria-label*='new chat'], "
                "a[href='/'], "
                "bard-sidenav-item:has-text('New chat')"
            )
            if new_chat:
                await new_chat.click()
                await asyncio.sleep(1)
            else:
                await self._page.goto(GEMINI_URL, wait_until="domcontentloaded")
        except Exception as exc:
            logger.debug("GeminiCrawler: new_conversation: %s", exc)

    async def _send_message(self, text: str = "What is 2 + 2?") -> None:
        """Type and send a message in the Gemini chat box."""
        try:
            # Gemini uses a rich text input
            input_area = await self._page.wait_for_selector(
                "rich-textarea div[contenteditable='true'], "
                "textarea[aria-label*='message'], "
                "div[role='textbox']",
                timeout=8_000,
            )
            await input_area.click()
            await input_area.fill(text)
            await asyncio.sleep(0.3)

            send_btn = await self._page.query_selector(
                "button[aria-label*='Send'], "
                "button[aria-label*='send'], "
                "mat-icon[aria-label*='send']"
            )
            if send_btn:
                await send_btn.click()
            else:
                await input_area.press("Enter")
            await asyncio.sleep(4)  # Wait for response to stream
        except Exception as exc:
            logger.debug("GeminiCrawler: send_message: %s", exc)

    async def _switch_model(self) -> None:
        """Click the model selector and switch to a different model."""
        try:
            model_btn = await self._page.query_selector(
                "[aria-label*='model'], "
                "button:has-text('Gemini'), "
                ".model-selector, "
                "[data-testid='model-switcher']"
            )
            if not model_btn:
                return
            await model_btn.click()
            await asyncio.sleep(0.5)

            # Pick a model from the dropdown (not the current one)
            model_options = await self._page.query_selector_all(
                "mat-option, [role='option'], li[data-model]"
            )
            if len(model_options) > 1:
                await model_options[1].click()
                await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("GeminiCrawler: switch_model: %s", exc)

    async def _open_linked_notebooks(self) -> None:
        """Find and click the 'Notebooks' or NLM integration button."""
        try:
            # Gemini has a Notebooks integration that calls NXpLKc (ListLinkedNotebooks)
            notebooks_btn = await self._page.query_selector(
                "button:has-text('Notebook'), "
                "[aria-label*='notebook'], "
                "[aria-label*='Notebook'], "
                "button[data-tool='notebooklm']"
            )
            if notebooks_btn:
                await notebooks_btn.click()
                await asyncio.sleep(2)
                # Close the panel
                close = await self._page.query_selector(
                    "button[aria-label='Close'], button[aria-label='Back']"
                )
                if close:
                    await close.click()
            else:
                # Try the @ mention which can trigger notebook picker
                input_area = await self._page.query_selector(
                    "rich-textarea div[contenteditable='true'], div[role='textbox']"
                )
                if input_area:
                    await input_area.click()
                    await input_area.fill("@")
                    await asyncio.sleep(1)
                    # Press Escape to dismiss
                    await input_area.press("Escape")
                    await input_area.fill("")
        except Exception as exc:
            logger.debug("GeminiCrawler: open_linked_notebooks: %s", exc)

    async def _open_file_upload(self) -> None:
        """Click the file upload button to trigger CreateFile endpoint."""
        try:
            upload_btn = await self._page.query_selector(
                "button[aria-label*='upload'], "
                "button[aria-label*='Upload'], "
                "button[aria-label*='attach'], "
                "button[aria-label*='Attach'], "
                "[data-testid='file-upload']"
            )
            if upload_btn:
                await upload_btn.click()
                await asyncio.sleep(1)
                # Dismiss without uploading
                await self._page.keyboard.press("Escape")
        except Exception as exc:
            logger.debug("GeminiCrawler: open_file_upload: %s", exc)

    async def _open_history_panel(self) -> None:
        """Open the conversation history sidebar."""
        try:
            history_btn = await self._page.query_selector(
                "button[aria-label*='history'], "
                "button[aria-label*='History'], "
                "[aria-label*='Recent'], "
                "button:has-text('Recent')"
            )
            if history_btn:
                await history_btn.click()
                await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("GeminiCrawler: open_history_panel: %s", exc)

    async def _open_extensions_panel(self) -> None:
        """Open Extensions or Integrations panel."""
        try:
            ext_btn = await self._page.query_selector(
                "button[aria-label*='extension'], "
                "button[aria-label*='Extension'], "
                "button:has-text('Extensions'), "
                "[href*='extensions']"
            )
            if ext_btn:
                await ext_btn.click()
                await asyncio.sleep(1)
                await self._page.keyboard.press("Escape")
        except Exception as exc:
            logger.debug("GeminiCrawler: open_extensions_panel: %s", exc)

    async def _open_settings(self) -> None:
        """Navigate to settings page."""
        try:
            settings_btn = await self._page.query_selector(
                "button[aria-label*='settings'], "
                "button[aria-label*='Settings'], "
                "[href*='settings']"
            )
            if settings_btn:
                await settings_btn.click()
                await asyncio.sleep(1)
                # Go back
                await self._page.go_back()
        except Exception as exc:
            logger.debug("GeminiCrawler: open_settings: %s", exc)

    # ──── Coverage analysis ────

    def _log_rpcid_coverage(self) -> None:
        seen = set()
        for step in self._steps:
            for req in step.traffic:
                for rpcid in GEMINI_RPCIDS:
                    if rpcid in (req.post_data or "") or rpcid in (req.url or ""):
                        seen.add(rpcid)

        coverage = len(seen) / len(GEMINI_RPCIDS) * 100
        missing = set(GEMINI_RPCIDS) - seen
        logger.info(
            "GeminiCrawler: rpcid coverage %.0f%% (%d/%d). Missing: %s",
            coverage, len(seen), len(GEMINI_RPCIDS),
            [GEMINI_RPCIDS[r] for r in missing] if missing else "none",
        )
