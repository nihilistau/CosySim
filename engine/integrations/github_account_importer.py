"""GitHub account cookie importer.

Utilities for importing GitHub browser cookies into the GoogleAccountPool so
they can be used by GithubCopilotClient.
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
