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
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.argus.config import CDP_URL

logger = logging.getLogger(__name__)

# Domains to harvest cookies from
_GOOGLE_DOMAINS = [
    "https://notebooklm.google.com",
    "https://accounts.google.com",
    "https://myaccount.google.com",
    "https://google.com",
]

_POOL_PATH = ROOT / "data" / "accounts" / "pool.json"
_TOKEN_DIR = ROOT / "data" / "argus" / "tokens"

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

        return cookies, account_name


# ──── Pool update ─────────────────────────────────────────────────────────────

def update_account_pool(cookies: Dict[str, str], account_name: str) -> None:
    """Update data/accounts/pool.json with fresh cookies."""
    _POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing pool
    pool_data: List[Dict[str, Any]] = []
    if _POOL_PATH.exists():
        try:
            pool_data = json.loads(_POOL_PATH.read_text(encoding="utf-8")).get("accounts", [])
        except Exception:
            pool_data = []

    # Find or create entry
    existing = next((a for a in pool_data if a["name"] == account_name), None)
    if existing:
        existing["cookies"].update(cookies)
        existing["added_at"] = time.time()
        existing["services"] = list(set(existing.get("services", []) + ["nlm", "gemini", "colab"]))
        logger.info("Updated existing account: %s", account_name)
    else:
        pool_data.append({
            "name": account_name,
            "cookies": cookies,
            "authuser": 0,
            "services": ["nlm", "gemini", "colab"],
            "rate_limited": {},
            "added_at": time.time(),
            "at_token": None,
        })
        logger.info("Added new account: %s", account_name)

    _POOL_PATH.write_text(
        json.dumps({"accounts": pool_data}, indent=2),
        encoding="utf-8",
    )
    logger.info("Pool saved → %s (%d accounts)", _POOL_PATH, len(pool_data))

    # Also save a timestamped snapshot
    snap = _TOKEN_DIR / f"{account_name}_{int(time.time())}.json"
    snap.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
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
    cookies, account_name = await harvest_cookies(args.url)

    if args.account:
        account_name = args.account

    print_cookies(cookies, account_name)

    if not args.show and cookies:
        update_account_pool(cookies, account_name)
        print(f"\n[harvester] Pool updated. Direct clients will use fresh cookies on next call.")
    elif args.show:
        print("\n[harvester] --show mode: not saving to pool.")


if __name__ == "__main__":
    asyncio.run(main())
