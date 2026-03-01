"""NLM Cookie Refresh Tool.

Opens a Playwright browser window and waits for the user to log in to
NotebookLM. On success, extracts all cookies and saves them to
data/nlm_cookies.json so the proxy and automation can use them.

Usage:
    python -m engine.nexus.nlm_cookie_refresh
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_NLM_URL = "https://notebooklm.google.com/"
_COOKIES_FILE = Path(__file__).resolve().parents[2] / "data" / "nlm_cookies.json"
_TIMEOUT_SECONDS = 600


async def _run_refresh() -> bool:
    """Open browser, wait for NLM login, extract and save cookies."""
    from playwright.async_api import async_playwright

    print("\n" + "=" * 60)
    print("NLM Cookie Refresh")
    print("=" * 60)
    print("A Chromium browser window will open.")
    print("NOTE: The 'not secure' warning is normal — it's just Playwright's")
    print("      Chromium build. Your login is still sent securely to Google.")
    print(f"Timeout: {_TIMEOUT_SECONDS}s ({_TIMEOUT_SECONDS//60} minutes)")
    print("=" * 60 + "\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await page.goto(_NLM_URL)

        print("Waiting for you to log in and reach the NLM homepage...")
        print("(You have 10 minutes — take your time)\n")

        deadline = asyncio.get_event_loop().time() + _TIMEOUT_SECONDS
        last_print = 0.0
        while asyncio.get_event_loop().time() < deadline:
            url = page.url
            if "notebooklm.google.com" in url and "accounts.google.com" not in url:
                # Reached NLM — allow a moment for session cookies to settle
                await page.wait_for_timeout(2000)
                break
            now = asyncio.get_event_loop().time()
            remaining = int(deadline - now)
            if now - last_print >= 30:
                print(f"  Still waiting... {remaining}s remaining. Current: {url[:70]}")
                last_print = now
            await page.wait_for_timeout(1000)
        else:
            print(f"\n✗ Timed out after {_TIMEOUT_SECONDS}s — no cookies saved.")
            await browser.close()
            return False

        # Extract cookies
        cookies = await ctx.cookies("https://notebooklm.google.com")
        # Also grab .google.com scope
        google_cookies = await ctx.cookies("https://accounts.google.com")
        all_cookies: dict[str, str] = {}
        for c in google_cookies + cookies:
            all_cookies[c["name"]] = c["value"]

        await browser.close()

        if not all_cookies:
            print("✗ No cookies found — not logged in?")
            return False

        _COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOKIES_FILE.write_text(json.dumps(all_cookies, indent=2), encoding="utf-8")
        print(f"\n✓ Saved {len(all_cookies)} cookies to {_COOKIES_FILE}")
        key_present = [k for k in ("SID", "SSID", "__Secure-1PSID", "OSID") if k in all_cookies]
        print(f"  Key cookies: {', '.join(key_present)}")
        return True


def main() -> None:
    """Entry point for cookie refresh."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ok = asyncio.run(_run_refresh())
    if ok:
        print("\nCookies saved. You can now run the NLM automation:\n  python -m engine.nexus.nlm_automation\n")
    else:
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
