"""Automate NotebookLM notebook creation with built-in HAR capture.

Attaches to your running Chrome, drives the NLM UI to create a notebook
and add a source, records every network request to a HAR file, then
parses out the batchexecute payloads so future calls skip the browser entirely.

Usage:
    python scripts/nlm_ingest.py                          # ingest PROJECT_JOURNAL.md
    python scripts/nlm_ingest.py --file docs/ARGUS.md --name "ARGUS Docs"
    python scripts/nlm_ingest.py --no-cdp                 # launch fresh browser
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
HAR_OUT      = PROJECT_ROOT / "data" / "har_files"
NLM_URL      = "https://notebooklm.google.com"
CDP_URL      = "http://localhost:9222"


# ──── Selectors (aria-stable where possible) ──────────────────────────────────

NEW_NB       = ["button:has-text('New notebook')", "[aria-label='New notebook']"]
TITLE_INPUT  = ["input[placeholder*='Untitled']", "input[aria-label*='title']", "input[name='title']"]
CONFIRM      = ["button:has-text('Create')", "button[type='submit']"]
ADD_SOURCE   = ["button:has-text('Add source')", "[aria-label='Add source']"]
PASTE_OPT    = ["button:has-text('Copied text')", "li:has-text('Copied text')", "button:has-text('Paste text')"]
TEXTAREA     = ["textarea"]
INSERT       = ["button:has-text('Insert')", "button:has-text('Add')", "button[type='submit']"]


async def _click(page, selectors: list[str], timeout=8000) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                await el.click()
                return True
        except Exception:
            continue
    return False


async def _find(page, selectors: list[str], timeout=5000):
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except Exception:
            continue
    return None


# ──── Main automation ─────────────────────────────────────────────────────────

async def run(notebook_name: str, content: str, source_filename: str, use_cdp: bool) -> dict:
    """Drive NLM, capture HAR, return result dict."""
    from playwright.async_api import async_playwright

    HAR_OUT.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    har_path = HAR_OUT / f"nlm_create_{ts}.har"

    async with async_playwright() as pw:
        browser = None
        context = None
        owned = False                         # did we launch this browser?

        # ── Attach to running Chrome (has live NLM session) ──────────────────
        if use_cdp:
            try:
                browser = await pw.chromium.connect_over_cdp(CDP_URL)
                # Wrap the existing context so we can record HAR on a new page
                context = await browser.contexts[0].browser.new_context(
                    record_har_path=str(har_path),
                    record_har_url_filter="*notebooklm*",
                )
                # Copy cookies from the live context into the new recording one
                live_cookies = await browser.contexts[0].cookies()
                await context.add_cookies(live_cookies)
                owned = True
                logger.info("Attached to Chrome via CDP, copied %d cookies", len(live_cookies))
            except Exception as e:
                logger.info("CDP failed (%s) — launching fresh browser", e)
                browser = None

        # ── Launch fresh browser with pool cookies ────────────────────────────
        if browser is None:
            browser = await pw.chromium.launch(headless=False)
            owned = True
            context = await browser.new_context(
                record_har_path=str(har_path),
                record_har_url_filter="*notebooklm*",
                viewport={"width": 1280, "height": 900},
            )
            # Inject Google cookies from pool
            try:
                sys.path.insert(0, str(PROJECT_ROOT))
                from engine.integrations.google_account_pool import GoogleAccountPool
                pool = GoogleAccountPool()
                for acct in pool.get_available_accounts("notebooklm"):
                    if any(k in acct.cookies for k in ("SAPISID", "APISID")):
                        cookies = [
                            {"name": k, "value": str(v), "domain": ".google.com",
                             "path": "/", "secure": True, "sameSite": "None"}
                            for k, v in acct.cookies.items()
                        ]
                        await context.add_cookies(cookies)
                        logger.info("Injected %d cookies from %s", len(cookies), acct.name)
                        break
            except Exception as e:
                logger.warning("No pool cookies: %s", e)

        result = {"notebook_url": None, "har_path": str(har_path), "error": None}

        try:
            page = await context.new_page()
            logger.info("→ notebooklm.google.com")
            await page.goto(NLM_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            if "accounts.google.com" in page.url:
                result["error"] = "Redirected to login — cookies expired. Re-login in Chrome first."
                return result

            # ── Create notebook ───────────────────────────────────────────────
            logger.info("Clicking 'New notebook'...")
            if not await _click(page, NEW_NB, timeout=10000):
                result["error"] = "Could not find 'New notebook' button"
                return result
            await page.wait_for_timeout(1500)

            title_el = await _find(page, TITLE_INPUT)
            if title_el:
                await title_el.triple_click()
                await title_el.type(notebook_name, delay=25)
                await page.wait_for_timeout(400)

            await _click(page, CONFIRM, timeout=5000) or await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)

            notebook_url = page.url
            logger.info("Notebook created: %s", notebook_url)
            result["notebook_url"] = notebook_url

            # ── Add source ────────────────────────────────────────────────────
            logger.info("Adding source (%d chars)...", len(content))
            if not await _click(page, ADD_SOURCE, timeout=8000):
                logger.warning("No 'Add source' button — notebook created but source not added")
                return result
            await page.wait_for_timeout(1500)

            if not await _click(page, PASTE_OPT, timeout=5000):
                logger.warning("No 'Copied text' option found")
                return result
            await page.wait_for_timeout(1000)

            textarea = await _find(page, TEXTAREA)
            if textarea:
                await textarea.click()
                # Set value via JS (fast for large content)
                await page.evaluate(
                    """([val]) => {
                        const el = document.querySelector('textarea');
                        const setter = Object.getOwnPropertyDescriptor(
                            HTMLTextAreaElement.prototype, 'value').set;
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    }""",
                    [content[:500_000]],
                )
                await page.wait_for_timeout(800)

            await _click(page, INSERT, timeout=5000)
            await page.wait_for_timeout(5000)   # let source process
            logger.info("Source inserted")

        except Exception as e:
            result["error"] = str(e)
            logger.error("Automation error: %s", e, exc_info=True)
        finally:
            await context.close()              # flushes HAR to disk
            if owned and browser:
                await browser.close()

    # ── Parse HAR for batchexecute payloads ───────────────────────────────────
    if har_path.exists():
        _extract_and_log_payloads(har_path)

    return result


def _extract_and_log_payloads(har_path: Path) -> None:
    """Parse the captured HAR and log any NLM batchexecute calls found."""
    try:
        har = json.loads(har_path.read_text(encoding="utf-8"))
        entries = har.get("log", {}).get("entries", [])
        found = 0
        for entry in entries:
            url = entry.get("request", {}).get("url", "")
            if "batchexecute" not in url and "LabsTailwindUi" not in url:
                continue
            post = entry.get("request", {}).get("postData", {}).get("text", "")
            if not post:
                continue
            decoded = urllib.parse.unquote(post.replace("f.req=", ""))
            response_body = entry.get("response", {}).get("content", {}).get("text", "")
            logger.info("NLM call captured:\n  URL: %s\n  REQ: %s\n  RES: %s",
                        url[:120], decoded[:200], response_body[:200])
            found += 1
        logger.info("HAR: %d NLM batchexecute calls captured → %s", found, har_path)
    except Exception as e:
        logger.warning("HAR parse error: %s", e)


def _store_in_nexus(notebook_url: str, notebook_name: str) -> None:
    try:
        import requests as req
        req.post(
            "http://localhost:8700/api/entries",
            json={
                "title": f"NLM Notebook: {notebook_name}",
                "content": f"URL: {notebook_url}\nSource: docs/PROJECT_JOURNAL.md",
                "content_type": "note",
                "category": "architecture",
                "tags": ["notebooklm", "notebook"],
            },
            timeout=10,
        )
        logger.info("Stored in Nexus")
    except Exception as e:
        logger.warning("Nexus store failed: %s", e)


# ──── CLI ─────────────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> int:
    source_path = Path(args.file)
    if not source_path.exists():
        print(f"ERROR: {source_path} not found")
        return 1

    content = source_path.read_text(encoding="utf-8")
    name    = args.name or source_path.stem.replace("_", " ").title()

    print(f"File   : {source_path} ({len(content):,} chars)")
    print(f"Notebook: {name}")
    print()

    result = await run(name, content, source_path.name, use_cdp=not args.no_cdp)

    if result["notebook_url"]:
        print(f"\n✓  {result['notebook_url']}")
        print(f"   HAR saved → {result['har_path']}")
        _store_in_nexus(result["notebook_url"], name)
        return 0
    else:
        print(f"\n✗  {result['error']}")
        print(f"   HAR (partial) → {result['har_path']}")
        return 1


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser()
    p.add_argument("--file",   default=str(PROJECT_ROOT / "docs" / "PROJECT_JOURNAL.md"))
    p.add_argument("--name",   default="CosySim Project Journal & Onboarding")
    p.add_argument("--no-cdp", action="store_true")
    sys.exit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()
