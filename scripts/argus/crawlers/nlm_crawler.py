"""ARGUS NotebookLM crawler — systematic UI flow mapper for notebooklm.google.com.

Executes every significant NLM user flow, capturing the batchexecute traffic
at each step to verify all 24 known rpcids and discover any new ones.

Flows covered:
    1.  List notebooks (home page load)            → wIlBFe
    2.  Open a notebook                            → GetNotebook / ListSources
    3.  Send a chat message                        → tJHFsf
    4.  Get chat history                           → GzgSEd
    5.  Generate a study guide                     → xqEXEf
    6.  Generate an FAQ                            → xqEXEf (variant)
    7.  Generate a briefing doc                    → xqEXEf (variant)
    8.  Get audio overview status                  → sqTeoe
    9.  Get notebook analysis                      → VfAZjd
   10.  Add a text source                          → PoHVkb
   11.  List sources                               → jtGGne
   12.  Get feature flags                          → ozz5Z
   13.  Create a new notebook (then delete it)     → VqhFhd / kVoZqc
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from scripts.argus.config import NLM_RPCIDS, TARGETS
from scripts.argus.crawlers.base_crawler import BaseCrawler, CrawlStep
from scripts.argus.network_monitor import NetworkMonitor

logger = logging.getLogger(__name__)

NLM_URL = TARGETS["notebooklm"]["base_url"]


class NLMCrawler(BaseCrawler):
    """Crawl NotebookLM, triggering all known rpcids and capturing traffic."""

    name = "nlm"
    target_domain = "notebooklm.google.com"

    def __init__(self, monitor: Optional[NetworkMonitor] = None,
                 test_notebook_id: Optional[str] = None) -> None:
        super().__init__(monitor)
        # If provided, use this notebook rather than the first in list
        self._target_notebook_id = test_notebook_id
        self._notebook_url: Optional[str] = None

    # ──── Main flow sequence ────

    async def run_flows(self) -> List[CrawlStep]:
        """Execute all NLM flows in sequence."""
        page = await self.get_or_open_page("notebooklm.google.com", NLM_URL)
        await asyncio.sleep(2)  # Let the SPA fully load

        # ── Flow 1: Home page / list notebooks ──
        await self.step("list_notebooks",
                        lambda: self._wait_network_idle())

        # ── Flow 2: Open first notebook ──
        await self.step("open_notebook",
                        self._open_first_notebook)

        if not self._notebook_url:
            logger.warning("NLMCrawler: no notebook found — skipping detail flows")
            return self._steps

        # ── Flow 3: Chat message ──
        await self.step("send_chat_message",
                        self._send_chat_message)

        # ── Flow 4: Chat history (scroll up) ──
        await self.step("get_chat_history",
                        lambda: self.scroll_to_bottom())

        # ── Flow 5: Generate study guide ──
        await self.step("generate_study_guide",
                        self._generate_study_guide)

        # ── Flow 6: Generate FAQ ──
        await self.step("generate_faq",
                        self._generate_faq)

        # ── Flow 7: Generate briefing doc ──
        await self.step("generate_briefing",
                        self._generate_briefing)

        # ── Flow 8: Audio overview panel ──
        await self.step("open_audio_overview",
                        self._open_audio_overview)

        # ── Flow 9: Notebook analysis / insights ──
        await self.step("get_notebook_analysis",
                        self._open_notebook_analysis)

        # ── Flow 10: Sources panel ──
        await self.step("list_sources",
                        self._open_sources_panel)

        # ── Flow 11: Add a text source ──
        await self.step("add_text_source",
                        self._add_text_source)

        # ── Flow 12: Feature flags (via URL trigger) ──
        await self.step("get_feature_flags",
                        self._probe_feature_flags)

        # ── Flow 13: Create + delete a temp notebook ──
        await self.step("create_delete_notebook",
                        self._create_and_delete_notebook)

        # ── Flow 14: Share notebook dialog ──
        await self.step("open_share_dialog",
                        self._open_share_dialog)

        # Log coverage
        self._log_rpcid_coverage()

        return self._steps

    # ──── Individual flow implementations ────

    async def _open_first_notebook(self) -> None:
        """Click the first notebook card to open it."""
        try:
            # Wait for notebook cards to appear
            await self._page.wait_for_selector(
                "a[href*='/notebook/'], [data-notebook-id], .notebook-item, "
                "mat-card[routerlink], [routerlink*='notebook']",
                timeout=15_000,
            )
            # Click the first one
            notebook_links = await self._page.query_selector_all(
                "a[href*='/notebook/'], [routerlink*='notebook']"
            )
            if notebook_links:
                await notebook_links[0].click()
                await asyncio.sleep(2)
                self._notebook_url = self._page.url
                logger.info("NLMCrawler: opened notebook %s", self._notebook_url)
            else:
                logger.warning("NLMCrawler: no notebook links found")
        except Exception as exc:
            logger.warning("NLMCrawler: open_first_notebook failed: %s", exc)

    async def _send_chat_message(self) -> None:
        """Type and send a simple chat message."""
        try:
            textarea = await self._page.wait_for_selector(
                "textarea, [contenteditable='true'], input[type='text']",
                timeout=8_000,
            )
            await textarea.click()
            await textarea.fill("What are the main topics in this notebook?")
            await asyncio.sleep(0.3)
            # Try send button or Enter
            send_btn = await self._page.query_selector(
                "button[aria-label*='send'], button[aria-label*='Send'], "
                "button[type='submit'], mat-icon-button"
            )
            if send_btn:
                await send_btn.click()
            else:
                await textarea.press("Enter")
            await asyncio.sleep(3)  # Wait for response
        except Exception as exc:
            logger.warning("NLMCrawler: send_chat_message failed: %s", exc)

    async def _generate_study_guide(self) -> None:
        """Open the studio panel and trigger study guide generation."""
        await self._click_studio_option("study guide", "Study guide")

    async def _generate_faq(self) -> None:
        """Trigger FAQ generation from studio panel."""
        await self._click_studio_option("faq", "FAQ")

    async def _generate_briefing(self) -> None:
        """Trigger briefing doc generation from studio panel."""
        await self._click_studio_option("briefing", "Briefing")

    async def _click_studio_option(self, option_lower: str, label: str) -> None:
        """Click a studio panel option by label."""
        try:
            # Look for studio/notebook guide panel
            btns = await self._page.query_selector_all("button, mat-list-item, [role='button']")
            for btn in btns:
                text = (await btn.inner_text()).strip().lower()
                if option_lower in text or label.lower() in text:
                    await btn.click()
                    await asyncio.sleep(2)
                    return
            logger.debug("NLMCrawler: '%s' button not found", label)
        except Exception as exc:
            logger.debug("NLMCrawler: %s failed: %s", label, exc)

    async def _open_audio_overview(self) -> None:
        """Open the audio overview panel."""
        await self._click_studio_option("audio", "Audio overview")

    async def _open_notebook_analysis(self) -> None:
        """Open the notebook insights/analysis panel."""
        await self._click_studio_option("insight", "Notebook insights")
        await self._click_studio_option("analysis", "Notebook analysis")

    async def _open_sources_panel(self) -> None:
        """Open the sources panel to trigger ListSources."""
        try:
            sources_btn = await self._page.query_selector(
                "[aria-label*='source'], [aria-label*='Source'], "
                "button:has-text('Sources'), mat-tab:has-text('Sources')"
            )
            if sources_btn:
                await sources_btn.click()
                await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("NLMCrawler: open_sources_panel: %s", exc)

    async def _add_text_source(self) -> None:
        """Open 'Add source' dialog and add a text source."""
        try:
            add_btn = await self._page.query_selector(
                "button:has-text('Add source'), "
                "[aria-label*='add source'], "
                "[aria-label*='Add source']"
            )
            if not add_btn:
                return
            await add_btn.click()
            await asyncio.sleep(1)

            # Look for 'Copied text' option
            text_option = await self._page.query_selector(
                "button:has-text('Copied text'), "
                "mat-list-item:has-text('Paste text'), "
                "[aria-label*='text']"
            )
            if text_option:
                await text_option.click()
                await asyncio.sleep(0.5)
                # Fill in the text area
                ta = await self._page.query_selector("textarea")
                if ta:
                    await ta.fill("ARGUS test source: " + "x" * 100)
                    # Submit
                    submit = await self._page.query_selector(
                        "button:has-text('Insert'), button:has-text('Add')"
                    )
                    if submit:
                        await submit.click()
                        await asyncio.sleep(2)
            # Close dialog if still open
            close = await self._page.query_selector(
                "button[aria-label='Close'], button[aria-label='Cancel']"
            )
            if close:
                await close.click()
        except Exception as exc:
            logger.debug("NLMCrawler: add_text_source: %s", exc)

    async def _probe_feature_flags(self) -> None:
        """Trigger a GetFeatureFlags call via JS injection."""
        try:
            # NLM calls ozz5Z (GetFeatureFlags) on page load — just reload
            await self._page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2)
        except Exception as exc:
            logger.debug("NLMCrawler: probe_feature_flags: %s", exc)

    async def _create_and_delete_notebook(self) -> None:
        """Create a temporary notebook and immediately delete it."""
        try:
            # Navigate back to home
            await self._page.goto(NLM_URL, wait_until="domcontentloaded")
            await asyncio.sleep(1)

            # Find 'New notebook' button
            new_btn = await self._page.query_selector(
                "button:has-text('New notebook'), "
                "[aria-label*='new notebook'], "
                "[aria-label*='New notebook'], "
                "button:has-text('Create')"
            )
            if not new_btn:
                return
            await new_btn.click()
            await asyncio.sleep(2)

            # Get the new notebook URL (if we were redirected)
            new_url = self._page.url
            logger.info("NLMCrawler: created notebook at %s", new_url)

            # Delete it — find the kebab menu / delete option
            menu_btn = await self._page.query_selector(
                "[aria-label*='more'], [aria-label*='More'], "
                "button[aria-label*='options'], mat-icon-button"
            )
            if menu_btn:
                await menu_btn.click()
                await asyncio.sleep(0.5)
                delete_btn = await self._page.query_selector(
                    "button:has-text('Delete'), mat-menu-item:has-text('Delete')"
                )
                if delete_btn:
                    await delete_btn.click()
                    await asyncio.sleep(0.5)
                    # Confirm dialog
                    confirm = await self._page.query_selector(
                        "button:has-text('Delete'), "
                        "button:has-text('Confirm')"
                    )
                    if confirm:
                        await confirm.click()
                        await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("NLMCrawler: create_and_delete_notebook: %s", exc)

    async def _open_share_dialog(self) -> None:
        """Open the share dialog to trigger ShareNotebook / GetSharedNotebook."""
        try:
            if self._notebook_url:
                await self._page.goto(self._notebook_url, wait_until="domcontentloaded")
                await asyncio.sleep(1)
            share_btn = await self._page.query_selector(
                "button:has-text('Share'), [aria-label*='share'], [aria-label*='Share']"
            )
            if share_btn:
                await share_btn.click()
                await asyncio.sleep(1)
                # Close the dialog
                close = await self._page.query_selector(
                    "button[aria-label='Close'], button[aria-label='Cancel'], "
                    "button:has-text('Done')"
                )
                if close:
                    await close.click()
        except Exception as exc:
            logger.debug("NLMCrawler: open_share_dialog: %s", exc)

    # ──── Coverage analysis ────

    def _log_rpcid_coverage(self) -> None:
        """Log which known NLM rpcids were seen in captured traffic."""
        seen_rpcids = set()
        for step in self._steps:
            for req in step.traffic:
                if req.is_batchexecute and req.post_data:
                    # Quick scan of post_data for rpcid patterns
                    for rpcid in NLM_RPCIDS:
                        if rpcid in (req.post_data or ""):
                            seen_rpcids.add(rpcid)

        coverage = len(seen_rpcids) / len(NLM_RPCIDS) * 100
        missing = set(NLM_RPCIDS) - seen_rpcids
        logger.info(
            "NLMCrawler: rpcid coverage %.0f%% (%d/%d). Missing: %s",
            coverage, len(seen_rpcids), len(NLM_RPCIDS),
            [NLM_RPCIDS[r] for r in missing] if missing else "none",
        )
