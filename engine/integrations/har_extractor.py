"""HAR file extractor for Google authentication credentials.

Parses browser HAR (HTTP Archive) files to extract session cookies,
auth headers, and XSRF tokens needed for direct Google API access.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger(__name__)

# Canonical cookie names used by Google accounts
COOKIE_NAMES: List[str] = [
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "SIDCC",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
    "AEC",
    "NID",
]


class HARExtractor:
    """Extracts Google auth data from a browser HAR file.

    Args:
        har_path: Path to the .har file exported from browser DevTools.
    """

    def __init__(self, har_path: str) -> None:
        self._har_path = har_path
        self._entries: List[Dict[str, Any]] = []
        self._load()

    # ──── Loading ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load and parse the HAR file."""
        logger.debug("Loading HAR file: %s", self._har_path)
        with open(self._har_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._entries = data.get("log", {}).get("entries", [])
        logger.debug("Loaded %d HAR entries", len(self._entries))

    # ──── Cookie extraction ───────────────────────────────────────────────────

    def extract_cookies(self, domain: str = "google.com") -> Dict[str, str]:
        """Extract cookies for a given domain from the HAR entries.

        Scans all request cookies in entries whose URL contains the domain,
        collecting the canonical Google session cookie names.

        Args:
            domain: Domain to filter entries by (e.g. "google.com").

        Returns:
            Mapping of cookie name to cookie value for matching cookies.
        """
        collected: Dict[str, str] = {}
        target_names = set(COOKIE_NAMES)

        for entry in self._entries:
            request = entry.get("request", {})
            url = request.get("url", "")
            if domain not in url:
                continue

            # Check request cookies
            for cookie in request.get("cookies", []):
                name = cookie.get("name", "")
                value = cookie.get("value", "")
                if name in target_names and name not in collected:
                    collected[name] = value

            # Also check Cookie header (some HAR exporters only put it there)
            for header in request.get("headers", []):
                if header.get("name", "").lower() == "cookie":
                    for part in header.get("value", "").split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, _, v = part.partition("=")
                            k = k.strip()
                            v = v.strip()
                            if k in target_names and k not in collected:
                                collected[k] = v

            if len(collected) >= len(target_names):
                break

        logger.debug("Extracted %d cookies for domain '%s'", len(collected), domain)
        return collected

    # ──── Auth header extraction ──────────────────────────────────────────────

    def extract_authuser(self) -> int:
        """Extract the x-goog-authuser header value.

        Returns:
            Integer authuser index (typically 0), or 0 if not found.
        """
        for entry in self._entries:
            for header in entry.get("request", {}).get("headers", []):
                if header.get("name", "").lower() == "x-goog-authuser":
                    try:
                        return int(header.get("value", "0"))
                    except (ValueError, TypeError):
                        return 0
        return 0

    def extract_at_token(self) -> Optional[str]:
        """Extract the XSRF `at` token from request post data.

        The `at` token appears in form-encoded bodies as `at=<token>`.

        Returns:
            The at token string, or None if not found.
        """
        for entry in self._entries:
            post_data = entry.get("request", {}).get("postData", {})
            text = post_data.get("text", "")
            if not text:
                continue
            # Parse form-encoded body
            try:
                params = parse_qs(text)
                if "at" in params:
                    return params["at"][0]
            except Exception:
                pass
            # Also check raw f.req bodies for at= patterns
            if "at=" in text:
                for part in text.split("&"):
                    if part.startswith("at="):
                        value = unquote(part[3:])
                        if value:
                            return value
        return None

    # ──── Convenience ─────────────────────────────────────────────────────────

    def to_account_dict(self, account_name: str) -> Dict[str, Any]:
        """Build a full account dictionary suitable for GoogleAccountPool.

        Args:
            account_name: Human-readable name for this account.

        Returns:
            Dictionary with keys: name, cookies, authuser, at_token.
        """
        cookies = self.extract_cookies("google.com")
        authuser = self.extract_authuser()
        at_token = self.extract_at_token()

        return {
            "name": account_name,
            "cookies": cookies,
            "authuser": authuser,
            "at_token": at_token,
        }
