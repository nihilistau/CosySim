"""
Create a NotebookLM notebook and upload a file source using Playwright.
Uses the stored browser_state/state.json cookies (no login needed).

Usage:
    python scripts/nlm_create_notebook.py --title "My Notebook" --file path/to/file.md
    python scripts/nlm_create_notebook.py --screenshot  # just take a screenshot to see UI
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

STATE_FILE = Path(r"C:\Users\Knack\AppData\Local\notebooklm-mcp\Data\browser_state\state.json")
NLM_URL = "https://notebooklm.google.com/"
SCREENSHOT_PATH = Path("data/nlm_screenshot.png")


def run(title: str | None, file_path: str | None, screenshot_only: bool = False) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright...")
        os.system("pip install playwright && playwright install chromium")
        from playwright.sync_api import sync_playwright

    if not STATE_FILE.exists():
        print(f"ERROR: state.json not found at {STATE_FILE}")
        sys.exit(1)

    with open(STATE_FILE) as f:
        storage_state = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        print(f"Navigating to {NLM_URL}...")
        page.goto(NLM_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Take screenshot to see current state
        SCREENSHOT_PATH.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        print(f"Screenshot saved: {SCREENSHOT_PATH}")

        if screenshot_only:
            print("Title:", page.title())
            print("URL:", page.url)
            # Print visible buttons
            buttons = page.query_selector_all("button, [role=button]")
            print(f"\nVisible buttons/roles ({len(buttons)}):")
            for btn in buttons[:20]:
                txt = btn.inner_text().strip()[:60]
                aria = btn.get_attribute("aria-label") or ""
                if txt or aria:
                    print(f"  '{txt}' | aria='{aria}'")
            browser.close()
            return

        # Find the "New notebook" button — try multiple selectors
        new_nb_selectors = [
            "button[aria-label*='new' i]",
            "button[aria-label*='New' i]",
            "button[aria-label*='notebook' i]",
            "[data-mat-icon-name='add']",
            "button:has-text('New')",
            "button:has-text('+')",
            ".new-notebook-button",
            "mat-fab",
            "[aria-label='New notebook']",
            "button.new-notebook",
        ]

        new_btn = None
        for sel in new_nb_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    print(f"Found new-notebook button: {sel}")
                    new_btn = el
                    break
            except Exception:
                pass

        if not new_btn:
            print("Could not find 'New notebook' button. Taking screenshot for inspection...")
            page.screenshot(path="data/nlm_no_button.png", full_page=True)
            # Print all elements
            print("\nAll visible buttons:")
            buttons = page.query_selector_all("button, [role=button], mat-fab")
            for btn in buttons[:30]:
                txt = btn.inner_text().strip()[:80]
                aria = btn.get_attribute("aria-label") or ""
                cls = btn.get_attribute("class") or ""
                print(f"  text='{txt}' | aria='{aria}' | class='{cls[:40]}'")
            browser.close()
            return

        new_btn.click()
        print("Clicked 'New notebook' button")
        time.sleep(2)

        # Set title if provided
        if title:
            title_selectors = [
                "input[placeholder*='title' i]",
                "input[aria-label*='title' i]",
                ".notebook-title input",
                "input[name='title']",
            ]
            for sel in title_selectors:
                el = page.query_selector(sel)
                if el:
                    el.triple_click()
                    el.type(title)
                    print(f"Set title: {title}")
                    break

        # Upload file if provided
        if file_path:
            file_path = Path(file_path)
            if not file_path.exists():
                print(f"ERROR: file not found: {file_path}")
                browser.close()
                return

            # Find upload button / file input
            upload_selectors = [
                "input[type='file']",
                "button[aria-label*='upload' i]",
                "button[aria-label*='file' i]",
                "button:has-text('Upload')",
                "button:has-text('Add source')",
                "button:has-text('From file')",
                "[data-source-type='upload']",
            ]

            upload_input = None
            for sel in upload_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        print(f"Found upload element: {sel}")
                        upload_input = el
                        break
                except Exception:
                    pass

            if upload_input and upload_input.get_attribute("type") == "file":
                upload_input.set_input_files(str(file_path))
                print(f"Uploaded: {file_path}")
                time.sleep(5)
            elif upload_input:
                upload_input.click()
                time.sleep(1)
                # After clicking, look for file input
                file_input = page.query_selector("input[type='file']")
                if file_input:
                    file_input.set_input_files(str(file_path))
                    print(f"Uploaded: {file_path}")
                    time.sleep(5)

        # Get notebook URL
        print(f"\nFinal URL: {page.url}")
        page.screenshot(path="data/nlm_after_create.png", full_page=True)
        print("Final screenshot: data/nlm_after_create.png")

        # Wait a moment for user to see
        input("\nPress Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create NotebookLM notebook")
    parser.add_argument("--title", default="CosySim Project Journal & Knowledge Base")
    parser.add_argument("--file", default=None)
    parser.add_argument("--screenshot", action="store_true", help="Just take screenshot to inspect UI")
    args = parser.parse_args()

    run(
        title=args.title,
        file_path=args.file,
        screenshot_only=args.screenshot,
    )
