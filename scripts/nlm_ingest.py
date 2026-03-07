"""Ingest a local file into a NotebookLM notebook.

Uses the ARGUS BaseCrawler (CDP attach + NetworkMonitor) so all the
Playwright / Chrome plumbing is already handled.  Captures every
batchexecute call to HAR so we can later call NLM directly without a browser.

Usage:
    python scripts/nlm_ingest.py                           # PROJECT_JOURNAL.md
    python scripts/nlm_ingest.py --file docs/ARGUS.md --name "ARGUS Docs"
    python scripts/nlm_ingest.py --file docs/ARGUS.md --name "ARGUS Docs" --notebook-url https://notebooklm.google.com/notebook/...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
# Ensure project root is on path so scripts.argus and engine imports work
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
NLM_URL      = "https://notebooklm.google.com"


# ──── Crawler ─────────────────────────────────────────────────────────────────

class NLMIngestCrawler:
    """Drive NotebookLM create-notebook + add-source flows via ARGUS BaseCrawler."""

    def __init__(self, notebook_name: str, content: str, notebook_url: str | None = None) -> None:
        self.notebook_name = notebook_name
        self.content       = content
        self.notebook_url  = notebook_url

    async def run(self) -> str | None:
        from scripts.argus.crawlers.base_crawler import BaseCrawler
        from scripts.argus.network_monitor import NetworkMonitor

        monitor = NetworkMonitor()
        crawler = BaseCrawler(monitor=monitor)

        async with crawler:
            target_url = self.notebook_url or NLM_URL
            page = await crawler.get_or_open_page("notebooklm", target_url)

            if self.notebook_url:
                logger.info("Opening existing notebook for ingest: %s", self.notebook_url)
                if self.notebook_url not in page.url:
                    await page.goto(self.notebook_url, wait_until="domcontentloaded", timeout=30000)
                await self._wait_for_notebook_ready(page)
            else:
                # Navigate to NLM home so "Create new notebook" is available.
                if "/notebook/" in page.url:
                    logger.info("On notebook page — navigating to NLM home first")
                    await page.goto(NLM_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=20000)

            if "accounts.google.com" in page.url:
                logger.error("Redirected to login — log into NLM in Chrome first")
                return None

            if self.notebook_url:
                self.notebook_url = page.url.split("?")[0]
                await self._step("open_add_source", page, self._open_add_source_dialog)
            else:
                # Click "Create new notebook" → NLM immediately opens a new notebook
                # with the add-source dialog visible (URL ends in ?addSource=true).
                await self._step("new_notebook", page, self._click_new_notebook)
                # Wait for the new notebook URL to settle
                await page.wait_for_url("**/notebook/**", timeout=15000)
                await page.wait_for_timeout(1500)
                self.notebook_url = page.url.split("?")[0]
                logger.info("Notebook: %s", self.notebook_url)

            await self._step("select_copied_text", page, self._click_copied_text)
            await self._step("paste_text",         page, self._paste_content)
            await self._step("insert",             page, self._insert_source)
            await self._step("set_title",          page, self._set_notebook_title)

            await self._save_har(monitor)

        return self.notebook_url

    async def _step(self, name: str, page, fn) -> None:
        """Run one UI action, log it."""
        logger.info("→ %s", name)
        try:
            await fn(page)
        except Exception as e:
            logger.warning("Step %s failed: %s", name, e)

    # ──── UI actions ────────────────────────────────────────────────────────

    async def _click_new_notebook(self, page) -> None:
        for sel in [
            "button[aria-label='Create new notebook']",
            "[aria-label='Create new notebook']",
            "[aria-label='Create notebook']",
            "button:has-text('Create new')",
            "button:has-text('Create notebook')",
        ]:
            try:
                await page.click(sel, timeout=10000)
                await page.wait_for_timeout(2000)
                return
            except Exception:
                continue
        raise RuntimeError("'Create new notebook' button not found on NLM home")

    async def _open_add_source_dialog(self, page) -> None:
        """Open the add-source dialog for an existing notebook."""
        if await page.locator("textarea.copied-text-input-textarea").count():
            return

        for sel in [
            "button[aria-label='Add source']",
            "button[aria-label='Add sources']",
            "button.add-source-button",
            "button:has-text('Add sources')",
            "button:has-text('Upload a source')",
        ]:
            try:
                await page.click(sel, timeout=10000)
                await page.wait_for_timeout(1500)
                return
            except Exception:
                continue
        raise RuntimeError("'Add source' button not found on notebook page")

    async def _wait_for_notebook_ready(self, page) -> None:
        """Wait for an existing notebook page to become interactive."""
        for sel in [
            "button[aria-label='Add source']",
            "button[aria-label='Add sources']",
            "button.add-source-button",
            "input.title-input",
            "textarea[aria-label='Query box']",
        ]:
            try:
                await page.wait_for_selector(sel, timeout=20000, state="visible")
                return
            except Exception:
                continue
        raise RuntimeError("Notebook page did not become interactive")

    async def _click_copied_text(self, page) -> None:
        """Click the 'Copied text' option in the add-source dialog."""
        for sel in [
            "button:has-text('Copied text')",
            "li:has-text('Copied text')",
            "[aria-label*='Copied text']",
        ]:
            try:
                await page.click(sel, timeout=8000)
                await page.wait_for_timeout(1000)
                return
            except Exception:
                continue
        raise RuntimeError("'Copied text' tab not found in add-source dialog")

    async def _paste_content(self, page) -> None:
        # Angular-compatible: use native input setter + InputEvent so the form control validates
        await page.evaluate(
            """([val]) => {
                const el = document.querySelector('textarea.copied-text-input-textarea')
                         || document.querySelector('textarea');
                if (!el) return;
                const proto = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                proto.set.call(el, val);
                el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: val}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            [self.content[:500_000]],
        )
        await page.wait_for_timeout(800)

    async def _insert_source(self, page) -> None:
        for sel in ["button:has-text('Insert')", "button:has-text('Add')"]:
            try:
                await page.click(sel, timeout=5000)
                await page.wait_for_timeout(5000)
                return
            except Exception:
                continue
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

    async def _set_notebook_title(self, page) -> None:
        """Apply the requested notebook title once the add-source dialog closes."""
        if not self.notebook_name:
            return

        for sel in [
            "input.title-input",
            "input[aria-label*='title']",
            "input[name='title']",
        ]:
            try:
                await page.wait_for_selector(sel, timeout=8000, state="visible")
                await page.click(sel, timeout=5000)
                await page.fill(sel, self.notebook_name, timeout=5000)
                await page.keyboard.press("Tab")
                await page.wait_for_timeout(1000)
                logger.info("Notebook title set: %s", self.notebook_name)
                return
            except Exception:
                continue

        raise RuntimeError("Notebook title input not found")

    # ──── HAR dump ──────────────────────────────────────────────────────────

    async def _save_har(self, monitor) -> None:
        from scripts.argus.config import DATA_DIR

        har_dir = DATA_DIR / "har"
        har_dir.mkdir(parents=True, exist_ok=True)
        har_path = har_dir / f"nlm_ingest_{int(time.time())}.har"

        entries = []
        for req in await monitor.drain():
            if "notebooklm" not in req.url:
                continue
            entries.append({
                "request":  {"url": req.url, "method": req.method,
                             "postData": {"text": req.post_data or ""}},
                "response": {"content": {"text": req.response_body or ""}},
            })
            if req.post_data:
                decoded = urllib.parse.unquote(req.post_data.replace("f.req=", ""))
                if any(rpc in decoded for rpc in ("VqhFhd", "PoHVkb", "wIlBFe")):
                    logger.info("batchexecute captured: %s", decoded[:200])

        har_path.write_text(json.dumps({"log": {"version": "1.2", "entries": entries}},
                                       indent=2), encoding="utf-8")
        logger.info("HAR → %s (%d NLM entries)", har_path, len(entries))


# ──── Nexus ───────────────────────────────────────────────────────────────────

def _store_in_nexus(url: str, name: str) -> None:
    try:
        import requests as req
        req.post("http://localhost:8700/api/entries", json={
            "title":        f"NLM Notebook: {name}",
            "content":      f"URL: {url}",
            "content_type": "note",
            "category":     "architecture",
            "tags":         ["notebooklm", "notebook"],
        }, timeout=10)
        logger.info("Stored in Nexus")
    except Exception as e:
        logger.warning("Nexus: %s", e)


# ──── CLI ─────────────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.exists():
        print(f"ERROR: {src} not found"); return 1

    content = src.read_text(encoding="utf-8")
    name    = args.name or src.stem.replace("_", " ").title()
    print(f"File    : {src} ({len(content):,} chars)\nNotebook: {name}\n")

    url = await NLMIngestCrawler(name, content, notebook_url=args.notebook_url).run()

    if url and "notebooklm" in url:
        print(f"\n✓  {url}")
        _store_in_nexus(url, name)
        return 0

    print("\n✗  Failed — make sure Chrome is open and logged into notebooklm.google.com")
    return 1


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Ingest a file into NotebookLM via ARGUS crawler")
    p.add_argument("--file", default=str(PROJECT_ROOT / "docs" / "PROJECT_JOURNAL.md"))
    p.add_argument("--name", default="CosySim Project Journal & Onboarding")
    p.add_argument("--notebook-url", default=None, help="Add the file to an existing NotebookLM notebook URL")
    sys.exit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()
