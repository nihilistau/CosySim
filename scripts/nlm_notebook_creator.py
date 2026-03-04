"""NLM Notebook Creator — Playwright automation for NotebookLM.

Connects to running Chrome via CDP (if available) or launches a new browser
with injected Google cookies from the account pool. Automates:
  - Navigating to notebooklm.google.com
  - Creating a new notebook
  - Adding a text source (pasted content)
  - Returning the notebook URL

Usage:
    # Upload project journal
    python scripts/nlm_notebook_creator.py

    # Upload any file
    python scripts/nlm_notebook_creator.py --file docs/ARGUS.md --name "ARGUS Docs"

    # Non-interactive headless mode
    python scripts/nlm_notebook_creator.py --headless
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ──── Constants ──────────────────────────────────────────────────────────────

NLM_URL = "https://notebooklm.google.com"
CDP_URL = "http://localhost:9222"
PROJECT_ROOT = Path(__file__).parent.parent

# Selectors — verified against NLM DOM as of 2026-03
# These are the stable aria/data-test attributes where possible
SEL_NEW_NOTEBOOK_BTN = [
    "button:has-text('New notebook')",
    "[aria-label='New notebook']",
    "[data-test='new-notebook-button']",
    "button:has-text('Create')",
]
SEL_NOTEBOOK_TITLE_INPUT = [
    "input[placeholder*='Untitled']",
    "input[aria-label*='title']",
    "[contenteditable][aria-label*='title']",
    "input[name='title']",
]
SEL_CONFIRM_CREATE = [
    "button:has-text('Create')",
    "button[type='submit']",
]
SEL_ADD_SOURCE_BTN = [
    "button:has-text('Add source')",
    "[aria-label='Add source']",
    "button:has-text('+')",
]
SEL_PASTE_TEXT_OPTION = [
    "button:has-text('Copied text')",
    "li:has-text('Copied text')",
    "button:has-text('Paste')",
    "[data-source-type='text']",
]
SEL_TEXT_PASTE_AREA = [
    "textarea[placeholder*='Paste']",
    "textarea[aria-label*='text']",
    "textarea",
]
SEL_INSERT_SOURCE_BTN = [
    "button:has-text('Insert')",
    "button:has-text('Add')",
    "button[type='submit']:has-text('Insert')",
]
SEL_SOURCE_LOADING = [
    ".source-loading",
    "[aria-label='Processing source']",
]


# ──── Cookie injection ────────────────────────────────────────────────────────

def _get_google_cookies() -> list[dict]:
    """Load Google cookies for notebooklm from the account pool."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from engine.integrations.google_account_pool import GoogleAccountPool
        pool = GoogleAccountPool()
        accounts = pool.get_available_accounts("notebooklm")
        # Prefer account with proper Google cookies
        for account in accounts:
            if any(k in account.cookies for k in ("SAPISID", "APISID", "__Secure-1PSID")):
                logger.info("Using Google account: %s", account.name)
                # Convert dict cookies → Playwright format
                playwright_cookies = []
                for name, value in account.cookies.items():
                    playwright_cookies.append({
                        "name": name,
                        "value": str(value),
                        "domain": ".google.com",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "None",
                    })
                return playwright_cookies
    except Exception as e:
        logger.warning("Could not load account pool cookies: %s", e)
    return []


# ──── Core automation ─────────────────────────────────────────────────────────

async def _try_selector(page, selectors: list[str], timeout: int = 5000):
    """Try multiple selectors, return the first visible element found."""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except Exception:
            continue
    return None


async def _click_first(page, selectors: list[str], timeout: int = 5000) -> bool:
    """Click the first matching selector."""
    el = await _try_selector(page, selectors, timeout)
    if el:
        await el.click()
        return True
    return False


async def create_notebook_with_source(
    notebook_name: str,
    source_content: str,
    source_title: str = "source.md",
    headless: bool = True,
    use_cdp: bool = True,
) -> Optional[str]:
    """Create a NotebookLM notebook and add a text source.

    Args:
        notebook_name: Display name for the new notebook.
        source_content: Text content to add as a source.
        source_title: Descriptive title for the source.
        headless: Run browser headlessly.
        use_cdp: Prefer attaching to running Chrome over launching new.

    Returns:
        Notebook URL string, or None on failure.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = None
        context = None
        attached = False

        # ── Try CDP attach first (uses existing Chrome session with NLM cookies) ──
        if use_cdp:
            try:
                browser = await pw.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else None
                if context:
                    attached = True
                    logger.info("Attached to existing Chrome via CDP")
            except Exception as e:
                logger.info("CDP attach failed (%s), launching new browser", e)

        # ── Launch new browser with injected cookies ──
        if not attached:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            # Inject cookies before navigating
            cookies = _get_google_cookies()
            if cookies:
                await context.add_cookies(cookies)
                logger.info("Injected %d Google cookies", len(cookies))
            else:
                logger.warning("No Google cookies found — NLM may require login")

        try:
            # ── Navigate to NotebookLM ──
            page = await context.new_page()
            logger.info("Navigating to NotebookLM...")
            await page.goto(NLM_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Check if we're logged in
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url:
                logger.error("NLM redirected to Google login — cookies invalid or expired")
                await _capture_screenshot(page, "nlm_login_redirect")
                return None

            logger.info("On NLM homepage: %s", current_url)
            await _capture_screenshot(page, "nlm_home")

            # ── Click 'New notebook' ──
            logger.info("Looking for 'New notebook' button...")
            clicked = await _click_first(page, SEL_NEW_NOTEBOOK_BTN, timeout=8000)
            if not clicked:
                # Try scrolling up first
                await page.keyboard.press("Home")
                await page.wait_for_timeout(1000)
                clicked = await _click_first(page, SEL_NEW_NOTEBOOK_BTN, timeout=5000)

            if not clicked:
                logger.error("Could not find 'New notebook' button")
                await _capture_screenshot(page, "nlm_no_new_btn")
                return None

            await page.wait_for_timeout(1500)
            await _capture_screenshot(page, "nlm_new_dialog")

            # ── Set notebook title ──
            title_el = await _try_selector(page, SEL_NOTEBOOK_TITLE_INPUT, timeout=5000)
            if title_el:
                await title_el.triple_click()
                await title_el.type(notebook_name, delay=30)
                await page.wait_for_timeout(500)
                logger.info("Set notebook title: %s", notebook_name)
            else:
                logger.warning("Could not find title input — using default name")

            # ── Confirm creation ──
            confirmed = await _click_first(page, SEL_CONFIRM_CREATE, timeout=5000)
            if not confirmed:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            await _capture_screenshot(page, "nlm_notebook_created")

            # Capture the new notebook URL
            notebook_url = page.url
            logger.info("Notebook URL: %s", notebook_url)

            # ── Add the text source ──
            logger.info("Adding text source (%d chars)...", len(source_content))
            source_added = await _add_text_source(page, source_content, source_title)
            if not source_added:
                logger.warning("Source add failed but notebook was created: %s", notebook_url)

            return notebook_url

        except Exception as e:
            logger.error("Automation error: %s", e, exc_info=True)
            try:
                await _capture_screenshot(page, "nlm_error")
            except Exception:
                pass
            return None
        finally:
            if not attached and browser:
                await browser.close()


async def _add_text_source(page, content: str, title: str) -> bool:
    """Add a text paste source to an open notebook."""
    # Click 'Add source'
    clicked = await _click_first(page, SEL_ADD_SOURCE_BTN, timeout=8000)
    if not clicked:
        logger.error("Could not find 'Add source' button")
        return False

    await page.wait_for_timeout(1500)
    await _capture_screenshot(page, "nlm_add_source_menu")

    # Select 'Copied text' option
    clicked = await _click_first(page, SEL_PASTE_TEXT_OPTION, timeout=5000)
    if not clicked:
        logger.error("Could not find 'Copied text' option")
        return False

    await page.wait_for_timeout(1500)
    await _capture_screenshot(page, "nlm_paste_dialog")

    # Find the textarea and paste content
    text_area = await _try_selector(page, SEL_TEXT_PASTE_AREA, timeout=5000)
    if not text_area:
        logger.error("Could not find text paste area")
        return False

    # Use clipboard paste for speed (much faster than type for large content)
    await text_area.click()
    await page.evaluate(
        f"navigator.clipboard.writeText({repr(content[:500_000])})"
    )
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Control+v")
    await page.wait_for_timeout(1000)

    # If clipboard API fails, fall back to JS value set
    typed_val = await page.evaluate("document.activeElement.value")
    if not typed_val or len(typed_val) < 100:
        logger.info("Clipboard paste didn't work, using JS value injection")
        await page.evaluate(
            """(args) => {
                const el = document.querySelector('textarea');
                if (el) {
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value').set;
                    nativeInputValueSetter.call(el, args.content);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            {"content": content[:500_000]},
        )
        await page.wait_for_timeout(500)

    logger.info("Content pasted, clicking Insert...")
    await _capture_screenshot(page, "nlm_content_pasted")

    # Click Insert/Add
    inserted = await _click_first(page, SEL_INSERT_SOURCE_BTN, timeout=5000)
    if not inserted:
        await page.keyboard.press("Tab")
        await page.keyboard.press("Enter")

    await page.wait_for_timeout(3000)
    await _capture_screenshot(page, "nlm_source_inserting")

    # Wait for source to finish processing (loading indicator disappears)
    try:
        await page.wait_for_selector(
            ".source-loading, [aria-label='Processing']",
            state="hidden",
            timeout=60000,
        )
    except Exception:
        pass  # May not show this indicator

    await page.wait_for_timeout(2000)
    await _capture_screenshot(page, "nlm_source_done")
    logger.info("Source added successfully")
    return True


async def _capture_screenshot(page, name: str) -> None:
    """Save a debug screenshot."""
    try:
        shot_dir = PROJECT_ROOT / "data" / "argus" / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        path = shot_dir / f"nlm_{name}_{int(time.time())}.png"
        await page.screenshot(path=str(path))
        logger.debug("Screenshot: %s", path)
    except Exception:
        pass


# ──── Nexus storage ───────────────────────────────────────────────────────────

def store_notebook_url_in_nexus(notebook_url: str, notebook_name: str) -> None:
    """Store the notebook URL in Nexus for agent reference."""
    try:
        import requests
        requests.post(
            "http://localhost:8700/api/entries",
            json={
                "title": f"NLM Notebook: {notebook_name}",
                "content": (
                    f"NotebookLM notebook URL: {notebook_url}\n\n"
                    f"Created by: scripts/nlm_notebook_creator.py\n"
                    f"Use this notebook to research, ask questions, and distill knowledge.\n"
                    f"Source: docs/PROJECT_JOURNAL.md"
                ),
                "content_type": "note",
                "category": "architecture",
                "tags": ["notebooklm", "notebook", notebook_name.lower().replace(" ", "-")],
            },
            timeout=15,
        )
        logger.info("Stored notebook URL in Nexus")
    except Exception as e:
        logger.warning("Could not store in Nexus: %s", e)


# ──── CLI ─────────────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> int:
    source_path = Path(args.file)
    if not source_path.exists():
        print(f"ERROR: File not found: {source_path}")
        return 1

    content = source_path.read_text(encoding="utf-8")
    notebook_name = args.name or source_path.stem.replace("_", " ").replace("-", " ").title()

    print(f"Source: {source_path} ({len(content):,} chars)")
    print(f"Notebook: {notebook_name}")
    print(f"Mode: {'headless' if args.headless else 'visible browser'}")
    print(f"CDP: {'yes' if not args.no_cdp else 'no (fresh browser)'}")
    print()

    notebook_url = await create_notebook_with_source(
        notebook_name=notebook_name,
        source_content=content,
        source_title=source_path.name,
        headless=args.headless,
        use_cdp=not args.no_cdp,
    )

    if notebook_url and "notebooklm.google.com" in notebook_url:
        print(f"\n✓ SUCCESS: {notebook_url}")
        store_notebook_url_in_nexus(notebook_url, notebook_name)
        print("\nNotebook ready. Ask questions with:")
        print(f"  python -m engine.nexus.nlm_cli ask 'What is the project philosophy?'")
        return 0
    else:
        print("\n✗ FAILED — check screenshots at data/argus/screenshots/")
        print("\nTroubleshooting:")
        print("  1. Make sure Chrome is running (for CDP mode)")
        print("  2. Make sure you're logged into NotebookLM in Chrome")
        print("  3. Try: python scripts/nlm_notebook_creator.py --no-cdp --no-headless")
        return 1


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Create a NotebookLM notebook from a local file"
    )
    parser.add_argument(
        "--file",
        default=str(PROJECT_ROOT / "docs" / "PROJECT_JOURNAL.md"),
        help="Path to the file to upload (default: docs/PROJECT_JOURNAL.md)",
    )
    parser.add_argument(
        "--name",
        default="CosySim Project Journal & Onboarding",
        help="Notebook name",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run in headless mode (default: visible browser for debugging)",
    )
    parser.add_argument(
        "--no-cdp",
        action="store_true",
        default=False,
        help="Don't try to attach to existing Chrome; launch fresh browser",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
