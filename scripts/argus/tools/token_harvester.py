"""ARGUS Token Harvester — extract live Google cookies from running Chrome.

Instead of manually exporting HARs, this pulls cookies directly from
Chrome's cookie store via CDP, updates the Google account pool, and
refreshes all downstream direct clients (NLM, Gemini, Colab, etc.).

Usage:
    python -m scripts.argus.tools.token_harvester            # harvest + save
    python -m scripts.argus.tools.token_harvester --show     # print to stdout only
    python -m scripts.argus.tools.token_harvester --account myname
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.integrations.google_account_pool import GoogleAccount, GoogleAccountPool
from engine.integrations.google_service_profiles import normalize_google_services
from scripts.har_capture import (
    NLM_URL,
    _build_nlm_session_metadata,
    _get_account_name_from_tab,
    _get_cdp_tabs,
    _get_cookies_from_tab,
    _get_nlm_session_from_tab,
    _navigate_and_get_cookies,
    _select_cdp_tab,
)
from scripts.argus.config import CDP_URL
from scripts.argus.paths import TOKENS_DIR

logger = logging.getLogger(__name__)

# Domains to harvest cookies from
_GOOGLE_DOMAINS = [
    "https://notebooklm.google.com",
    "https://accounts.google.com",
    "https://myaccount.google.com",
    "https://google.com",
]

_POOL_PATH = ROOT / "data" / "accounts" / "pool.json"
_TOKEN_DIR = TOKENS_DIR
_DEFAULT_SERVICES = ["notebooklm", "aistudio", "colab"]

# Same list as har_extractor.py — these are the cookies we need
COOKIE_NAMES = [
    "SID", "__Secure-1PSID", "__Secure-3PSID",
    "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "AEC", "NID",
]


# ──── SAPISIDHASH generation ──────────────────────────────────────────────────

def generate_sapisid_hash(sapisid: str, origin: str = "https://notebooklm.google.com") -> str:
    """Generate the SAPISIDHASH Authorization header value.

    Format: SAPISIDHASH <timestamp>_<sha1(timestamp + ' ' + sapisid + ' ' + origin)>
    """
    ts = str(int(time.time()))
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


# ──── CDP cookie extraction ───────────────────────────────────────────────────

async def harvest_cookies(url_pattern: str = "notebooklm") -> Tuple[Dict[str, str], str]:
    """Backward-compatible wrapper returning only cookies and account name."""
    capture = await harvest_capture(url_pattern)
    return capture.get("cookies", {}), capture.get("account_name", "harvested")


async def _harvest_via_direct_cdp(url_pattern: str = "notebooklm") -> Optional[Dict[str, Any]]:
    """Harvest cookies and NotebookLM session metadata via direct CDP calls."""
    tabs = _get_cdp_tabs()
    if not tabs:
        return None

    preferred_patterns = [url_pattern] if url_pattern else []
    ws_url, page_url = _select_cdp_tab(tabs, preferred_patterns=preferred_patterns)
    if not ws_url:
        return None

    cookies = await _get_cookies_from_tab(ws_url)
    wants_notebooklm = "notebooklm" in (url_pattern or "").lower()
    ensure_notebooklm = wants_notebooklm and "notebooklm.google.com" not in page_url

    if len(cookies) < 3 and wants_notebooklm:
        logger.info("Direct CDP harvested too few cookies; navigating the live tab to NotebookLM")
        cookies = await _navigate_and_get_cookies(ws_url, NLM_URL)
        ensure_notebooklm = False
        page_url = NLM_URL

    if not cookies:
        return None

    nlm_session: Dict[str, str] = {}
    if wants_notebooklm or "notebooklm.google.com" in page_url:
        nlm_session = await _get_nlm_session_from_tab(ws_url, ensure_notebooklm=ensure_notebooklm)

    account_name = await _get_account_name_from_tab(ws_url) or "harvested"
    at_token = nlm_session.get("at")
    return {
        "cookies": cookies,
        "account_name": account_name,
        "authuser": 0,
        "at_token": at_token,
        "nlm_session": nlm_session,
        "service_sessions": {"notebooklm": nlm_session} if nlm_session else {},
        "services": list(_DEFAULT_SERVICES),
    }


async def _harvest_via_playwright(url_pattern: str = "notebooklm") -> Optional[Dict[str, Any]]:
    """Harvest Google cookies from the running Chrome instance.

    Connects via CDP, reads cookies from the NLM tab context, and returns
    a filtered cookie dict plus the detected account name.

    Returns:
        (cookies_dict, account_name)
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # Get all cookies from context (includes all domains)
        all_cookies = await ctx.cookies(_GOOGLE_DOMAINS)

        cookies: Dict[str, str] = {}
        for c in all_cookies:
            if c["name"] in COOKIE_NAMES:
                cookies[c["name"]] = c["value"]

        # Try to find account name from the NLM page
        account_name = "harvested"
        nlm_page = next((p for p in ctx.pages if "notebooklm" in p.url or "google" in p.url), None)
        if nlm_page:
            try:
                email = await nlm_page.evaluate("""
                    () => {
                        // Try various places Google exposes the account email
                        const meta = document.querySelector('meta[name="account-email"]');
                        if (meta) return meta.content;
                        const data = window.__GSAP_DATA__ || window.__ACCOUNT__;
                        if (data?.email) return data.email;
                        // aria-label on account button
                        const btn = document.querySelector('[aria-label*="@"]');
                        if (btn) {
                            const m = btn.getAttribute('aria-label').match(/\\b[\\w.+-]+@[\\w-]+\\.[\\w.]+/);
                            if (m) return m[0];
                        }
                        return null;
                    }
                """)
                if email:
                    account_name = email.split("@")[0]
                    logger.info("Detected account: %s", email)
            except Exception:
                pass

        nlm_session: Dict[str, str] = {}
        if nlm_page:
            try:
                page_data = await nlm_page.evaluate(
                    """() => ({
                        bl: (() => {
                            const wiz = window.WIZ_global_data || {};
                            const explicit = wiz.QrtxK || wiz.cfb2h || wiz.bl || '';
                            if (typeof explicit === 'string' && explicit.startsWith('boq_labs-tailwind-frontend_')) {
                                return explicit;
                            }
                            for (const value of Object.values(wiz)) {
                                if (typeof value === 'string' && value.startsWith('boq_labs-tailwind-frontend_')) {
                                    return value;
                                }
                            }
                            return '';
                        })(),
                        f_sid: (window.WIZ_global_data && (window.WIZ_global_data.IxjpMA || window.WIZ_global_data.FdrFJe)) || '',
                        at: (window.WIZ_global_data && window.WIZ_global_data.SNlM0e) || '',
                        href: location.href,
                    })"""
                )
                if isinstance(page_data, dict):
                    nlm_session = _build_nlm_session_metadata(page_data)
            except Exception:
                logger.debug("Could not extract NotebookLM session metadata via Playwright", exc_info=True)

        return {
            "cookies": cookies,
            "account_name": account_name,
            "authuser": 0,
            "at_token": nlm_session.get("at"),
            "nlm_session": nlm_session,
            "service_sessions": {"notebooklm": nlm_session} if nlm_session else {},
            "services": list(_DEFAULT_SERVICES),
        }


async def harvest_capture(url_pattern: str = "notebooklm") -> Dict[str, Any]:
    """Harvest a full browser auth bundle from the live Chrome session."""
    try:
        capture = await _harvest_via_direct_cdp(url_pattern)
    except Exception:
        logger.warning("Direct CDP harvest failed; falling back to Playwright", exc_info=True)
        capture = None

    if capture and capture.get("cookies"):
        return capture

    fallback = await _harvest_via_playwright(url_pattern)
    return fallback or {
        "cookies": {},
        "account_name": "harvested",
        "authuser": 0,
        "at_token": None,
        "nlm_session": {},
        "service_sessions": {},
        "services": list(_DEFAULT_SERVICES),
    }


# ──── Pool update ─────────────────────────────────────────────────────────────

def update_account_pool(
    cookies: Dict[str, str],
    account_name: str,
    *,
    session: Optional[Dict[str, str]] = None,
    services: Optional[List[str]] = None,
    authuser: int = 0,
    at_token: Optional[str] = None,
    service_sessions: Optional[Dict[str, Dict[str, str]]] = None,
    pool_path: Optional[Path] = None,
) -> None:
    """Update the account pool with fresh cookies and session metadata."""
    pool_path = pool_path or _POOL_PATH
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    normalized_services = normalize_google_services(services or _DEFAULT_SERVICES)
    normalized_session = dict(session or {})
    normalized_service_sessions = {
        service_name: dict(service_session)
        for service_name, service_session in (service_sessions or {}).items()
        if isinstance(service_session, dict) and service_session
    }
    if normalized_session and "notebooklm" not in normalized_service_sessions:
        normalized_service_sessions["notebooklm"] = dict(normalized_session)

    pool = GoogleAccountPool(pool_path=str(pool_path))
    existing = pool.get_by_name(account_name)
    merged_at_token = at_token or normalized_session.get("at")

    if existing:
        merged_cookies = dict(existing.cookies)
        merged_cookies.update({name: value for name, value in cookies.items() if value})
        existing.cookies = merged_cookies
        existing.added_at = time.time()
        existing.authuser = authuser
        existing.services = normalize_google_services(existing.services + normalized_services)
        if merged_at_token:
            existing.at_token = merged_at_token

        if normalized_session:
            existing.nlm_session = {**existing.nlm_session, **normalized_session}

        for service_name, service_session in normalized_service_sessions.items():
            merged_session = dict(existing.service_sessions.get(service_name, {}))
            merged_session.update({key: value for key, value in service_session.items() if value})
            existing.service_sessions[service_name] = merged_session

        pool.add_account(existing)
        logger.info("Updated existing account: %s", account_name)
    else:
        account = GoogleAccount(
            name=account_name,
            cookies={name: value for name, value in cookies.items() if value},
            authuser=authuser,
            services=normalized_services,
            at_token=merged_at_token,
            nlm_session=normalized_session,
            service_sessions=normalized_service_sessions,
        )
        pool.add_account(account)
        logger.info("Added new account: %s", account_name)

    pool.save()
    logger.info("Pool saved → %s", pool_path)

    # Also save a timestamped snapshot
    snap = _TOKEN_DIR / f"{account_name}_{int(time.time())}.json"
    snap.write_text(
        json.dumps(
            {
                "account_name": account_name,
                "authuser": authuser,
                "services": normalized_services,
                "cookies": {name: value for name, value in cookies.items() if value},
                "nlm_session": normalized_session,
                "service_sessions": normalized_service_sessions,
                "at_token": merged_at_token,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Snapshot → %s", snap)


def print_cookies(cookies: Dict[str, str], account_name: str) -> None:
    """Pretty-print harvested cookies."""
    print(f"\n{'─'*60}")
    print(f"Account : {account_name}")
    print(f"Cookies : {len(cookies)} / {len(COOKIE_NAMES)} expected")
    print(f"{'─'*60}")
    for name in COOKIE_NAMES:
        val = cookies.get(name, "")
        status = "✓" if val else "✗"
        display = (val[:40] + "…") if len(val) > 40 else val
        print(f" {status}  {name:<30} {display}")
    print(f"{'─'*60}")

    if "SAPISID" in cookies:
        h = generate_sapisid_hash(cookies["SAPISID"])
        print(f"\nSAPISDHASH (NLM) : {h}")

    missing = [n for n in COOKIE_NAMES if n not in cookies]
    if missing:
        print(f"\nMissing ({len(missing)}): {', '.join(missing)}")
        print("  → Make sure Chrome is logged into Google and on a Google page.")
    else:
        print("\n✓ All cookies harvested — pool updated.")


async def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="ARGUS Token Harvester")
    ap.add_argument("--show",    action="store_true", help="Print cookies, don't save")
    ap.add_argument("--account", default="",          help="Override account name")
    ap.add_argument("--url",     default="notebooklm", help="Tab URL pattern")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    print("[harvester] Connecting to Chrome...")
    capture = await harvest_capture(args.url)
    cookies = capture.get("cookies", {})
    account_name = capture.get("account_name", "harvested")

    if args.account:
        account_name = args.account

    print_cookies(cookies, account_name)

    if not args.show and cookies:
        update_account_pool(
            cookies,
            account_name,
            session=capture.get("nlm_session"),
            services=capture.get("services"),
            authuser=int(capture.get("authuser", 0) or 0),
            at_token=capture.get("at_token"),
            service_sessions=capture.get("service_sessions"),
        )
        print(f"\n[harvester] Pool updated. Direct clients will use fresh cookies on next call.")
    elif args.show:
        print("\n[harvester] --show mode: not saving to pool.")


if __name__ == "__main__":
    asyncio.run(main())
