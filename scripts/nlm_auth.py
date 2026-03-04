"""
NotebookLM auth helper — opens a visible browser, waits for login, saves cookies.

Usage:
    python scripts/nlm_auth.py

After running: cookies are saved to the notebooklm-mcp data directory.
"""
import json
import pathlib
import sys
import time


NLM_CHROME_PROFILE = str(
    pathlib.Path.home() / "AppData/Local/notebooklm-mcp/Data/chrome_profile"
)


def find_nlm_cookie_dir() -> pathlib.Path:
    """Find where notebooklm-mcp stores its cookies."""
    candidates = [
        pathlib.Path.home() / "AppData/Roaming/notebooklm-mcp",
        pathlib.Path.home() / "AppData/Local/notebooklm-mcp",
        pathlib.Path.home() / ".config/notebooklm-mcp",
        pathlib.Path.home() / ".notebooklm-mcp",
    ]
    for c in candidates:
        if c.exists():
            return c
    # default — create it
    d = pathlib.Path.home() / "AppData/Roaming/notebooklm-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> None:
    from playwright.sync_api import sync_playwright

    cookie_dir = find_nlm_cookie_dir()
    cookie_file = cookie_dir / "cookies.json"
    print(f"Cookie target: {cookie_file}")

    with sync_playwright() as p:
        # Use the notebooklm-mcp chrome profile so auth persists for MCP use
        nlm_profile = NLM_CHROME_PROFILE
        pathlib.Path(nlm_profile).mkdir(parents=True, exist_ok=True)

        browser = p.chromium.launch_persistent_context(
            user_data_dir=nlm_profile,
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        page = browser.new_page()
        print("Opening NotebookLM...")
        page.goto("https://notebooklm.google.com", timeout=30000)

        print("\nPlease log in to your Google account in the browser window.")
        print("Waiting up to 3 minutes for login...\n")

        deadline = time.time() + 180
        logged_in = False
        while time.time() < deadline:
            try:
                url = page.url
                title = page.title()
                if "notebooklm.google.com" in url and "Sign in" not in title:
                    logged_in = True
                    print(f"Logged in! Title: {title}")
                    break
                time.sleep(2)
                sys.stdout.write(".")
                sys.stdout.flush()
            except Exception:
                time.sleep(2)

        if logged_in:
            cookies = browser.cookies()
            cookie_file.write_text(json.dumps(cookies, indent=2))
            print(f"\nSaved {len(cookies)} cookies to {cookie_file}")
            print("Auth profile saved. NotebookLM MCP should now work.")
        else:
            print("\nLogin not detected within 3 minutes.")

        browser.close()


if __name__ == "__main__":
    main()
