"""
NLM HAR Capture — Automated Chrome CDP cookie extraction for NotebookLM.

Workflow
~~~~~~~~
1. Check if Chrome is already running with --remote-debugging-port=9222
2. If not, launch Chrome with the existing user profile + remote debugging
3. Navigate to notebooklm.google.com via CDP
4. Wait for page load and extract cookies via Network.getAllCookies
5. Also capture the build label (bl) and session ID (f.sid) from the page
6. Store everything in data/nlm_cookies.json and data/nlm_meta.json

Chrome Profile Path (default): C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data

The user is already logged in via their existing Chrome profile, so no
re-authentication is needed.

Usage::

    from engine.nexus.nlm_har_capture import capture_nlm_cookies
    result = capture_nlm_cookies()
    # result = {"imported_cookies": 12, "bl": "boq_...", "f_sid": "...", "status": "ok"}

    # CLI:
    python -m engine.nexus.nlm_har_capture
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_FILE = _PROJECT_ROOT / "data" / "nlm_cookies.json"
_META_FILE = _PROJECT_ROOT / "data" / "nlm_meta.json"
_NLM_HOST = "notebooklm.google.com"
_CDP_HOST = "localhost"
_CDP_PORT = 9222
_CDP_URL = f"http://{_CDP_HOST}:{_CDP_PORT}"

# Google Chrome install paths on Windows
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\{user}\AppData\Local\Google\Chrome\Application\chrome.exe",
]

# Google auth cookie names to keep
_AUTH_COOKIE_NAMES = frozenset([
    "SID", "SSID", "APISID", "SAPISID", "HSID", "OSID", "LSID", "SIDCC",
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC", "__Secure-1PSIDTS",
    "NID", "1P_JAR", "AEC", "SOCS", "CONSENT",
])


# ── Chrome detection and launch ──────────────────────────────────────────

def _find_chrome() -> Optional[str]:
    """Find the Chrome executable path on this system."""
    user = os.environ.get("USERNAME", "")
    for path in _CHROME_PATHS:
        expanded = path.format(user=user)
        if Path(expanded).exists():
            return expanded

    # Try registry (Windows)
    try:
        import winreg
        for key_path in [
            r"SOFTWARE\Google\Chrome\BLBeacon",
            r"SOFTWARE\Wow6432Node\Google\Chrome\BLBeacon",
        ]:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    version = winreg.QueryValueEx(key, "version")[0]
                    if version:
                        # Found Chrome
                        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
                        if Path(chrome).exists():
                            return chrome
            except OSError:
                continue
    except ImportError:
        pass

    # Try shutil
    import shutil
    found = shutil.which("chrome") or shutil.which("google-chrome")
    return found


def _is_cdp_running() -> bool:
    """Check if Chrome is already running with remote debugging on port 9222."""
    try:
        req = urllib.request.Request(f"{_CDP_URL}/json/version", headers={"User-Agent": "CosySim"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return "Chrome" in data.get("Browser", "")
    except Exception:
        return False


def _launch_chrome_with_debugging(profile_dir: Optional[str] = None) -> Optional[subprocess.Popen]:
    """Launch Chrome with remote debugging port enabled.

    Uses the existing user profile so the user is already authenticated.

    Args:
        profile_dir: Path to Chrome user data directory. Auto-detected if None.

    Returns:
        Popen handle for the launched Chrome instance, or None on failure.
    """
    chrome_exe = _find_chrome()
    if not chrome_exe:
        logger.error("Chrome executable not found. Install Google Chrome to enable auto-capture.")
        return None

    if not profile_dir:
        user = os.environ.get("USERNAME", "")
        profile_dir = rf"C:\Users\{user}\AppData\Local\Google\Chrome\User Data"

    # Use a separate profile to avoid conflicting with running Chrome
    cdp_profile = str(_PROJECT_ROOT / "data" / "chrome_cdp_profile")

    args = [
        chrome_exe,
        f"--remote-debugging-port={_CDP_PORT}",
        f"--user-data-dir={cdp_profile}",
        "--headless=new",  # Headless mode
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-extensions",
        f"https://{_NLM_HOST}",
    ]

    logger.info("Launching Chrome with CDP on port %d", _CDP_PORT)
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for Chrome to start
        for _ in range(20):
            time.sleep(0.5)
            if _is_cdp_running():
                logger.info("Chrome CDP ready")
                return proc
        logger.warning("Chrome started but CDP not responding after 10s")
        return proc
    except Exception as exc:
        logger.error("Failed to launch Chrome: %s", exc)
        return None


# ── CDP communication ────────────────────────────────────────────────────

def _cdp_json(endpoint: str) -> Any:
    """Make a simple GET request to the Chrome DevTools JSON API."""
    req = urllib.request.Request(
        f"{_CDP_URL}/{endpoint.lstrip('/')}",
        headers={"User-Agent": "CosySim/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


class CDPSession:
    """Lightweight Chrome DevTools Protocol session over WebSocket."""

    def __init__(self, ws_url: str) -> None:
        self._ws_url = ws_url
        self._ws: Any = None
        self._msg_id = 0
        self._pending: Dict[int, Any] = {}

    def connect(self) -> None:
        """Establish WebSocket connection to Chrome CDP."""
        try:
            import websocket  # type: ignore[import]
            self._ws = websocket.WebSocket()
            self._ws.connect(self._ws_url, timeout=10)
        except ImportError:
            raise RuntimeError(
                "websocket-client not installed. Run: pip install websocket-client"
            )

    def close(self) -> None:
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def send(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send a CDP command and wait for response.

        Args:
            method: CDP method name (e.g. "Network.getAllCookies").
            params: Optional dict of parameters.

        Returns:
            CDP response dict.
        """
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        self._ws.send(json.dumps(msg))

        deadline = time.time() + 15
        while time.time() < deadline:
            raw = self._ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                return data
        raise TimeoutError(f"CDP command {method} timed out after 15s")


def _get_nlm_page(session: CDPSession) -> Optional[str]:
    """Return the target ID for the NotebookLM page, or None."""
    targets = _cdp_json("json")
    for t in targets:
        if _NLM_HOST in t.get("url", ""):
            return t.get("webSocketDebuggerUrl")
    return None


def _navigate_to_nlm(session: CDPSession) -> None:
    """Navigate the current page to NotebookLM and wait for load."""
    session.send("Page.enable")
    session.send("Page.navigate", {"url": f"https://{_NLM_HOST}"})
    # Wait for page to load
    time.sleep(5)


# ── Main capture function ────────────────────────────────────────────────

def capture_nlm_cookies(
    profile_dir: Optional[str] = None,
    force_new_instance: bool = False,
) -> Dict[str, Any]:
    """Capture Google auth cookies for NotebookLM via Chrome CDP.

    This is the primary function for automated cookie capture. It:
    1. Checks if Chrome is running with remote debugging
    2. Launches Chrome if not (using existing user profile)
    3. Navigates to NotebookLM
    4. Extracts cookies via CDP Network.getAllCookies
    5. Stores cookies and metadata for the proxy

    Args:
        profile_dir: Chrome user data dir. Auto-detected if None.
        force_new_instance: Force launch new Chrome instance.

    Returns:
        Dict with: imported_cookies, bl, f_sid, status, and any error.
    """
    _chrome_proc: Optional[subprocess.Popen] = None
    cdp_session: Optional[CDPSession] = None

    try:
        # Step 1: Ensure CDP is available
        if not _is_cdp_running() or force_new_instance:
            logger.info("Chrome CDP not running — launching Chrome")
            _chrome_proc = _launch_chrome_with_debugging(profile_dir)
            if not _chrome_proc:
                return {
                    "error": "chrome_not_found",
                    "detail": "Google Chrome not found. Install it and try again.",
                    "status": "error",
                }
            if not _is_cdp_running():
                return {
                    "error": "cdp_not_responding",
                    "detail": f"Chrome launched but CDP not responding on port {_CDP_PORT}",
                    "status": "error",
                }

        # Step 2: Find or navigate to NotebookLM page
        try:
            targets = _cdp_json("json")
        except Exception as exc:
            return {"error": "cdp_json_failed", "detail": str(exc), "status": "error"}

        # Find a suitable target (page) to connect to
        page_ws_url = None
        nlm_ws_url = None
        for t in targets:
            url = t.get("url", "")
            if _NLM_HOST in url:
                nlm_ws_url = t.get("webSocketDebuggerUrl")
            elif t.get("type") == "page" and "devtools" not in url:
                page_ws_url = t.get("webSocketDebuggerUrl")

        target_ws = nlm_ws_url or page_ws_url
        if not target_ws:
            return {"error": "no_cdp_target", "detail": "No suitable Chrome page found", "status": "error"}

        # Step 3: Connect and get cookies
        try:
            cdp_session = CDPSession(target_ws)
            cdp_session.connect()
        except RuntimeError as exc:
            # websocket-client not installed
            return {"error": "dependency_missing", "detail": str(exc), "status": "error"}
        except Exception as exc:
            return {"error": "cdp_connect_failed", "detail": str(exc), "status": "error"}

        # Navigate to NLM if not already there
        if not nlm_ws_url:
            logger.info("Navigating to NotebookLM...")
            _navigate_to_nlm(cdp_session)

        # Step 4: Get all cookies for google.com domains
        response = cdp_session.send("Network.getAllCookies")
        all_cookies = response.get("result", {}).get("cookies", [])

        # Filter to Google auth cookies
        cookies: Dict[str, str] = {}
        for c in all_cookies:
            domain = c.get("domain", "")
            name = c.get("name", "")
            value = c.get("value", "")
            if "google" in domain and (
                name in _AUTH_COOKIE_NAMES
                or any(name.startswith(p) for p in ("__Secure-", "SIDCC"))
            ):
                cookies[name] = value

        logger.info("Captured %d auth cookies via CDP", len(cookies))

        # Step 5: Try to extract bl, f.sid, and at token from page JavaScript
        meta: Dict[str, str] = {}
        try:
            js_result = cdp_session.send("Runtime.evaluate", {
                "expression": (
                    "JSON.stringify({"
                    "  bl: (window.WIZ_global_data && (window.WIZ_global_data.QrtxK || window.WIZ_global_data.cfb2h)) || '',"
                    "  f_sid: (window.WIZ_global_data && (window.WIZ_global_data.IxjpMA || window.WIZ_global_data.FdrFJe)) || '',"
                    "  at: (window.WIZ_global_data && window.WIZ_global_data.SNlM0e) || '',"
                    "  origin: location.origin"
                    "})"
                ),
                "returnByValue": True,
            })
            if js_result.get("result", {}).get("result", {}).get("value"):
                page_data = json.loads(js_result["result"]["result"]["value"])
                if page_data.get("bl"):
                    meta["bl"] = page_data["bl"]
                if page_data.get("f_sid"):
                    meta["f_sid"] = str(page_data["f_sid"])
                if page_data.get("at"):
                    meta["at"] = page_data["at"]
                logger.info(
                    "Extracted from page JS: bl=%s f_sid=%s at_present=%s",
                    meta.get("bl"), meta.get("f_sid"), bool(meta.get("at")),
                )
        except Exception as exc:
            logger.debug("Could not extract bl/f_sid/at from JS: %s", exc)

        if not cookies:
            return {
                "error": "no_auth_cookies",
                "detail": (
                    "Chrome CDP connected but no Google auth cookies found. "
                    "The Chrome instance may not be logged in to Google. "
                    "Log in to Google in Chrome and try again."
                ),
                "status": "error",
                "meta": meta,
            }

        # Step 6: Persist cookies and meta
        _save_cookies(cookies)
        existing_meta = _load_meta()
        if meta.get("bl"):
            existing_meta["bl"] = meta["bl"]
        if meta.get("f_sid"):
            existing_meta["f_sid"] = meta["f_sid"]
        if meta.get("at"):
            existing_meta["at"] = meta["at"]
        _save_meta(existing_meta)

        return {
            "imported_cookies": len(cookies),
            "cookie_names": list(cookies.keys()),
            "bl": existing_meta.get("bl"),
            "f_sid": existing_meta.get("f_sid"),
            "at_present": bool(existing_meta.get("at")),
            "status": "ok",
        }

    finally:
        if cdp_session:
            cdp_session.close()
        # Don't kill Chrome if it was already running
        if _chrome_proc:
            try:
                _chrome_proc.terminate()
            except Exception:
                pass


# ── Persistence helpers (mirrors nlm_live_proxy.py) ─────────────────────

def _load_cookies() -> Dict[str, str]:
    try:
        if _COOKIES_FILE.exists():
            return json.loads(_COOKIES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cookies(cookies: Dict[str, str]) -> None:
    _COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Merge with existing
    existing = _load_cookies()
    merged = {**existing, **cookies}
    _COOKIES_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    logger.info("Saved %d cookies to %s", len(merged), _COOKIES_FILE)


def _load_meta() -> Dict[str, str]:
    try:
        if _META_FILE.exists():
            return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"bl": "boq_labs-tailwind-frontend_20260226.08_p0", "f_sid": "-1"}


def _save_meta(meta: Dict[str, str]) -> None:
    _META_FILE.parent.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )
    parser = argparse.ArgumentParser(description="Capture NotebookLM cookies via Chrome CDP")
    parser.add_argument("--profile", help="Chrome user data directory")
    parser.add_argument("--force", action="store_true", help="Force new Chrome instance")
    args = parser.parse_args()

    result = capture_nlm_cookies(profile_dir=args.profile, force_new_instance=args.force)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)
