"""
Create a NotebookLM notebook via CDP using the already-running Chrome.
Connects to Chrome's remote debugging port (9223).

Usage:
    python scripts/nlm_cdp_create.py --screenshot
    python scripts/nlm_cdp_create.py --title "My Notebook" --file path/to/file.md
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

CDP_HOST = "http://localhost:9223"
NLM_URL = "https://notebooklm.google.com/"


def get_or_open_nlm_tab() -> dict:
    """Return an existing NLM tab or open a new one."""
    tabs = requests.get(f"{CDP_HOST}/json").json()
    for tab in tabs:
        if "notebooklm.google.com" in tab.get("url", ""):
            print(f"Using existing NLM tab: {tab['id']}")
            return tab
    # Open new tab
    new_tab = requests.put(f"{CDP_HOST}/json/new?{NLM_URL}").json()
    print(f"Opened new NLM tab: {new_tab['id']}")
    time.sleep(3)
    return new_tab


def cdp(tab_id: str, method: str, params: dict = None) -> dict:
    """Execute a CDP command via WebSocket."""
    import websocket  # type: ignore

    tabs = requests.get(f"{CDP_HOST}/json").json()
    ws_url = None
    for tab in tabs:
        if tab.get("id") == tab_id:
            ws_url = tab.get("webSocketDebuggerUrl")
            break

    if not ws_url:
        raise ValueError(f"Tab {tab_id} not found or has no WS URL")

    ws = websocket.create_connection(ws_url, timeout=15)
    msg = {"id": 1, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
    result = json.loads(ws.recv())
    ws.close()
    return result


def screenshot(tab_id: str, out_path: str) -> None:
    result = cdp(tab_id, "Page.captureScreenshot", {"format": "png"})
    data = result.get("result", {}).get("data", "")
    if data:
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"Screenshot saved: {out_path}")
    else:
        print(f"Screenshot failed: {result}")


def eval_js(tab_id: str, js: str) -> dict:
    return cdp(tab_id, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True,
    })


def inspect_nlm_buttons(tab_id: str) -> None:
    js = """
    (() => {
        const results = [];
        const els = document.querySelectorAll('button, [role="button"], mat-fab');
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                results.push({
                    tag: el.tagName,
                    text: el.innerText?.trim().substring(0, 60),
                    aria: el.getAttribute('aria-label'),
                    class: el.className?.substring(0, 60),
                    id: el.id,
                });
            }
        }
        return JSON.stringify(results.slice(0, 30));
    })()
    """
    result = eval_js(tab_id, js)
    val = result.get("result", {}).get("value", "[]")
    buttons = json.loads(val) if isinstance(val, str) else []
    print(f"\nVisible interactive elements ({len(buttons)}):")
    for b in buttons:
        print(f"  <{b['tag']}> text='{b.get('text','')}' aria='{b.get('aria','')}' class='{b.get('class','')[:40]}' id='{b.get('id','')}'")


def click_by_aria(tab_id: str, aria_label: str) -> bool:
    js = f"""
    (() => {{
        const el = document.querySelector('[aria-label="{aria_label}"]') ||
                   [...document.querySelectorAll('button')].find(b => b.innerText.includes('{aria_label}'));
        if (el) {{ el.click(); return true; }}
        return false;
    }})()
    """
    result = eval_js(tab_id, js)
    return result.get("result", {}).get("value", False)


def navigate_to_nlm(tab_id: str) -> None:
    cdp(tab_id, "Page.navigate", {"url": NLM_URL})
    time.sleep(4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--title", default="CosySim Project Journal & Knowledge Base")
    parser.add_argument("--file", default=None)
    parser.add_argument("--inspect", action="store_true", help="Inspect DOM buttons only")
    args = parser.parse_args()

    # Check websocket-client
    try:
        import websocket  # noqa
    except ImportError:
        print("Installing websocket-client...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "websocket-client"], check=True)
        import websocket  # noqa

    # Check CDP is available
    try:
        tabs = requests.get(f"{CDP_HOST}/json", timeout=3).json()
        print(f"Chrome CDP available: {len(tabs)} tabs")
    except Exception as e:
        print(f"ERROR: Chrome CDP not available at {CDP_HOST}: {e}")
        print("Start Chrome with: --remote-debugging-port=9223")
        sys.exit(1)

    tab = get_or_open_nlm_tab()
    tab_id = tab["id"]

    # Navigate to NLM if not already there
    current_url = tab.get("url", "")
    if "notebooklm.google.com" not in current_url:
        print(f"Current URL: {current_url} — navigating to NLM...")
        navigate_to_nlm(tab_id)

    Path("data").mkdir(exist_ok=True)
    screenshot(tab_id, "data/nlm_cdp_screenshot.png")

    if args.screenshot or args.inspect:
        inspect_nlm_buttons(tab_id)

        # Also print page title and URL
        result = eval_js(tab_id, "document.title + ' | ' + location.href")
        val = result.get("result", {}).get("value", "")
        print(f"\nPage: {val}")
        return

    # Try to create notebook
    print("\nAttempting to create notebook...")
    inspect_nlm_buttons(tab_id)


if __name__ == "__main__":
    main()
