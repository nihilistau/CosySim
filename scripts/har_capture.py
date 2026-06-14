"""HAR Capture — automated Google cookie refresh via CDP.

THREE modes, tried in order:
  1. CDP direct  — connect to already-running Chrome (port 9223),
                   use Network.getCookies() to pull cookies silently
  2. CDP launch  — spawn a new Chrome with --remote-debugging-port,
                   navigate to notebooklm.google.com, pull cookies
  3. Macro       — keyboard automation fallback (pyautogui required)

Usage
-----
    python scripts/har_capture.py                     # auto (tries CDP first)
    python scripts/har_capture.py --mode cdp          # force CDP
    python scripts/har_capture.py --mode launch       # launch fresh Chrome
    python scripts/har_capture.py --mode macro        # keyboard macro
    python scripts/har_capture.py --account myaccount # override account name
    python scripts/har_capture.py --watch             # start watchfolder after

After cookies are captured they are written straight into the account pool
(data/accounts/pool.json) — no HAR file needed.  A synthetic .har is also
saved to data/hars/imported/ so the import history stays consistent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.integrations.har_extractor import COOKIE_NAMES, HARExtractor
from engine.integrations.google_service_profiles import normalize_google_services

logger = logging.getLogger("har_capture")

CDP_PORT = 9223
NLM_URL = "https://notebooklm.google.com"
POOL_PATH = PROJECT_ROOT / "data" / "accounts" / "pool.json"
HARS_DIR = PROJECT_ROOT / "data" / "hars"
IMPORTED_DIR = HARS_DIR / "imported"

GOOGLE_COOKIE_NAMES = set(COOKIE_NAMES)
DEFAULT_CAPTURE_SERVICES = ["notebooklm", "colab"]

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
        os.environ.get("USERNAME", "")
    ),
]


# ──── CDP helpers ─────────────────────────────────────────────────────────────

def _get_cdp_tabs(port: int = CDP_PORT) -> list:
    try:
        raw = urllib.request.urlopen(f"http://localhost:{port}/json", timeout=3).read()
        return json.loads(raw)
    except Exception:
        return []


def _find_chrome_exe() -> Optional[str]:
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return None


class CDPSession:
    """Minimal CDP session over websockets."""

    def __init__(self, ws):
        self._ws = ws
        self._id = 0

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        cid = self._id
        payload = json.dumps({"id": cid, "method": method, "params": params or {}})
        await self._ws.send(payload)
        while True:
            raw = await self._ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == cid:
                return msg.get("result") or {}


def _extract_runtime_evaluate_value(result: Dict[str, Any]) -> str:
    """Return the by-value payload from a CDP Runtime.evaluate result."""
    if not isinstance(result, dict):
        return ""

    runtime_result = result.get("result")
    if isinstance(runtime_result, dict):
        value = runtime_result.get("value")
        if isinstance(value, str):
            return value

        nested_result = runtime_result.get("result")
        if isinstance(nested_result, dict):
            nested_value = nested_result.get("value")
            if isinstance(nested_value, str):
                return nested_value

    direct_value = result.get("value")
    return direct_value if isinstance(direct_value, str) else ""


def _build_nlm_session_metadata(page_data: Dict[str, Any]) -> Dict[str, str]:
    """Build NotebookLM session metadata from evaluated page state."""
    meta: Dict[str, str] = {}

    build_label = page_data.get("bl")
    if isinstance(build_label, str) and build_label.startswith("boq_labs-tailwind-frontend_"):
        meta["bl"] = build_label

    f_sid = page_data.get("f_sid")
    if f_sid not in (None, ""):
        meta["f_sid"] = str(f_sid)

    at_token = page_data.get("at")
    if isinstance(at_token, str) and at_token:
        meta["at"] = at_token

    href = page_data.get("href")
    if isinstance(href, str) and href:
        parsed = urlparse(href)
        if parsed.path:
            notebook_match = re.search(r"/notebook/([a-f0-9-]{36})", parsed.path)
            if notebook_match:
                meta["source_path"] = parsed.path
                meta["notebook_id"] = notebook_match.group(1)

    return meta


def _select_cdp_tab(
    tabs: List[Dict[str, Any]],
    preferred_patterns: Optional[List[str]] = None,
) -> tuple[Optional[str], str]:
    """Pick the most relevant page tab and return its websocket URL and page URL."""
    usable_tabs = [
        tab
        for tab in tabs
        if tab.get("type") == "page" and not tab.get("url", "").startswith("devtools://")
    ]
    if not usable_tabs:
        return None, ""

    patterns = [pattern for pattern in (preferred_patterns or []) if pattern]
    fallback_patterns = patterns + ["notebooklm.google.com", "google.com"]
    seen: List[str] = []

    for pattern in fallback_patterns:
        if pattern in seen:
            continue
        seen.append(pattern)
        for tab in usable_tabs:
            url = tab.get("url", "")
            if pattern in url:
                return tab.get("webSocketDebuggerUrl"), url

    first_tab = usable_tabs[0]
    return first_tab.get("webSocketDebuggerUrl"), first_tab.get("url", "")


async def _get_cookies_from_tab(ws_url: str) -> Dict[str, str]:
    """Connect to a CDP tab and pull Google auth cookies."""
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets not installed: pip install websockets")

    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)

        # Enable Network domain so CDP knows about cookies
        await cdp.send("Network.enable")

        # Get all cookies for Google domains
        result = await cdp.send("Network.getCookies", {
            "urls": [
                "https://google.com",
                "https://notebooklm.google.com",
                "https://accounts.google.com",
                "https://colab.research.google.com",
            ]
        })

        cookies: Dict[str, str] = {}
        for cookie in result.get("cookies", []):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name in GOOGLE_COOKIE_NAMES and value:
                cookies[name] = value

        return cookies


async def _get_nlm_session_from_tab(
    ws_url: str,
    ensure_notebooklm: bool = False,
) -> Dict[str, str]:
    """Extract NotebookLM page session metadata from a CDP tab."""
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets not installed: pip install websockets")

    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        if ensure_notebooklm:
            await cdp.send("Page.navigate", {"url": NLM_URL})
            await asyncio.sleep(4)

        result = await cdp.send("Runtime.evaluate", {
            "expression": (
                "JSON.stringify({"
                "  bl: (() => {"
                "    const wiz = window.WIZ_global_data || {};"
                "    const explicit = wiz.QrtxK || wiz.cfb2h || wiz.bl || '';"
                "    if (typeof explicit === 'string' && explicit.startsWith('boq_labs-tailwind-frontend_')) return explicit;"
                "    for (const value of Object.values(wiz)) {"
                "      if (typeof value === 'string' && value.startsWith('boq_labs-tailwind-frontend_')) return value;"
                "    }"
                "    return '';"
                "  })(),"
                "  f_sid: (window.WIZ_global_data && (window.WIZ_global_data.IxjpMA || window.WIZ_global_data.FdrFJe)) || '',"
                "  at: (window.WIZ_global_data && window.WIZ_global_data.SNlM0e) || '',"
                "  href: location.href"
                "})"
            ),
            "returnByValue": True,
        })

    raw_value = _extract_runtime_evaluate_value(result)
    if not raw_value:
        return {}

    try:
        page_data = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}

    return _build_nlm_session_metadata(page_data)


async def _get_account_name_from_tab(ws_url: str) -> str:
    """Extract a likely Google account name from a live page when available."""
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets not installed: pip install websockets")

    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        result = await cdp.send("Runtime.evaluate", {
            "expression": (
                "JSON.stringify({"
                "  email: (() => {"
                "    const meta = document.querySelector('meta[name=\"account-email\"]');"
                "    if (meta && meta.content) return meta.content;"
                "    const accountButton = document.querySelector('[aria-label*=\"@\"]');"
                "    if (accountButton) {"
                "      const label = accountButton.getAttribute('aria-label') || '';"
                "      const match = label.match(/\\b[\\w.+-]+@[\\w-]+\\.[\\w.]+/);"
                "      if (match) return match[0];"
                "    }"
                "    return '';"
                "  })()"
                "})"
            ),
            "returnByValue": True,
        })

    raw_value = _extract_runtime_evaluate_value(result)
    if not raw_value:
        return ""

    try:
        page_data = json.loads(raw_value)
    except json.JSONDecodeError:
        return ""

    email = page_data.get("email")
    if not isinstance(email, str) or not email:
        return ""
    return email.split("@", 1)[0]


async def _navigate_and_get_cookies(ws_url: str, url: str = NLM_URL) -> Dict[str, str]:
    """Navigate to url then pull cookies."""
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets not installed: pip install websockets")

    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)
        await cdp.send("Page.enable")
        await cdp.send("Network.enable")
        print(f"  Navigating to {url} ...")
        await cdp.send("Page.navigate", {"url": url})
        await asyncio.sleep(4)  # wait for page + auth redirect to settle
        result = await cdp.send("Network.getCookies", {
            "urls": [
                "https://google.com",
                "https://notebooklm.google.com",
                "https://accounts.google.com",
            ]
        })
        cookies: Dict[str, str] = {}
        for cookie in result.get("cookies", []):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name in GOOGLE_COOKIE_NAMES and value:
                cookies[name] = value
        return cookies


# ──── Mode: CDP (existing Chrome) ────────────────────────────────────────────

async def mode_cdp(account_name: str) -> Optional[Dict[str, Any]]:
    """Pull cookies from already-running Chrome instance."""
    tabs = _get_cdp_tabs()
    if not tabs:
        print("  No Chrome with CDP on port 9223")
        return None

    best_ws, best_url = _select_cdp_tab(tabs, preferred_patterns=["notebooklm.google.com"])
    if not best_ws:
        print("  No usable page tabs found")
        return None

    print(f"  Using existing Chrome tab: {best_ws[:60]}...")
    cookies = await _get_cookies_from_tab(best_ws)
    ensure_notebooklm = "notebooklm.google.com" not in best_url

    if len(cookies) < 3:
        print(f"  Only {len(cookies)} Google cookies found — Chrome may not be logged into Google")
        print("  Navigating an existing tab to NotebookLM to refresh cookies...")
        cookies = await _navigate_and_get_cookies(best_ws, NLM_URL)
        ensure_notebooklm = False

    if len(cookies) < 3:
        return None

    session = await _get_nlm_session_from_tab(best_ws, ensure_notebooklm=ensure_notebooklm)
    return {
        "cookies": cookies,
        "authuser": 0,
        "at_token": session.get("at"),
        "nlm_session": session,
        "service_sessions": {"notebooklm": session} if session else {},
        "services": DEFAULT_CAPTURE_SERVICES,
    }


# ──── Mode: Launch (fresh Chrome) ────────────────────────────────────────────

async def mode_launch(account_name: str) -> Optional[Dict[str, Any]]:
    """Launch a new Chrome instance with CDP and pull cookies."""
    chrome = _find_chrome_exe()
    if not chrome:
        print("  Chrome not found")
        return None

    debug_port = 9223  # Use different port to avoid conflict with existing CDP
    profile_dir = PROJECT_ROOT / "data" / "chrome_capture_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        NLM_URL,
    ]

    print(f"  Launching Chrome on port {debug_port}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for CDP to come up
    for _ in range(15):
        await asyncio.sleep(1)
        tabs = _get_cdp_tabs(debug_port)
        if tabs:
            break
    else:
        proc.terminate()
        print("  Chrome CDP did not start in time")
        return None

    print(f"  Chrome launched (pid={proc.pid}). Waiting 6s for Google login to load...")
    await asyncio.sleep(6)

    # Find the NLM tab
    tabs = _get_cdp_tabs(debug_port)
    best_ws = None
    for tab in tabs:
        if tab.get("type") == "page":
            best_ws = tab.get("webSocketDebuggerUrl")
            break

    if not best_ws:
        proc.terminate()
        return None

    try:
        import websockets
    except ImportError:
        proc.terminate()
        raise RuntimeError("pip install websockets")

    async with websockets.connect(best_ws, max_size=10 * 1024 * 1024) as ws:
        cdp = CDPSession(ws)
        await cdp.send("Network.enable")
        result = await cdp.send("Network.getCookies", {
            "urls": ["https://google.com", "https://notebooklm.google.com",
                     "https://accounts.google.com"]
        })
        cookies: Dict[str, str] = {}
        for cookie in result.get("cookies", []):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name in GOOGLE_COOKIE_NAMES and value:
                cookies[name] = value

    session = await _get_nlm_session_from_tab(best_ws)
    proc.terminate()
    if len(cookies) < 3:
        return None
    return {
        "cookies": cookies,
        "authuser": 0,
        "at_token": session.get("at"),
        "nlm_session": session,
        "service_sessions": {"notebooklm": session} if session else {},
        "services": DEFAULT_CAPTURE_SERVICES,
    }


# ──── Mode: Macro (keyboard automation) ──────────────────────────────────────

def mode_macro(account_name: str) -> Optional[Dict[str, Any]]:
    """Drive Chrome DevTools via keyboard macros to save a HAR, then parse it."""
    try:
        import pyautogui
    except ImportError:
        print("  pyautogui not installed: pip install pyautogui")
        return None

    har_path = HARS_DIR / f"{account_name}.har"
    HARS_DIR.mkdir(parents=True, exist_ok=True)

    chrome = _find_chrome_exe()
    if not chrome:
        print("  Chrome not found")
        return None

    print(f"  Launching Chrome to {NLM_URL} ...")
    subprocess.Popen([chrome, "--new-window", NLM_URL])
    time.sleep(4)

    print("  Opening DevTools and capturing HAR...")
    pyautogui.PAUSE = 0.3

    pyautogui.hotkey("ctrl", "shift", "i")  # Open DevTools
    time.sleep(1.5)

    # Navigate to Network tab
    pyautogui.hotkey("shift", "tab")
    pyautogui.hotkey("shift", "tab")
    pyautogui.press("enter")       # Focus toolbar
    pyautogui.press("down")
    pyautogui.press("down")
    pyautogui.press("enter")       # Click Network tab
    time.sleep(0.5)

    # Reload page to capture traffic with Network tab open
    pyautogui.hotkey("ctrl", "r")
    time.sleep(3)

    # Export HAR: right-click in Network panel → Save all as HAR
    # The user's macro: shift-tab x5 to get to the network list, then right-click
    # Actually use the "..." menu in DevTools Network panel
    # Simpler: use keyboard shortcut sequence the user provided
    for _ in range(5):
        pyautogui.hotkey("shift", "tab")
        time.sleep(0.1)

    # Type the save path directly
    pyautogui.typewrite(str(har_path), interval=0.02)
    pyautogui.press("enter")
    time.sleep(1)
    pyautogui.press("enter")
    time.sleep(2)

    if not har_path.exists():
        print(f"  HAR file not found at {har_path} — macro may have failed")
        return None

    print(f"  HAR saved: {har_path}")

    # Parse it
    extractor = HARExtractor(str(har_path))
    account_data = extractor.to_account_dict(account_name)
    if not account_data.get("cookies"):
        return None
    return account_data


# ──── Import cookies into pool ────────────────────────────────────────────────

def _save_to_pool(capture: Dict[str, Any], account_name: str) -> None:
    """Write a captured auth bundle directly into the account pool."""
    from engine.integrations.google_account_pool import get_account_pool, GoogleAccount

    pool = get_account_pool()
    existing = pool.get_by_name(account_name)
    cookies = capture.get("cookies", {})
    nlm_session = capture.get("nlm_session", {}) or {}
    service_sessions = dict(capture.get("service_sessions", {}) or {})
    if nlm_session and "notebooklm" not in service_sessions:
        service_sessions["notebooklm"] = dict(nlm_session)
    requested_services = normalize_google_services(capture.get("services") or DEFAULT_CAPTURE_SERVICES)
    at_token = capture.get("at_token")
    authuser = int(capture.get("authuser", existing.authuser if existing else 0) or 0)

    if existing:
        # Update in-place
        existing.cookies = cookies
        existing.added_at = time.time()
        existing.services = normalize_google_services(existing.services + requested_services)
        existing.authuser = authuser
        if at_token:
            existing.at_token = at_token
        if nlm_session:
            existing.nlm_session = {**existing.nlm_session, **nlm_session}
        for service, session in service_sessions.items():
            existing_session = dict(existing.service_sessions.get(service, {}))
            existing_session.update(session)
            existing.service_sessions[service] = existing_session
        pool.add_account(existing)
    else:
        account = GoogleAccount(
            name=account_name,
            cookies=cookies,
            authuser=authuser,
            services=requested_services,
            at_token=at_token,
            nlm_session=nlm_session,
            service_sessions=service_sessions,
        )
        pool.add_account(account)

    pool.save()
    print(f"  Pool updated: '{account_name}' now has {len(cookies)} fresh cookies")


def _store_nexus_event(account_name: str, cookie_count: int, mode: str, services: List[str]) -> None:
    try:
        import requests
        requests.post(
            "http://localhost:8700/api/entries",
            json={
                "title": f"Cookie Refresh: {account_name} ({mode})",
                "content": (
                    f"Cookies refreshed for account '{account_name}' via {mode}.\n"
                    f"Cookie count: {cookie_count}\n"
                    f"Services: {', '.join(services)}\n"
                    f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                "content_type": "note",
                "category": "system",
                "tags": ["cookie-refresh", "har-capture", mode],
            },
            timeout=5,
        )
    except Exception:
        pass


# ──── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated Google cookie refresh for the account pool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "cdp", "launch", "macro"],
        default="auto",
        help="Capture mode (default: auto — tries cdp → launch → macro)",
    )
    parser.add_argument(
        "--account",
        default="nihilistcod",
        help="Account name to store cookies under (default: nihilistcod)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Start har_watchfolder.py after successful capture",
    )
    parser.add_argument(
        "--services",
        default="notebooklm,colab",
        help="Comma-separated service labels to associate with the capture",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CDP_PORT,
        help=f"Chrome CDP port (default: {CDP_PORT})",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    account_name = args.account
    capture_services = normalize_google_services(
        [service for service in args.services.split(",") if service.strip()]
    ) or list(DEFAULT_CAPTURE_SERVICES)
    print(f"\n-- HAR Capture -------------------------------------------")
    print(f"  Account : {account_name}")
    print(f"  Mode    : {args.mode}")
    print(f"  CDP port: {args.port}")
    print(f"  Services: {', '.join(capture_services)}")
    print()

    capture: Optional[Dict[str, Any]] = None
    used_mode = ""

    modes = {
        "cdp": lambda: asyncio.run(mode_cdp(account_name)),
        "launch": lambda: asyncio.run(mode_launch(account_name)),
        "macro": lambda: mode_macro(account_name),
    }

    if args.mode == "auto":
        order = ["cdp", "launch", "macro"]
    else:
        order = [args.mode]

    for mode_name in order:
        print(f"  Trying mode: {mode_name} ...")
        try:
            result = modes[mode_name]()
            cookie_count = len(result.get("cookies", {})) if result else 0
            if result and cookie_count >= 3:
                # Always respect CLI-requested services instead of any defaults from capture mode
                result["services"] = capture_services
                capture = result
                used_mode = mode_name
                break
            else:
                print(f"  {mode_name}: insufficient cookies ({cookie_count}), trying next...")
        except Exception as exc:
            print(f"  {mode_name} failed: {exc}")

    if not capture:
        print("\n✗ Could not capture cookies via any method.")
        print("\nManual fallback:")
        print("  1. Open notebooklm.google.com in Chrome")
        print("  2. F12 → Network tab → reload the page")
        print("  3. Right-click any request → Save all as HAR with content")
        print(f"  4. Save to: {HARS_DIR / account_name}.har")
        print("  5. Run: python scripts/har_watchfolder.py watch")
        sys.exit(1)

    cookie_count = len(capture["cookies"])
    print(f"\n[OK] Captured {cookie_count} cookies via {used_mode}")
    if capture.get("nlm_session"):
        session = capture["nlm_session"]
        print(
            "  NLM session:"
            f" bl={session.get('bl', '')}"
            f" f_sid={session.get('f_sid', '')}"
            f" at_present={bool(session.get('at'))}"
        )
    _save_to_pool(capture, account_name)
    _store_nexus_event(account_name, cookie_count, used_mode, capture.get("services", capture_services))

    # Verify
    print("\n  Verifying ...")
    subprocess.run(
        [sys.executable, "scripts/har_watchfolder.py", "status"],
        cwd=str(PROJECT_ROOT),
    )

    if args.watch:
        print("\n  Starting HAR watchfolder ...")
        subprocess.Popen(
            [sys.executable, "scripts/har_watchfolder.py", "watch"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  Watchfolder running. Drop any future .har into {HARS_DIR}")


if __name__ == "__main__":
    main()
