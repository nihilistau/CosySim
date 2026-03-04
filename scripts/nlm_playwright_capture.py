"""
nlm_playwright_capture.py — Playwright automation for NLM API discovery.

Automates known NLM actions while capturing ALL network traffic, then:
  - Saves HAR files per action
  - Extracts and documents each rpc method discovered
  - Runs nlm_protocol_mapper to correlate request/response schemas
  - Stores findings in Nexus

Usage:
    python scripts/nlm_playwright_capture.py --action all
    python scripts/nlm_playwright_capture.py --action chat --notebook <uuid>
    python scripts/nlm_playwright_capture.py --action list_notebooks
    python scripts/nlm_playwright_capture.py --list-actions
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

# ── Playwright ────────────────────────────────────────────────────────────────
try:
    from playwright.async_api import async_playwright, BrowserContext, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


COOKIE_FILE = Path("data/accounts/pool.json")
HAR_OUT_DIR = Path("data/har_files")
HAR_OUT_DIR.mkdir(parents=True, exist_ok=True)

NLM_BASE = "https://notebooklm.google.com"

# Default notebook for testing (active notebook from heap analysis)
DEFAULT_NOTEBOOK = "603976db-40d0-4b3f-9827-a483c45a3108"

# All known NLM actions to capture
ACTIONS = {
    "list_notebooks": "Open NLM home page — triggers ListNotebooks",
    "open_notebook": "Open a specific notebook — triggers GetNotebook, ListSources",
    "chat": "Send a chat message — triggers GenerateFreeFormStreamed",
    "add_source_url": "Add a URL source to a notebook",
    "add_source_text": "Add a text/paste source",
    "delete_source": "Delete a source",
    "create_notebook": "Create a new notebook",
    "delete_notebook": "Delete a notebook",
    "get_audio_overview": "Trigger audio overview generation",
    "generate_study_guide": "Generate a study guide artifact",
    "generate_faq": "Generate an FAQ artifact",
    "generate_briefing": "Generate a briefing document",
    "generate_mindmap": "Generate a mind map",
    "generate_quiz": "Generate a quiz",
    "generate_table": "Generate a data table",
    "generate_slides": "Generate slides",
    "generate_report": "Generate a report",
    "generate_infographic": "Generate an infographic",
    "generate_video_overview": "Generate a video overview",
    "rename_notebook": "Rename a notebook",
    "add_collaborator": "Add a notebook collaborator",
    "share_notebook": "Get share link for a notebook",
    "search_notebooks": "Search across notebooks",
    "pin_source": "Pin/unpin a source",
    "rename_source": "Rename a source",
}


async def load_cookies_to_context(context: BrowserContext, account: str = "knack112358") -> bool:
    """Load saved cookies from pool.json into browser context."""
    if not COOKIE_FILE.exists():
        print(f"  [!] No pool.json at {COOKIE_FILE}")
        return False

    with open(COOKIE_FILE) as f:
        pool = json.load(f)

    accounts = pool.get("accounts", pool)
    acct = accounts.get(account, {})
    raw_cookies = acct.get("cookies", {})

    if not raw_cookies:
        print(f"  [!] No cookies for account '{account}'")
        return False

    playwright_cookies = []
    for name, value in raw_cookies.items():
        playwright_cookies.append({
            "name": name,
            "value": value,
            "domain": ".google.com",
            "path": "/",
            "httpOnly": name.startswith("__Secure"),
            "secure": name.startswith("__Secure"),
            "sameSite": "None" if name.startswith("__Secure") else "Lax",
        })

    await context.add_cookies(playwright_cookies)
    print(f"  Loaded {len(playwright_cookies)} cookies for {account}")
    return True


async def capture_action(
    page: Page,
    action: str,
    notebook_id: str = DEFAULT_NOTEBOOK,
    chat_message: str = "What are the main topics covered in this notebook?",
) -> list[dict]:
    """Execute a known NLM action and return captured API calls."""
    api_calls = []

    def on_request(request):
        if "notebooklm.google.com" in request.url and request.method == "POST":
            api_calls.append({
                "type": "request",
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": request.post_data or "",
                "timestamp": time.time(),
            })

    def on_response(response):
        if "notebooklm.google.com" in response.url and response.status < 400:
            pass  # Body captured separately via HAR

    page.on("request", on_request)
    page.on("response", on_response)

    print(f"\n  Executing action: {action}")

    try:
        if action == "list_notebooks":
            await page.goto(NLM_BASE, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

        elif action == "open_notebook":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

        elif action == "chat":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            # Find chat input
            chat_input = page.locator("textarea, input[type='text'], [contenteditable='true']").last
            await chat_input.fill(chat_message)
            await page.wait_for_timeout(500)
            # Submit
            await page.keyboard.press("Enter")
            # Wait for response to stream
            await page.wait_for_timeout(8000)

        elif action == "add_source_url":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            # Click Add source
            add_btn = page.get_by_text("Add source", exact=False).first
            await add_btn.click()
            await page.wait_for_timeout(1000)
            # Look for URL input
            url_input = page.locator("input[placeholder*='URL'], input[placeholder*='url']").first
            if await url_input.count() > 0:
                await url_input.fill("https://example.com")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(5000)

        elif action == "create_notebook":
            await page.goto(NLM_BASE, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            new_btn = page.get_by_text("New notebook", exact=False).first
            await new_btn.click()
            await page.wait_for_timeout(3000)

        elif action == "generate_study_guide":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            studio_btn = page.get_by_text("Study guide", exact=False).first
            await studio_btn.click()
            await page.wait_for_timeout(8000)

        elif action == "generate_faq":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            btn = page.get_by_text("FAQ", exact=False).first
            await btn.click()
            await page.wait_for_timeout(8000)

        elif action == "generate_briefing":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            btn = page.get_by_text("Briefing doc", exact=False).first
            await btn.click()
            await page.wait_for_timeout(8000)

        elif action == "generate_audio_overview":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            btn = page.get_by_text("Generate", exact=False).first
            await btn.click()
            await page.wait_for_timeout(5000)

        elif action == "get_audio_overview":
            await page.goto(f"{NLM_BASE}/notebook/{notebook_id}", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            # Look for audio overview section
            audio_btn = page.locator("[aria-label*='audio'], button:has-text('Audio overview')").first
            if await audio_btn.count() > 0:
                await audio_btn.click()
                await page.wait_for_timeout(3000)

        else:
            print(f"  [!] Action '{action}' not yet implemented")

    except Exception as e:
        print(f"  [!] Action failed: {e}")

    page.remove_listener("request", on_request)
    print(f"  Captured {len(api_calls)} API calls")
    return api_calls


async def run_capture(
    actions: list[str],
    notebook_id: str = DEFAULT_NOTEBOOK,
    account: str = "knack112358",
    headed: bool = True,
    har_prefix: str = "auto",
) -> dict:
    """Run actions in browser with HAR recording."""
    if not HAS_PLAYWRIGHT:
        print("[!] Playwright not installed. Run: pip install playwright && playwright install chromium")
        return {}

    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )

        for action in actions:
            print(f"\n{'='*60}")
            print(f"Action: {action}")
            print(f"{'='*60}")

            har_path = HAR_OUT_DIR / f"nlm_capture_{action}_{int(time.time())}.har"

            context = await browser.new_context(
                record_har_path=str(har_path),
                record_har_url_filter="**/notebooklm.google.com/**",
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                ),
            )

            ok = await load_cookies_to_context(context, account)
            if not ok:
                print(f"  [!] Skipping {action} — no valid cookies")
                await context.close()
                continue

            page = await context.new_page()
            api_calls = await capture_action(page, action, notebook_id)

            await page.close()
            await context.close()

            # HAR is saved when context closes
            if har_path.exists():
                print(f"  HAR saved: {har_path} ({har_path.stat().st_size / 1024:.1f} KB)")
                # Run protocol mapper on it
                from scripts.nlm_protocol_mapper import analyze_har
                r = analyze_har(str(har_path), verbose=False)
                results[action] = {
                    "har": str(har_path),
                    "api_calls": api_calls,
                    "rpc_methods": list(r["rpc_methods"].keys()),
                    "notebooks": r["notebook_uuids"],
                }
                # Show new rpcids
                for rpcid in r["rpc_methods"]:
                    print(f"  New rpcid: [{rpcid}] — {r['rpc_methods'][rpcid]['calls']} calls")
            else:
                print(f"  [!] No HAR generated for {action}")

        await browser.close()

    return results


def run_all_hars_analysis() -> None:
    """Analyze all existing HARs and produce merged protocol map."""
    from scripts.nlm_protocol_mapper import analyze_all_hars
    results = analyze_all_hars()

    # Save merged results
    out = Path("data/heap_output/nlm_protocol_map.json")
    with open(out, "w") as f:
        # Serialize sets
        def default(o):
            if isinstance(o, set):
                return sorted(o)
            return str(o)
        json.dump(results, f, indent=2, default=default)
    print(f"\nProtocol map saved: {out}")


def main():
    parser = argparse.ArgumentParser(description="NLM Playwright capture and protocol mapping")
    parser.add_argument("--action", default="all", help="Action to run or 'all'")
    parser.add_argument("--notebook", default=DEFAULT_NOTEBOOK, help="Notebook UUID to use")
    parser.add_argument("--account", default="knack112358", help="Google account to use")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--list-actions", action="store_true", help="List all actions")
    parser.add_argument("--analyze-hars", action="store_true", help="Analyze all existing HARs")
    args = parser.parse_args()

    if args.list_actions:
        print("\nAvailable actions:")
        for name, desc in ACTIONS.items():
            print(f"  {name:30s} — {desc}")
        return

    if args.analyze_hars:
        run_all_hars_analysis()
        return

    if not HAS_PLAYWRIGHT:
        print("[!] Install playwright first:")
        print("    pip install playwright")
        print("    playwright install chromium")
        return

    actions = list(ACTIONS.keys()) if args.action == "all" else [args.action]
    asyncio.run(run_capture(
        actions=actions,
        notebook_id=args.notebook,
        account=args.account,
        headed=not args.headless,
    ))


if __name__ == "__main__":
    main()
