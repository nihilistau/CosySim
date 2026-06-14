"""
GitHub Account Cookie Importer
===============================

Utilities for importing GitHub browser cookies into the GoogleAccountPool so
they can be used by GithubCopilotClient.

Version: v1.57.2 [2026-03-27]
Author:  CosySim Team

Change Log:
    v1.57.2 [2026-03-27] — Added CLI with auto-detect account name, --analyze, --name
    v1.57.1 [2026-03-26] — Initial implementation

Usage:
    # Import cookies from HAR (auto-detects GitHub username)
    python -m engine.integrations.github_account_importer path/to/github.har

    # Import with explicit account name
    python -m engine.integrations.github_account_importer path/to/github.har --name nihilistau

    # Analyze HAR without importing (dry-run)
    python -m engine.integrations.github_account_importer path/to/github.har --analyze

    # Import from JSON cookies file
    python -m engine.integrations.github_account_importer cookies.json --json --name nihilistau
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FALLBACK_COOKIES_DIR = os.path.join("data", "accounts")


# ──── HAR import ─────────────────────────────────────────────────────────────


def import_github_har(har_path: str, account_name: str) -> Dict[str, Any]:
    """Extract GitHub cookies from a HAR file and add to the account pool.

    Args:
        har_path: Absolute or relative path to the .har file.
        account_name: Human-readable name for the account (e.g. "nihilistcod").

    Returns:
        Dict with ``name``, ``cookie_count``, and ``cookies`` summary.

    Raises:
        FileNotFoundError: If the HAR file does not exist.
        ValueError: If no GitHub cookies are found in the file.
    """
    if not os.path.exists(har_path):
        raise FileNotFoundError(f"HAR file not found: {har_path}")

    with open(har_path, "r", encoding="utf-8") as fh:
        har = json.load(fh)

    github_cookies: Dict[str, str] = {}
    entries = har.get("log", {}).get("entries", [])

    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        if "github.com" not in url:
            continue

        # Extract from request cookies
        for cookie in entry.get("request", {}).get("cookies", []):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name and value:
                github_cookies[name] = value

        # Also extract from Cookie header
        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header.get("value", "").split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, _, v = part.partition("=")
                        github_cookies[k.strip()] = v.strip()

    if not github_cookies:
        raise ValueError(f"No GitHub cookies found in HAR file: {har_path}")

    return _register_account(account_name, github_cookies)


# ──── JSON import ─────────────────────────────────────────────────────────────


def import_github_cookies_json(json_path: str, account_name: str) -> Dict[str, Any]:
    """Import GitHub cookies from a pre-extracted JSON file.

    The JSON file should be a flat mapping of cookie-name → cookie-value,
    as produced by browser extension exports.  The standard location is
    ``data/accounts/github_{account_name}_cookies.json``.

    Args:
        json_path: Path to the cookies JSON file.
        account_name: Human-readable name for the account.

    Returns:
        Dict with ``name``, ``cookie_count``, and ``cookies`` summary.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the file does not contain a valid cookies dict.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Cookies JSON not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as fh:
        cookies = json.load(fh)

    if not isinstance(cookies, dict):
        raise ValueError(
            f"Expected a flat dict in {json_path}, got {type(cookies).__name__}"
        )

    # Handle Netscape / array format (list of {name, value} dicts)
    if isinstance(cookies, list):
        cookies = {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}

    if not cookies:
        raise ValueError(f"No cookies found in {json_path}")

    return _register_account(account_name, cookies)


# ──── Internal helpers ────────────────────────────────────────────────────────


def _register_account(account_name: str, cookies: Dict[str, str]) -> Dict[str, Any]:
    """Add account to pool with service="github" and persist.

    Args:
        account_name: Account identifier.
        cookies: Cookie mapping to store.

    Returns:
        Summary dict with ``name``, ``cookie_count``, ``services``.
    """
    from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

    pool = get_account_pool()
    existing = pool.get_by_name(account_name)

    if existing is not None:
        # Update cookies; preserve other services
        existing.cookies = cookies
        if "github" not in existing.services:
            existing.services.append("github")
        pool.add_account(existing)
        logger.info(
            "Updated account '%s' with %d GitHub cookies",
            account_name,
            len(cookies),
        )
    else:
        account = GoogleAccount(
            name=account_name,
            cookies=cookies,
            services=["github"],
        )
        pool.add_account(account)
        logger.info(
            "Added account '%s' with %d GitHub cookies",
            account_name,
            len(cookies),
        )

    pool.save()

    return {
        "name": account_name,
        "cookie_count": len(cookies),
        "services": pool.get_by_name(account_name).services,  # type: ignore[union-attr]
        "cookies": {k: v[:8] + "..." for k, v in list(cookies.items())[:5]},
    }


# ──── Auto-detect helpers ────────────────────────────────────────────────────


def _detect_github_username(har_path: str) -> Optional[str]:
    """Try to detect the GitHub username from HAR cookies or URLs.

    Looks for the ``dotcom_user`` cookie first, then falls back to
    matching authenticated GitHub profile URLs.

    Args:
        har_path: Path to the HAR file.

    Returns:
        Detected username or None.
    """
    with open(har_path, "r", encoding="utf-8") as fh:
        har = json.load(fh)

    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        url = req.get("url", "")
        if "github.com" not in url:
            continue

        # Check cookies array for dotcom_user
        for cookie in req.get("cookies", []):
            if cookie.get("name") == "dotcom_user":
                return cookie.get("value", "")

        # Check Cookie header for dotcom_user
        for header in req.get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header.get("value", "").split(";"):
                    part = part.strip()
                    if part.startswith("dotcom_user="):
                        return part.split("=", 1)[1].strip()

    return None


def _analyze_har(har_path: str) -> Dict[str, Any]:
    """Quick analysis of GitHub content in a HAR file (dry-run).

    Args:
        har_path: Path to the HAR file.

    Returns:
        Summary dict with entry counts, detected username, cookie names.
    """
    with open(har_path, "r", encoding="utf-8") as fh:
        har = json.load(fh)

    entries = har.get("log", {}).get("entries", [])
    github_entries = [
        e for e in entries
        if "github.com" in e.get("request", {}).get("url", "")
    ]

    # Collect all cookie names from github entries
    cookie_names: set = set()
    for entry in github_entries:
        for cookie in entry.get("request", {}).get("cookies", []):
            name = cookie.get("name", "")
            if name:
                cookie_names.add(name)
        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header.get("value", "").split(";"):
                    part = part.strip()
                    if "=" in part:
                        cookie_names.add(part.split("=", 1)[0].strip())

    username = _detect_github_username(har_path)

    # Unique github domains
    domains: set = set()
    for e in github_entries:
        url = e.get("request", {}).get("url", "")
        if "://" in url:
            domains.add(url.split("://")[1].split("/")[0])

    return {
        "total_entries": len(entries),
        "github_entries": len(github_entries),
        "detected_username": username,
        "cookie_names": sorted(cookie_names),
        "cookie_count": len(cookie_names),
        "github_domains": sorted(domains),
        "has_session": "user_session" in cookie_names,
        "has_logged_in": "logged_in" in cookie_names,
    }


# ──── CLI ─────────────────────────────────────────────────────────────────────
# v1.57.2 [2026-03-27] — CLI with auto-detect, --analyze, --name, --json


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    # Ensure project root is on sys.path so engine imports work
    _ROOT = Path(__file__).resolve().parent.parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    # Also ensure CWD is project root for relative pool.json paths
    os.chdir(_ROOT)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Import GitHub cookies from HAR/JSON into the account pool.",
        epilog="Examples:\n"
               "  python -m engine.integrations.github_account_importer github.har\n"
               "  python -m engine.integrations.github_account_importer github.har --name nihilistau\n"
               "  python -m engine.integrations.github_account_importer github.har --analyze\n"
               "  python -m engine.integrations.github_account_importer cookies.json --json --name myaccount\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="Path to .har or .json file")
    parser.add_argument("--name", "-n", help="Account name (auto-detected from HAR if omitted)")
    parser.add_argument("--json", "-j", action="store_true", help="Import from JSON cookies file instead of HAR")
    parser.add_argument("--analyze", "-a", action="store_true", help="Analyze HAR without importing (dry-run)")

    args = parser.parse_args()
    filepath = args.file

    # Resolve relative paths
    if not os.path.isabs(filepath):
        filepath = str(_ROOT / filepath)

    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    # ── Analyze mode (dry-run) ──
    if args.analyze:
        info = _analyze_har(filepath)
        print(f"\n  GitHub HAR Analysis: {os.path.basename(filepath)}")
        print(f"  {'-' * 50}")
        print(f"  Total entries:      {info['total_entries']}")
        print(f"  GitHub entries:     {info['github_entries']}")
        print(f"  Detected username:  {info['detected_username'] or '(none)'}")
        print(f"  Cookies found:      {info['cookie_count']}")
        print(f"  Has user_session:   {'yes' if info['has_session'] else 'no'}")
        print(f"  Has logged_in:      {'yes' if info['has_logged_in'] else 'no'}")
        print(f"  GitHub domains:     {', '.join(info['github_domains'])}")
        print(f"\n  Cookies: {', '.join(info['cookie_names'])}")
        print()
        sys.exit(0)

    # ── Determine account name ──
    account_name = args.name
    if not account_name and not args.json:
        account_name = _detect_github_username(filepath)
        if account_name:
            print(f"  Auto-detected GitHub username: {account_name}")
        else:
            print("ERROR: Could not detect GitHub username from HAR. Use --name <account>")
            sys.exit(1)
    elif not account_name:
        print("ERROR: --name is required for JSON imports")
        sys.exit(1)

    # ── Import ──
    try:
        if args.json:
            result = import_github_cookies_json(filepath, account_name)
        else:
            result = import_github_har(filepath, account_name)

        print(f"\n  GitHub Cookie Import: SUCCESS")
        print(f"  {'-' * 50}")
        print(f"  Account:    {result['name']}")
        print(f"  Cookies:    {result['cookie_count']}")
        print(f"  Services:   {', '.join(result['services'])}")
        print(f"  Preview:    {json.dumps(result['cookies'], indent=2)}")
        print()

    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
