"""Ingest a local file into a new NotebookLM notebook.

Uses the ARGUS BaseCrawler (CDP attach + NetworkMonitor) so all the
Playwright / Chrome plumbing is already handled.  Captures every
batchexecute call to HAR so we can later call NLM directly without a browser.

Usage:
    python scripts/nlm_ingest.py                           # PROJECT_JOURNAL.md
    python scripts/nlm_ingest.py --file docs/ARGUS.md --name "ARGUS Docs"
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
NLM_URL      = "https://notebooklm.google.com"


# ──── Crawler ─────────────────────────────────────────────────────────────────

class NLMIngestCrawler:
    """Drive the NLM create-notebook + add-source flow via ARGUS BaseCrawler."""

    def __init__(self, notebook_name: str, content: str) -> None:
        self.notebook_name = notebook_name
        self.content       = content
        self.notebook_url: str | None = None

    async def run(self) -> str | None:
        from scripts.argus.crawlers.base_crawler import BaseCrawler
        from scripts.argus.network_monitor import NetworkMonitor

        monitor = NetworkMonitor()
        crawler = BaseCrawler(monitor=monitor)

        async with crawler:
            page = await crawler.get_or_open_page("notebooklm", NLM_URL)
            await page.wait_for_load_state("networkidle", timeout=20000)

            if "accounts.google.com" in page.url:
                logger.error("Redirected to login — log into NLM in Chrome first")
                return None

            await self._step("new_notebook",   page, self._click_new_notebook)
            await self._step("set_title",      page, self._set_title)
            await self._step("confirm_create", page, self._confirm_create)
            self.notebook_url = page.url
            logger.info("Notebook: %s", self.notebook_url)

            await self._step("add_source",  page, self._add_source)
            await self._step("paste_text",  page, self._paste_content)
            await self._step("insert",      page, self._insert_source)

            self._save_har(monitor)

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
        for sel in ["button:has-text('New notebook')", "[aria-label='New notebook']"]:
            try:
                await page.click(sel, timeout=8000)
                await page.wait_for_timeout(1500)
                return
            except Exception:
                continue
        raise RuntimeError("'New notebook' button not found")

    async def _set_title(self, page) -> None:
        for sel in ["input[placeholder*='Untitled']", "input[aria-label*='title']", "input"]:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                await el.triple_click()
                await el.type(self.notebook_name, delay=25)
                await page.wait_for_timeout(400)
                return
            except Exception:
                continue

    async def _confirm_create(self, page) -> None:
        for sel in ["button:has-text('Create')", "button[type='submit']"]:
            try:
                await page.click(sel, timeout=5000)
                await page.wait_for_timeout(3000)
                return
            except Exception:
                continue
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

    async def _add_source(self, page) -> None:
        for sel in ["button:has-text('Add source')", "[aria-label='Add source']"]:
            try:
                await page.click(sel, timeout=8000)
                await page.wait_for_timeout(1500)
                return
            except Exception:
                continue
        raise RuntimeError("'Add source' button not found")

    async def _paste_content(self, page) -> None:
        for sel in ["button:has-text('Copied text')", "li:has-text('Copied text')",
                    "button:has-text('Paste text')"]:
            try:
                await page.click(sel, timeout=5000)
                await page.wait_for_timeout(1000)
                break
            except Exception:
                continue
        # JS value injection — instant even for large files
        await page.evaluate(
            """([val]) => {
                const el = document.querySelector('textarea');
                if (!el) return;
                Object.getOwnPropertyDescriptor(
                    HTMLTextAreaElement.prototype, 'value'
                ).set.call(el, val);
                el.dispatchEvent(new Event('input',  {bubbles: true}));
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

    # ──── HAR dump ──────────────────────────────────────────────────────────

    def _save_har(self, monitor) -> None:
        from scripts.argus.config import DATA_DIR

        har_dir = DATA_DIR / "har"
        har_dir.mkdir(parents=True, exist_ok=True)
        har_path = har_dir / f"nlm_ingest_{int(time.time())}.har"

        entries = []
        for req in monitor.drain():
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

    url = await NLMIngestCrawler(name, content).run()

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
    sys.exit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()
