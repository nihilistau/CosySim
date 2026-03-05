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
# Ensure project root is on path so scripts.argus and engine imports work
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
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
            # Navigate to NLM home so "Create new notebook" is available.
            page = await crawler.get_or_open_page("notebooklm", NLM_URL)
            if "/notebook/" in page.url:
                logger.info("On notebook page — navigating to NLM home first")
                await page.goto(NLM_URL, wait_until="networkidle", timeout=30000)

            await page.wait_for_load_state("networkidle", timeout=20000)

            if "accounts.google.com" in page.url:
                logger.error("Redirected to login — log into NLM in Chrome first")
                return None

            # Click "Create new notebook" → NLM immediately opens a new notebook
            # with the add-source dialog visible (URL ends in ?addSource=true).
            await self._step("new_notebook", page, self._click_new_notebook)
            # Wait for the new notebook URL to settle
            await page.wait_for_url("**/notebook/**", timeout=15000)
            await page.wait_for_timeout(1500)
            self.notebook_url = page.url.split("?")[0]
            logger.info("Notebook: %s", self.notebook_url)

            # The add-source dialog is already open at this point; just click Copied text.
            await self._step("select_copied_text", page, self._click_copied_text)
            await self._step("paste_text",         page, self._paste_content)
            await self._step("insert",             page, self._insert_source)

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
