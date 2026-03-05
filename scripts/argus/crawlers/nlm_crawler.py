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
        page = await self.get_or_open_page("notebooklm.google.com", NLM_URL, reload=True)
        await asyncio.sleep(2)  # Let the SPA fully load

        # If we landed directly on a notebook page, use it immediately
        if "/notebook/" in page.url:
            self._notebook_url = page.url
            logger.info("NLMCrawler: already on notebook %s", self._notebook_url)
            await self.step("list_notebooks", lambda: self._wait_network_idle())
        else:
            # ── Flow 1: Home page / list notebooks ──
            await self.step("list_notebooks", lambda: self._wait_network_idle())
            # ── Flow 2: Open first notebook ──
            await self.step("open_notebook", self._open_first_notebook)

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
            # NLM uses Angular routing — wait for notebook list to render
            await self._page.wait_for_selector(
                "a[href*='/notebook/'], "
                "[data-notebook-id], "
                "nb-notebook-card, "
                ".notebook-card, "
                "mat-card",
                timeout=15_000,
            )
            # Try href-based links first (most reliable)
            notebook_links = await self._page.query_selector_all(
                "a[href*='/notebook/']"
            )
            if notebook_links:
                href = await notebook_links[0].get_attribute("href")
                if href:
                    nb_url = f"https://notebooklm.google.com{href}" if href.startswith("/") else href
                    await self._page.goto(nb_url, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    self._notebook_url = self._page.url
                    logger.info("NLMCrawler: opened notebook %s", self._notebook_url)
                    return
            # Fallback: click the first card
            cards = await self._page.query_selector_all(
                "mat-card, nb-notebook-card, .notebook-card, [role='listitem']"
            )
            if cards:
                await cards[0].click()
                await asyncio.sleep(2)
                self._notebook_url = self._page.url
                logger.info("NLMCrawler: opened notebook via card click %s", self._notebook_url)
            else:
                logger.warning("NLMCrawler: no notebook links or cards found on page")
                # Debug: dump interactive elements to help fix selectors
                await self.dump_dom_info("open_first_notebook")
        except Exception as exc:
            logger.warning("NLMCrawler: open_first_notebook failed: %s", exc)
            await self.dump_dom_info("open_first_notebook_err")

    async def _send_chat_message(self) -> None:
        """Type and send a simple chat message."""
        try:
            # Try Playwright locator API first — more robust than query_selector
            sent = False
            for selector in [
                "textarea[aria-label*='Ask']",
                "textarea[aria-label*='ask']",
                "textarea[aria-label*='query']",
                "textarea[aria-label*='Query']",
                "textarea[aria-label*='chat']",
                "textarea[aria-label*='message']",
                "textarea:not([aria-label*='emoji']):not([aria-label*='search'])",
                "[contenteditable='true']:not([aria-label*='emoji'])",
            ]:
                try:
                    loc = self._page.locator(selector).first
                    await loc.wait_for(state="visible", timeout=5_000)
                    await loc.click()
                    await loc.fill("What are the main topics in this notebook?")
                    await asyncio.sleep(0.3)
                    sent = True
                    break
                except Exception:
                    continue

            if not sent:
                logger.debug("NLMCrawler: no chat textarea found — trying JS injection")
                # Inject batchexecute directly for SendChatMessage
                await self._inject_nlm_chat_message(
                    "What are the main topics in this notebook?"
                )
                await asyncio.sleep(2)
                return

            # Send via button or Enter
            send_btn = await self.find_button("Send", "send", "Submit", "submit")
            if send_btn:
                await send_btn.click()
            else:
                await self._page.keyboard.press("Enter")
            await asyncio.sleep(4)  # Wait for response to stream
        except Exception as exc:
            logger.warning("NLMCrawler: send_chat_message failed: %s", exc)

    async def _inject_nlm_chat_message(self, text: str) -> None:
        """Inject a batchexecute SendChatMessage call via page-context fetch().

        This fires the tJHFsf rpcid directly using the browser's own session,
        bypassing DOM interaction. NetworkMonitor captures the resulting request.
        """
        # Extract current notebook ID from URL
        nb_id = ""
        if self._notebook_url:
            parts = self._notebook_url.rstrip("/").split("/")
            if "notebook" in parts:
                idx = parts.index("notebook")
                if idx + 1 < len(parts):
                    nb_id = parts[idx + 1]

        import json
        payload_inner = json.dumps([text, nb_id, [], None, None, None, None, None, None, None, True])
        f_req_inner = json.dumps([[["tJHFsf", payload_inner, None, "generic"]]])
        import urllib.parse
        body = "f.req=" + urllib.parse.quote(f_req_inner)

        result = await self.inject_fetch(
            url="/_/LabsTailwindUi/data/batchexecute?rpcids=tJHFsf&source-path=%2Fnotebook%2F"
                + nb_id,
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
            body=body,
        )
        if result:
            logger.info("NLMCrawler: injected tJHFsf chat → status %s", result.get("status"))

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
            # Try Playwright's robust locator API first
            btn = await self.find_button(label, option_lower.title())
            if btn:
                await btn.click()
                await asyncio.sleep(2)
                return
            # Fallback: scan all clickable elements for text match
            btns = await self._page.query_selector_all(
                "button, mat-list-item, [role='button'], mat-chip, "
                "nb-studio-option, .studio-option"
            )
            for b in btns:
                try:
                    text = (await b.inner_text()).strip().lower()
                    if option_lower in text or label.lower() in text:
                        await b.click()
                        await asyncio.sleep(2)
                        return
                except Exception:
                    continue
            logger.debug("NLMCrawler: '%s' button not found", label)
            await self.dump_dom_info(f"studio_{option_lower}")
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
            btn = await self.find_button("Sources", "sources", "Add source")
            if btn:
                await btn.click()
                await asyncio.sleep(1)
                return
            # Fallback selectors
            sources_btn = await self._page.query_selector(
                "[aria-label*='source'], [aria-label*='Source'], "
                "button:has-text('Sources'), mat-tab:has-text('Sources'), "
                "nb-sources-panel, [data-panel='sources']"
            )
            if sources_btn:
                await sources_btn.click()
                await asyncio.sleep(1)
            else:
                # Inject ListSources batchexecute directly
                await self._inject_nlm_rpcid("jtGGne", "[]")
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
        """Trigger a GetFeatureFlags call via JS injection + reload."""
        try:
            # Inject directly — ozz5Z fires on every page load anyway
            await self._inject_nlm_rpcid("ozz5Z", "[0]")
            await asyncio.sleep(1)
        except Exception as exc:
            logger.debug("NLMCrawler: probe_feature_flags: %s", exc)

    async def _inject_nlm_rpcid(self, rpcid: str, payload_json: str) -> None:
        """Inject a batchexecute call for a given NLM rpcid via page-context fetch().

        The request fires from the browser (so session cookies are included) and
        is captured by the NetworkMonitor's Playwright page listener.

        Args:
            rpcid:        The batchexecute rpcid string, e.g. "jtGGne".
            payload_json: JSON string to use as the inner payload, e.g. "[]".
        """
        import json
        import urllib.parse
        f_req = json.dumps([[[rpcid, payload_json, None, "generic"]]])
        body = "f.req=" + urllib.parse.quote(f_req)
        result = await self.inject_fetch(
            url=f"/_/LabsTailwindUi/data/batchexecute?rpcids={rpcid}",
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
            body=body,
        )
        if result:
            logger.info(
                "NLMCrawler: injected rpcid %s → status %s",
                rpcid, result.get("status"),
            )

    async def _create_and_delete_notebook(self) -> None:
        """Create a temporary notebook and immediately delete it."""
        try:
            # Navigate back to home
            await self._page.goto(NLM_URL, wait_until="domcontentloaded")
            await asyncio.sleep(1)

            # Find 'New notebook' button using robust locator
            new_btn = await self.find_button(
                "New notebook", "Create notebook", "New", "Create"
            )
            if not new_btn:
                new_btn = await self._page.query_selector(
                    "button:has-text('New notebook'), "
                    "[aria-label*='new notebook'], "
                    "[aria-label*='New notebook'], "
                    "button:has-text('Create')"
                )
            if not new_btn:
                logger.debug("NLMCrawler: no 'New notebook' button found")
                await self.dump_dom_info("create_notebook")
                # Fallback: inject CreateNotebook rpcid directly
                await self._inject_nlm_rpcid("VqhFhd", '["ARGUS test notebook",[]]')
                return
            await new_btn.click()
            await asyncio.sleep(2)

            # Get the new notebook URL (if we were redirected)
            new_url = self._page.url
            logger.info("NLMCrawler: created notebook at %s", new_url)

            # Delete it — find the kebab menu / delete option
            menu_btn = await self._page.query_selector(
                "[aria-label*='more options'], [aria-label*='More options'], "
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
