"""
NLM Automation — Systematic NotebookLM operation runner with full network capture.

Launches Playwright with the user's real Chrome profile (already logged into Google)
and performs every known NLM operation in sequence, intercepting all network traffic.

The captured log maps each operation to the exact batchexecute RPCs and other
endpoints it triggered. Run this to discover new/changed RPC IDs after a Google
frontend build update, or to find operations we've never seen before.

Usage::

    python -m engine.nexus.nlm_automation
    python -m engine.nexus.nlm_automation --headless   # no visible browser
    python -m engine.nexus.nlm_automation --ops create_notebook,add_url_source
    python -m engine.nexus.nlm_automation --output data/nlm_capture_2026.json

Output::

    data/nlm_automation_log.json   — full structured capture log
    data/nlm_rpc_registry.json     — operation → RPC mapping (updated)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILE = _DATA_DIR / "nlm_automation_log.json"
_REGISTRY_FILE = _DATA_DIR / "nlm_rpc_registry.json"
_SCREENSHOTS_DIR = _DATA_DIR / "nlm_screenshots"

_NLM_URL = "https://notebooklm.google.com"
_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
_CHROME_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"

# Delay between operations — be respectful to Google's services
_OP_DELAY = 3.0       # seconds between operations
_WAIT_AFTER_NAV = 4.0  # seconds after page navigation
_WAIT_FOR_RESPONSE = 8.0  # seconds to wait for async responses (AI generation)
_LONG_WAIT = 15.0     # seconds for slow operations (audio overview, file upload)

# Test data used by automation
_TEST_NOTEBOOK_TITLE = f"CosySim NLM Automation Test {datetime.now().strftime('%Y%m%d_%H%M')}"
_TEST_URL = "https://en.wikipedia.org/wiki/Multi-agent_system"
_TEST_YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
_TEST_QUESTION = "What is the main topic of this notebook?"
_TEST_NOTE_TEXT = "Test note created by CosySim NLM automation."


class NLMCapture:
    """Records all network requests/responses with operation labels."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self._current_op: str = "UNKNOWN"
        self._pending_requests: Dict[str, Dict] = {}

    def set_operation(self, op_name: str) -> None:
        self._current_op = op_name
        logger.info("  >>> Operation: %s", op_name)

    def on_request(self, request: Any) -> None:
        url = request.url
        if not self._is_interesting(url):
            return
        entry = {
            "operation": self._current_op,
            "timestamp": time.time(),
            "direction": "request",
            "method": request.method,
            "url": url,
            "rpc_id": self._extract_rpc_id(url),
            "source_path": self._extract_source_path(url),
            "endpoint_type": self._classify_endpoint(url),
        }
        try:
            body = request.post_data or ""
            if "f.req=" in body:
                freq = urllib.parse.unquote(body.split("f.req=")[1].split("&")[0])
                try:
                    entry["f_req_parsed"] = json.loads(freq)
                except Exception:
                    entry["f_req_raw"] = freq[:2000]
        except Exception:
            pass
        self._pending_requests[request.url + str(time.time())[:10]] = entry
        self.events.append(entry)

    def on_response(self, response: Any) -> None:
        url = response.url
        if not self._is_interesting(url):
            return

    async def on_response_async(self, response: Any) -> None:
        url = response.url
        if not self._is_interesting(url):
            return
        entry = {
            "operation": self._current_op,
            "timestamp": time.time(),
            "direction": "response",
            "status": response.status,
            "url": url,
            "rpc_id": self._extract_rpc_id(url),
            "source_path": self._extract_source_path(url),
            "endpoint_type": self._classify_endpoint(url),
        }
        try:
            body = await response.body()
            text = body.decode("utf-8", errors="replace")
            if text.startswith(")]}'"):
                text = text[5:]
            rpcs = self._parse_batchexecute_response(text)
            if rpcs:
                entry["rpcs"] = rpcs
            elif len(text) < 4000:
                entry["response_text"] = text
        except Exception as exc:
            entry["response_error"] = str(exc)
        self.events.append(entry)

    def _is_interesting(self, url: str) -> bool:
        skip = ["google-analytics", "accounts.google.com/ListAccounts",
                "static/", ".svg", ".gif", ".png", ".jpg", ".json",
                "fonts.googleapis", "lh3.googleusercontent", "googletagmanager"]
        return "notebooklm.google.com" in url and not any(s in url for s in skip)

    def _extract_rpc_id(self, url: str) -> Optional[str]:
        m = re.search(r"rpcids=([^&]+)", url)
        if m:
            return urllib.parse.unquote(m.group(1))
        if "GenerateFreeFormStreamed" in url:
            return "GenerateFreeFormStreamed"
        if "GenerateDocument" in url:
            return "GenerateDocument"
        return None

    def _extract_source_path(self, url: str) -> Optional[str]:
        m = re.search(r"source-path=([^&]+)", url)
        return urllib.parse.unquote(m.group(1)) if m else None

    def _classify_endpoint(self, url: str) -> str:
        if "batchexecute" in url:
            return "batchexecute"
        if "LabsTailwindOrchestrationService" in url:
            return "grpc_stream"
        if "signaler-pa.clients6.google.com" in url:
            return "signaler"
        if "punctual" in url:
            return "realtime"
        return "other"

    def _parse_batchexecute_response(self, text: str) -> List[Dict]:
        rpcs = []
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith('[["wrb.fr"'):
                continue
            try:
                outer = json.loads(line)
                rpc_id = outer[0][1]
                inner_raw = outer[0][2]
                inner = json.loads(inner_raw) if inner_raw else None
                rpcs.append({"rpc_id": rpc_id, "response": inner})
            except Exception:
                pass
        return rpcs

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.events, f, indent=2, ensure_ascii=False, default=str)
        logger.info("Saved %d capture events to %s", len(self.events), path)

    def get_operation_rpc_map(self) -> Dict[str, List[str]]:
        """Returns {operation: [rpc_id, ...]} mapping from captured data."""
        op_map: Dict[str, List[str]] = {}
        for ev in self.events:
            op = ev.get("operation", "UNKNOWN")
            rpc = ev.get("rpc_id")
            if rpc and ev.get("direction") == "request":
                for r in rpc.split(";"):
                    r = r.strip()
                    if r:
                        op_map.setdefault(op, [])
                        if r not in op_map[op]:
                            op_map[op].append(r)
        return op_map


async def _wait(page: Any, seconds: float, reason: str = "") -> None:
    """Polite wait with logging."""
    if reason:
        logger.debug("    Waiting %.1fs: %s", seconds, reason)
    await asyncio.sleep(seconds)


async def _safe_click(page: Any, selector: str, timeout: int = 5000) -> bool:
    """Click a selector, return False if not found."""
    try:
        await page.locator(selector).first.click(timeout=timeout)
        return True
    except Exception:
        return False


async def _safe_fill(page: Any, selector: str, text: str, timeout: int = 5000) -> bool:
    try:
        el = page.locator(selector).first
        await el.click(timeout=timeout)
        await el.fill(text)
        return True
    except Exception:
        return False


async def _screenshot(page: Any, name: str) -> None:
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = _SCREENSHOTS_DIR / f"{ts}_{name}.png"
        await page.screenshot(path=str(path))
        logger.debug("    Screenshot: %s", path.name)
    except Exception:
        pass


async def run_automation(
    headless: bool = False,
    ops_filter: Optional[List[str]] = None,
    output: Optional[Path] = None,
) -> NLMCapture:
    """
    Run the full NLM automation sequence.

    Args:
        headless: Run browser without visible window.
        ops_filter: Only run these operation names (None = all).
        output: Where to save the capture log.

    Returns:
        NLMCapture with all recorded events.
    """
    from playwright.async_api import async_playwright

    capture = NLMCapture()
    output = output or _LOG_FILE

    async with async_playwright() as p:
        logger.info("Launching Chrome with user profile...")
        # Use real Chrome with user profile — already logged into Google
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(_CHROME_PROFILE / "Default"),
                executable_path=_CHROME_PATH,
                headless=headless,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions-except=",
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_https_errors=True,
                viewport={"width": 1280, "height": 900},
            )
        except Exception as e:
            logger.warning("Chrome profile launch failed (%s), falling back to Playwright Chromium", e)
            # Fallback: use Playwright's Chromium (won't have Google session)
            browser = await p.chromium.launch(headless=headless)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900})

        page = await ctx.new_page()

        # Wire up network capture — response body needs async handler
        page.on("request", capture.on_request)
        page.on("response", lambda r: asyncio.ensure_future(capture.on_response_async(r)))

        test_nb_id: Optional[str] = None
        test_source_id: Optional[str] = None

        def _should_run(op: str) -> bool:
            return ops_filter is None or op in ops_filter

        # ── LOAD HOMEPAGE ─────────────────────────────────────────────────
        if _should_run("LOAD_HOMEPAGE"):
            capture.set_operation("LOAD_HOMEPAGE")
            await page.goto(_NLM_URL, wait_until="networkidle")
            await _wait(page, _WAIT_AFTER_NAV, "homepage load")
            await _screenshot(page, "homepage")

        # ── LIST NOTEBOOKS ─────────────────────────────────────────────────
        if _should_run("LIST_NOTEBOOKS"):
            capture.set_operation("LIST_NOTEBOOKS")
            await _wait(page, _OP_DELAY)

        # ── CREATE NOTEBOOK ────────────────────────────────────────────────
        if _should_run("CREATE_NOTEBOOK"):
            capture.set_operation("CREATE_NOTEBOOK")
            await _wait(page, _OP_DELAY)
            # Try various selectors for "New notebook" button
            created = False
            for sel in [
                'button:has-text("New notebook")',
                '[aria-label="New notebook"]',
                '[data-test-id="new-notebook"]',
                'button[jsname]:has-text("New")',
                'a[href="/notebook/creating"]',
                'button.new-notebook-button',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    created = True
                    logger.info("    Clicked new notebook with: %s", sel)
                    break
            if not created:
                # Try clicking the + button if visible
                await _safe_click(page, 'button[aria-label*="new" i]', timeout=3000)
            await _wait(page, _WAIT_AFTER_NAV, "notebook creation")
            await _screenshot(page, "create_notebook")
            # Grab the new notebook ID from URL
            current_url = page.url
            m = re.search(r"/notebook/([a-f0-9-]{36})", current_url)
            if m:
                test_nb_id = m.group(1)
                logger.info("    New notebook ID: %s", test_nb_id)

        # ── ADD URL SOURCE ─────────────────────────────────────────────────
        if _should_run("ADD_URL_SOURCE") and test_nb_id:
            capture.set_operation("ADD_URL_SOURCE")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Add source")',
                '[aria-label="Add source"]',
                'button:has-text("Add")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            # Click "Website URL" option in source menu
            for sel in [
                'button:has-text("Website URL")',
                '[aria-label="Website URL"]',
                'li:has-text("Website")',
                'button:has-text("Link")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            await _safe_fill(page, 'input[type="url"]', _TEST_URL)
            await _safe_fill(page, 'input[placeholder*="url" i]', _TEST_URL)
            await _safe_click(page, 'button:has-text("Insert")', timeout=3000)
            await _wait(page, _WAIT_FOR_RESPONSE, "URL source ingestion")
            await _screenshot(page, "add_url_source")

        # ── ADD YOUTUBE SOURCE ─────────────────────────────────────────────
        if _should_run("ADD_YOUTUBE_SOURCE") and test_nb_id:
            capture.set_operation("ADD_YOUTUBE_SOURCE")
            await _wait(page, _OP_DELAY)
            for sel in ['button:has-text("Add source")', '[aria-label="Add source"]']:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            for sel in [
                'button:has-text("YouTube")',
                'li:has-text("YouTube")',
                '[aria-label*="YouTube"]',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            await _safe_fill(page, 'input[type="url"]', _TEST_YOUTUBE_URL)
            await _safe_click(page, 'button:has-text("Insert")', timeout=3000)
            await _wait(page, _WAIT_FOR_RESPONSE, "YouTube source ingestion")
            await _screenshot(page, "add_youtube_source")

        # ── ADD TEXT SOURCE ────────────────────────────────────────────────
        if _should_run("ADD_TEXT_SOURCE") and test_nb_id:
            capture.set_operation("ADD_TEXT_SOURCE")
            await _wait(page, _OP_DELAY)
            for sel in ['button:has-text("Add source")', '[aria-label="Add source"]']:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            for sel in [
                'button:has-text("Copied text")',
                'li:has-text("Copied text")',
                'button:has-text("Paste")',
                'li:has-text("Paste")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            for sel in ['textarea', 'div[contenteditable="true"]']:
                if await _safe_fill(page, sel, "CosySim test source text. " * 20):
                    break
            await _safe_click(page, 'button:has-text("Insert")', timeout=3000)
            await _wait(page, _WAIT_FOR_RESPONSE, "text source ingestion")
            await _screenshot(page, "add_text_source")
            # Try to get source ID from network events
            for ev in reversed(capture.events):
                for rpc in ev.get("rpcs", []):
                    resp = rpc.get("response")
                    if isinstance(resp, list) and resp and isinstance(resp[0], list):
                        try:
                            test_source_id = resp[0][0][0][0]
                            logger.info("    Source ID: %s", test_source_id)
                        except Exception:
                            pass
                if test_source_id:
                    break

        # ── ASK QUESTION ──────────────────────────────────────────────────
        if _should_run("ASK_QUESTION") and test_nb_id:
            capture.set_operation("ASK_QUESTION")
            await _wait(page, _OP_DELAY)
            for sel in [
                'textarea[placeholder*="Ask"]',
                'textarea[placeholder*="question"]',
                'div[contenteditable][aria-label*="chat"]',
                'textarea.chat-input',
            ]:
                if await _safe_fill(page, sel, _TEST_QUESTION):
                    break
            # Press Enter to send
            try:
                await page.keyboard.press("Enter")
            except Exception:
                await _safe_click(page, 'button[aria-label*="send" i]', timeout=3000)
            await _wait(page, _WAIT_FOR_RESPONSE, "AI response generation")
            await _screenshot(page, "ask_question")

        # ── READ SOURCE CONTENT ───────────────────────────────────────────
        if _should_run("READ_SOURCE") and test_nb_id:
            capture.set_operation("READ_SOURCE")
            await _wait(page, _OP_DELAY)
            # Click any source chip/card to read it
            for sel in [
                '.source-chip',
                '[data-test-id="source-item"]',
                'button.source-item',
                '.source-list-item',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 2.0)
            await _screenshot(page, "read_source")

        # ── GET AI OVERVIEW ───────────────────────────────────────────────
        if _should_run("GET_AI_OVERVIEW") and test_nb_id:
            capture.set_operation("GET_AI_OVERVIEW")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Notebook guide")',
                'button:has-text("Overview")',
                '[aria-label="Notebook guide"]',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "overview generation")
            await _screenshot(page, "ai_overview")

        # ── GENERATE MIND MAP ─────────────────────────────────────────────
        if _should_run("GENERATE_MIND_MAP") and test_nb_id:
            capture.set_operation("GENERATE_MIND_MAP")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Mind map")',
                '[aria-label="Mind map"]',
                'button[title*="mind" i]',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "mind map generation")
            await _screenshot(page, "mind_map")

        # ── GENERATE STUDY GUIDE ──────────────────────────────────────────
        if _should_run("GENERATE_STUDY_GUIDE") and test_nb_id:
            capture.set_operation("GENERATE_STUDY_GUIDE")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Study guide")',
                '[aria-label="Study guide"]',
                'button:has-text("Generate study guide")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "study guide generation")
            await _screenshot(page, "study_guide")

        # ── GENERATE BRIEFING DOC ─────────────────────────────────────────
        if _should_run("GENERATE_BRIEFING") and test_nb_id:
            capture.set_operation("GENERATE_BRIEFING")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Briefing doc")',
                'button:has-text("Briefing")',
                '[aria-label="Briefing doc"]',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "briefing doc generation")
            await _screenshot(page, "briefing_doc")

        # ── GENERATE FAQ ──────────────────────────────────────────────────
        if _should_run("GENERATE_FAQ") and test_nb_id:
            capture.set_operation("GENERATE_FAQ")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("FAQ")',
                '[aria-label="FAQ"]',
                'button:has-text("Frequently asked")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "FAQ generation")
            await _screenshot(page, "faq")

        # ── GENERATE TIMELINE ─────────────────────────────────────────────
        if _should_run("GENERATE_TIMELINE") and test_nb_id:
            capture.set_operation("GENERATE_TIMELINE")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Timeline")',
                '[aria-label="Timeline"]',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _WAIT_FOR_RESPONSE, "timeline generation")
            await _screenshot(page, "timeline")

        # ── CREATE NOTE ───────────────────────────────────────────────────
        if _should_run("CREATE_NOTE") and test_nb_id:
            capture.set_operation("CREATE_NOTE")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Add note")',
                '[aria-label="Add note"]',
                'button.add-note',
                'button:has-text("New note")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            for sel in ['textarea', 'div[contenteditable="true"]']:
                if await _safe_fill(page, sel, _TEST_NOTE_TEXT):
                    break
            await _safe_click(page, 'button:has-text("Save")', timeout=3000)
            await _wait(page, 2.0, "note save")
            await _screenshot(page, "create_note")

        # ── AUDIO OVERVIEW ────────────────────────────────────────────────
        if _should_run("GENERATE_AUDIO_OVERVIEW") and test_nb_id:
            capture.set_operation("GENERATE_AUDIO_OVERVIEW")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Audio Overview")',
                '[aria-label="Audio Overview"]',
                'button:has-text("Generate")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, _LONG_WAIT, "audio overview generation")
            await _screenshot(page, "audio_overview")

        # ── FAST RESEARCH ─────────────────────────────────────────────────
        if _should_run("FAST_RESEARCH") and test_nb_id:
            capture.set_operation("FAST_RESEARCH")
            await _wait(page, _OP_DELAY)
            for sel in [
                'button:has-text("Discover sources")',
                '[aria-label="Discover sources"]',
                'button:has-text("Research")',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.5)
            await _safe_fill(page, 'input[type="search"]', "multi-agent AI systems")
            await _safe_fill(page, 'input[placeholder*="search" i]', "multi-agent AI systems")
            await page.keyboard.press("Enter")
            await _wait(page, _WAIT_FOR_RESPONSE, "fast research")
            await _screenshot(page, "fast_research")

        # ── RENAME NOTEBOOK ───────────────────────────────────────────────
        if _should_run("RENAME_NOTEBOOK") and test_nb_id:
            capture.set_operation("RENAME_NOTEBOOK")
            await _wait(page, _OP_DELAY)
            # Click notebook title to rename
            for sel in [
                '.notebook-title',
                '[aria-label="Notebook title"]',
                'h1.title',
                'span.notebook-name',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 1.0)
            await page.keyboard.press("Control+A")
            await page.keyboard.type(_TEST_NOTEBOOK_TITLE + " (renamed)")
            await page.keyboard.press("Enter")
            await _wait(page, 2.0, "rename save")
            await _screenshot(page, "rename_notebook")

        # ── DELETE SOURCE ─────────────────────────────────────────────────
        if _should_run("DELETE_SOURCE") and test_nb_id:
            capture.set_operation("DELETE_SOURCE")
            await _wait(page, _OP_DELAY)
            # Hover over a source to reveal its menu
            for sel in ['.source-chip', '[data-test-id="source-item"]', '.source-list-item']:
                try:
                    el = page.locator(sel).last
                    await el.hover(timeout=3000)
                    break
                except Exception:
                    pass
            await _wait(page, 0.5)
            # Click the kebab/more menu
            for sel in [
                'button[aria-label="More options"]',
                'button[aria-label*="more" i]',
                'button.more-menu',
                '[aria-label="Delete source"]',
            ]:
                if await _safe_click(page, sel, timeout=2000):
                    break
            await _wait(page, 0.5)
            for sel in ['button:has-text("Delete")', 'li:has-text("Delete")']:
                if await _safe_click(page, sel, timeout=2000):
                    break
            # Confirm delete dialog
            await _wait(page, 1.0)
            for sel in ['button:has-text("Delete")', 'button:has-text("Confirm")']:
                if await _safe_click(page, sel, timeout=2000):
                    break
            await _wait(page, 2.0, "source delete")
            await _screenshot(page, "delete_source")

        # ── DELETE NOTEBOOK ───────────────────────────────────────────────
        if _should_run("DELETE_NOTEBOOK") and test_nb_id:
            capture.set_operation("DELETE_NOTEBOOK")
            await _wait(page, _OP_DELAY)
            # Navigate to home to use the notebook list
            await page.goto(_NLM_URL, wait_until="networkidle")
            await _wait(page, _WAIT_AFTER_NAV)
            # Find the test notebook and click its menu
            for sel in [
                f'[aria-label*="{_TEST_NOTEBOOK_TITLE}" i] button',
                'button[aria-label="More actions"]',
                '.notebook-card button.kebab',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 0.5)
            for sel in ['button:has-text("Delete")', 'li:has-text("Delete notebook")']:
                if await _safe_click(page, sel, timeout=2000):
                    break
            await _wait(page, 1.0)
            for sel in ['button:has-text("Delete")', 'button:has-text("Confirm")']:
                if await _safe_click(page, sel, timeout=2000):
                    break
            await _wait(page, 2.0, "notebook delete")
            await _screenshot(page, "delete_notebook")

        # ── SHARE NOTEBOOK ────────────────────────────────────────────────
        if _should_run("SHARE_NOTEBOOK") and test_nb_id:
            capture.set_operation("SHARE_NOTEBOOK")
            await _wait(page, _OP_DELAY)
            for sel in ['button:has-text("Share")', '[aria-label="Share"]']:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 2.0, "share dialog")
            await _screenshot(page, "share_notebook")
            # Close dialog
            await _safe_click(page, 'button[aria-label="Close"]', timeout=2000)

        # ── GET USER QUOTA ────────────────────────────────────────────────
        if _should_run("GET_USER_QUOTA"):
            capture.set_operation("GET_USER_QUOTA")
            await _wait(page, _OP_DELAY)
            # Navigate to settings/profile if accessible
            for sel in [
                '[aria-label="Account"]',
                'img[aria-label*="Google Account"]',
                '.profile-button',
            ]:
                if await _safe_click(page, sel, timeout=3000):
                    break
            await _wait(page, 2.0)
            await _screenshot(page, "user_quota")
            await page.keyboard.press("Escape")

        await _wait(page, 2.0, "final capture flush")
        await _screenshot(page, "final_state")
        await ctx.close()

    capture.save(output)
    logger.info("Automation complete. %d events captured.", len(capture.events))
    return capture


def analyze_capture(log_path: Path) -> Dict[str, Any]:
    """
    Analyze a saved automation log and return the operation→RPC map.

    Also identifies new RPCs not in the existing registry.
    """
    with open(log_path, encoding="utf-8") as f:
        events = json.load(f)

    # Build op → RPC map
    op_rpcs: Dict[str, List[str]] = {}
    all_rpcs: set = set()
    endpoint_map: Dict[str, List[str]] = {}

    for ev in events:
        if ev.get("direction") != "request":
            continue
        op = ev.get("operation", "UNKNOWN")
        rpc = ev.get("rpc_id", "")
        if not rpc:
            continue
        for r in rpc.split(";"):
            r = r.strip()
            if not r:
                continue
            all_rpcs.add(r)
            op_rpcs.setdefault(op, [])
            if r not in op_rpcs[op]:
                op_rpcs[op].append(r)
        etype = ev.get("endpoint_type", "other")
        endpoint_map.setdefault(etype, [])
        if rpc not in endpoint_map[etype]:
            endpoint_map[etype].append(rpc)

    # Compare against existing registry
    existing_registry = _load_registry()
    known_rpcs = set(existing_registry.get("rpc_ids", {}).values())
    new_rpcs = all_rpcs - known_rpcs

    result = {
        "total_events": len(events),
        "total_unique_rpcs": len(all_rpcs),
        "new_rpcs": sorted(new_rpcs),
        "operation_to_rpcs": op_rpcs,
        "endpoint_types": endpoint_map,
        "all_rpcs": sorted(all_rpcs),
    }

    logger.info("Analysis: %d unique RPCs, %d NEW: %s",
                len(all_rpcs), len(new_rpcs), list(new_rpcs))
    return result


def _load_registry() -> Dict[str, Any]:
    if _REGISTRY_FILE.exists():
        with open(_REGISTRY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"rpc_ids": {}, "updated_at": None}


def update_registry(analysis: Dict[str, Any], bl: Optional[str] = None) -> Dict[str, Any]:
    """Merge analysis results into the RPC registry."""
    registry = _load_registry()
    op_rpcs = analysis.get("operation_to_rpcs", {})

    # Update rpc_ids mapping: operation → primary RPC ID
    for op, rpcs in op_rpcs.items():
        if rpcs:
            registry["rpc_ids"][op] = rpcs[0]  # first RPC is the primary
            if len(rpcs) > 1:
                registry.setdefault("rpc_ids_secondary", {})[op] = rpcs[1:]

    registry["updated_at"] = datetime.now().isoformat()
    registry["bl"] = bl or registry.get("bl", "unknown")
    registry["all_rpcs_seen"] = analysis.get("all_rpcs", [])

    _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)

    logger.info("Registry updated: %d operations mapped", len(op_rpcs))
    return registry


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="NLM automation runner")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--ops", help="Comma-separated op names to run (default: all)")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--analyze-only", help="Analyze existing log (path)")
    args = parser.parse_args()

    if args.analyze_only:
        result = analyze_capture(Path(args.analyze_only))
        print(json.dumps(result, indent=2))
        sys.exit(0)

    ops_filter = args.ops.split(",") if args.ops else None
    output = Path(args.output) if args.output else None

    capture = asyncio.run(run_automation(
        headless=args.headless,
        ops_filter=ops_filter,
        output=output,
    ))

    analysis = analyze_capture(output or _LOG_FILE)
    update_registry(analysis)

    print("\n=== RESULTS ===")
    print(f"Total events: {analysis['total_events']}")
    print(f"Unique RPCs:  {analysis['total_unique_rpcs']}")
    print(f"NEW RPCs:     {analysis['new_rpcs']}")
    print("\nOperation → RPC mapping:")
    for op, rpcs in analysis["operation_to_rpcs"].items():
        print(f"  {op:<30} → {', '.join(rpcs)}")
