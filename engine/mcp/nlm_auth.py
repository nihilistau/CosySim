"""NLM Auth — Cookie, session token, and build label management for NotebookLM.

Handles persistence and refresh of Google auth cookies, SAPISIDHASH computation,
build label (bl) tracking, and f.sid / at token extraction from WIZ_global_data.
Extracted from nlm_live_proxy.py to isolate auth concerns.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from engine.mcp.nlm_rpc_constants import (  # noqa: E402
    _DEFAULT_BL,
    _DEFAULT_BL_DATE,
    _is_valid_nlm_build_label,
)

logger = logging.getLogger(__name__)

# ── Path constants (defined here as canonical source for auth paths) ──────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_FILE = _PROJECT_ROOT / "data" / "nlm_cookies.json"
_META_FILE = _PROJECT_ROOT / "data" / "nlm_meta.json"
_NLM_HOST = "notebooklm.google.com"
_COOKIES_LOCK = threading.Lock()


# ════════════════════════════════════════════════════════════════════════════
# META / BUILD LABEL MANAGEMENT
#
# The batchexecute URL requires two session parameters:
#   bl      — build label; stable per Google frontend deploy, changes ~weekly.
#             Format: boq_labs-tailwind-frontend_YYYYMMDD.NN_p0
#   f.sid   — server session ID; extracted from the NLM page's WIZ_global_data.
#   at      — anti-forgery token; also from WIZ_global_data (key "SNlM0e").
#
# When bl is stale, batchexecute silently returns null for all calls.
# Refresh via: POST /cookies/refresh  or  POST /meta  or  re-import a HAR.
# ════════════════════════════════════════════════════════════════════════════

def _load_meta() -> Dict[str, str]:
    """Load stored build label and session meta from disk."""
    try:
        if _META_FILE.exists():
            return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"bl": _DEFAULT_BL, "f_sid": "-1"}


def _save_meta(meta: Dict[str, str]) -> None:
    """Persist build label and session meta to disk."""
    import datetime
    # Stamp BL update time when BL changes
    existing = _load_meta()
    if meta.get("bl") and meta.get("bl") != existing.get("bl"):
        meta["bl_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _META_FILE.parent.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _get_bl() -> str:
    """Return the current build label, falling back to default.

    Logs a warning when the stored BL is more than 8 days old since
    Google typically deploys new frontends weekly.
    """
    meta = _load_meta()
    bl = meta.get("bl", _DEFAULT_BL)
    # Check staleness using bl_updated_at if present
    updated_at = meta.get("bl_updated_at")
    if updated_at:
        try:
            import datetime
            age_days = (datetime.datetime.now(datetime.timezone.utc) -
                        datetime.datetime.fromisoformat(updated_at)).days
            if age_days >= 8:
                logger.warning(
                    "NLM build label is %d days old (%s). "
                    "Google may have deployed a new frontend — "
                    "consider importing a fresh HAR or CDP capture.",
                    age_days, bl,
                )
        except Exception:
            pass
    return bl


def _get_fsid() -> str:
    """Return the current f.sid session ID."""
    return _load_meta().get("f_sid", "-1")


def refresh_session_tokens() -> bool:
    """Refresh f.sid and at token by loading the NLM main page with stored cookies.

    Call this when batchexecute returns null data (stale f.sid / at token).
    Extracts tokens from ``WIZ_global_data`` in the page HTML — tries multiple
    known key variants since Google obfuscates these names per build:

    - f.sid:  ``IxjpMA``, ``FdrFJe``
    - at:     ``SNlM0e``
    - bl:     ``QrtxK``, ``cfb2h`` (also detected from boq_ string in HTML)

    Persists any found values to ``data/nlm_meta.json``.

    Returns:
        True if at least one token was refreshed, False otherwise.
    """
    cookies = _load_cookies()
    if not cookies:
        logger.warning("No cookies stored — cannot refresh session tokens")
        return False
    headers = {
        "Cookie": _cookies_header(cookies),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        req = urllib.request.Request(f"https://{_NLM_HOST}/", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.error("Failed to load NLM page for token refresh: %s", exc)
        return False

    m = re.search(r"WIZ_global_data\s*=\s*({.*?});", html, re.DOTALL)
    wiz: Dict[str, Any] = {}
    if m:
        try:
            wiz = json.loads(m.group(1))
        except Exception as exc:
            logger.warning("Failed to parse WIZ_global_data: %s", exc)

    invalid_build_label: Optional[str] = None
    for key in ("QrtxK", "cfb2h"):
        val = wiz.get(key)
        if isinstance(val, str) and val.startswith("boq_") and not _is_valid_nlm_build_label(val):
            invalid_build_label = val
            break
    if not invalid_build_label:
        match = re.search(r'"(boq_[^"]+)"', html)
        if match and not _is_valid_nlm_build_label(match.group(1)):
            invalid_build_label = match.group(1)
    if invalid_build_label or "identityfrontendauthuiserver" in html.lower():
        logger.warning(
            "Token refresh landed on a non-NotebookLM page; refusing to persist session tokens (build=%s)",
            invalid_build_label or "unknown",
        )
        return False

    meta = _load_meta()
    updated = False

    # f.sid — try known key variants in order of likelihood
    for key in ("IxjpMA", "FdrFJe"):
        if wiz.get(key):
            meta["f_sid"] = str(wiz[key])
            updated = True
            logger.debug("Extracted f.sid from WIZ_global_data.%s", key)
            break

    # at anti-forgery token
    if wiz.get("SNlM0e"):
        meta["at"] = wiz["SNlM0e"]
        updated = True
        logger.debug("Extracted at from WIZ_global_data.SNlM0e")

    # bl — try WIZ_global_data keys, then fall back to boq_ string scan
    # Only accept values that look like real build labels (boq_ prefix)
    for key in ("QrtxK", "cfb2h"):
        val = wiz.get(key)
        if val and isinstance(val, str) and _is_valid_nlm_build_label(val):
            new_bl = val
            if new_bl != meta.get("bl"):
                meta["bl"] = new_bl
                updated = True
                logger.info("Updated build label from WIZ_global_data.%s: %s", key, new_bl)
            break
    else:
        bl_match = re.search(r'"(boq_labs-tailwind-frontend_[^"]+)"', html)
        if bl_match:
            new_bl = bl_match.group(1)
            if new_bl != meta.get("bl"):
                meta["bl"] = new_bl
                updated = True
                logger.info("Updated build label from HTML scan: %s", new_bl)

    if updated:
        _save_meta(meta)
        logger.info(
            "Session tokens refreshed: f.sid=%s at_present=%s bl=%s",
            meta.get("f_sid"), bool(meta.get("at")), meta.get("bl"),
        )
    else:
        logger.warning(
            "refresh_session_tokens: no tokens found in page "
            "(WIZ keys present: %s)", list(wiz.keys())[:10] if wiz else "none"
        )
    return updated


# ════════════════════════════════════════════════════════════════════════════
# COOKIE MANAGEMENT
#
# Google auth requires a set of session cookies.  The critical ones are:
#   SID, SSID, APISID, SAPISID  — core Google session tokens
#   __Secure-3PSID, __Secure-3PAPISID  — same-site secure variants
#   HSID  — security cookie preventing CSRF
#   NID   — Google preference cookie (sometimes needed for API calls)
#
# Cookies are stored in data/nlm_cookies.json (thread-safe via _COOKIES_LOCK).
# Obtain them via: HAR import, CDP capture, or DevTools manual copy.
#
# The SAPISIDHASH in the Authorization header is derived from SAPISID:
#   SHA1(unix_timestamp + " " + SAPISID + " " + "https://notebooklm.google.com")
# This is a Google-wide anti-abuse mechanism; without it, API calls return 401.
# ════════════════════════════════════════════════════════════════════════════

def _load_cookies() -> Dict[str, str]:
    """Load stored Google auth cookies from disk."""
    with _COOKIES_LOCK:
        if not _COOKIES_FILE.exists():
            return {}
        try:
            return json.loads(_COOKIES_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load NLM cookies: %s", exc)
            return {}


def _save_cookies(cookies: Dict[str, str]) -> None:
    """Persist Google auth cookies to disk."""
    _COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _COOKIES_LOCK:
        _COOKIES_FILE.write_text(
            json.dumps(cookies, indent=2), encoding="utf-8"
        )


def extract_cookies_from_har(har_path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Extract Google auth cookies AND metadata (bl, f.sid) from a HAR file.

    Looks for requests to notebooklm.google.com and extracts:
    - Auth cookies sent with requests
    - Build label (bl) from URL parameters
    - Session ID (f.sid) from URL parameters

    Args:
        har_path: Path to the .har file.

    Returns:
        Tuple of (cookies_dict, meta_dict) where meta has keys 'bl', 'f_sid', 'at'.
    """
    try:
        with open(har_path, "r", encoding="utf-8", errors="replace") as fh:
            har = json.load(fh)
    except Exception as exc:
        logger.error("Could not read HAR file %s: %s", har_path, exc)
        return {}, {}

    cookies: Dict[str, str] = {}
    meta: Dict[str, str] = {}

    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        if _NLM_HOST not in url:
            continue

        # Extract bl and f.sid from batchexecute URLs
        if "batchexecute" in url:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if "bl" in params and not meta.get("bl"):
                meta["bl"] = params["bl"][0]
                logger.info("Extracted bl from HAR: %s", meta["bl"])
            if "f.sid" in params and not meta.get("f_sid"):
                meta["f_sid"] = params["f.sid"][0]
                logger.info("Extracted f.sid from HAR: %s", meta["f_sid"])
            # Extract 'at' anti-forgery token from POST body
            if not meta.get("at"):
                post_data = entry.get("request", {}).get("postData", {})
                post_text = post_data.get("text", "")
                if post_text:
                    parsed_body = urllib.parse.parse_qs(post_text)
                    if "at" in parsed_body:
                        meta["at"] = parsed_body["at"][0]
                        logger.info("Extracted at token from HAR postData")

        # Cookies in request headers
        for header in entry.get("request", {}).get("headers", []):
            if header.get("name", "").lower() == "cookie":
                for part in header["value"].split(";"):
                    part = part.strip()
                    if "=" in part:
                        name, _, value = part.partition("=")
                        cookies[name.strip()] = value.strip()
        # Cookies as structured objects
        for c in entry.get("request", {}).get("cookies", []):
            if isinstance(c, dict) and c.get("name"):
                cookies[c["name"]] = c.get("value", "")

        # Also check response Set-Cookie headers for fresh tokens
        for header in entry.get("response", {}).get("headers", []):
            if header.get("name", "").lower() == "set-cookie":
                parts = header["value"].split(";")[0].strip()
                if "=" in parts:
                    name, _, value = parts.partition("=")
                    cookies[name.strip()] = value.strip()

    # Keep only the auth-relevant Google session cookies
    _AUTH_PREFIXES = ("SID", "SSID", "APISID", "SAPISID", "HSID", "OSID",
                      "__Secure-", "NID", "1P_JAR", "AEC", "SOCS",
                      "CONSENT", "SEARCH_SAMESITE", "LSID", "SIDCC")
    filtered = {k: v for k, v in cookies.items()
                if any(k.startswith(p) for p in _AUTH_PREFIXES)}
    logger.info("Extracted %d auth cookies from HAR (kept %d after filter)",
                len(cookies), len(filtered))
    return filtered, meta


def _cookies_header(cookies: Dict[str, str]) -> str:
    """Format cookies dict as HTTP Cookie header value."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _sapisid_hash(cookies: Dict[str, str]) -> str:
    """Compute the SAPISIDHASH Authorization header value.

    Google requires this header on all notebooklm.google.com API requests.
    Without it, batchexecute returns HTTP 401.

    Algorithm (Google-standard, same across Maps/Docs/NLM):
      1. Extract SAPISID cookie value (fallback: __Secure-3PAPISID).
      2. Build raw string: "<unix_ts> <sapisid_value> <origin>"
      3. SHA-1 hash the raw string.
      4. Return "SAPISIDHASH <unix_ts>_<hex_digest>"

    The timestamp is included in both the raw string AND the header value so
    the server can verify freshness (tokens older than ~30 minutes are rejected).

    Args:
        cookies: Google auth cookies dict (must contain SAPISID or __Secure-3PAPISID).

    Returns:
        Authorization header value string, or "" if no SAPISID found.
    """
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID", "")
    if not sapisid:
        return ""
    ts = str(int(time.time()))
    raw = f"{ts} {sapisid} https://{_NLM_HOST}"
    digest = hashlib.sha1(raw.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"
