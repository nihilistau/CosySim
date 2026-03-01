"""NLM Chrome Auth Extractor — reads Google auth cookies from Node server's Chrome profile.

The @pan-sec/notebooklm-mcp Node server maintains a persistent Chrome profile at
C:\\Users\\Knack\\AppData\\Local\\notebooklm-mcp\\chrome_profile.

This module reads the Chrome Cookies SQLite database from that profile, decrypts
the cookie values (Windows DPAPI), and extracts the Google auth cookies needed
for our batchexecute proxy — eliminating the HAR token refresh requirement.

Usage:
    from engine.mcp.nlm_chrome_auth import get_cookies_from_chrome_profile
    cookies = get_cookies_from_chrome_profile()
    # Returns dict: {cookie_name: cookie_value, ...}
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Chrome profile path (set by Node server, Windows %LOCALAPPDATA%)
_CHROME_PROFILE = Path(
    os.environ.get("LOCALAPPDATA", r"C:\Users\Knack\AppData\Local")
) / "notebooklm-mcp" / "chrome_profile"

_COOKIES_DB = _CHROME_PROFILE / "Default" / "Cookies"
_LOCAL_STATE = _CHROME_PROFILE / "Local State"

# Google domains we care about for NLM auth
_GOOGLE_DOMAINS = {".google.com", "notebooklm.google.com", "accounts.google.com"}

# Cookies that NLM/Google auth needs
_AUTH_COOKIE_NAMES = frozenset({
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID",
    "__Secure-3PAPISID", "SAPISID", "APISID", "SID", "HSID",
    "SSID", "NID", "1P_JAR", "SOCS",
})


def _get_chrome_encryption_key() -> Optional[bytes]:
    """Read and decrypt the Chrome AES encryption key from Local State (Windows).

    Chrome on Windows encrypts cookie values with AES-256-GCM. The AES key
    is stored in Local State encrypted with Windows DPAPI.

    Returns:
        Raw 32-byte AES key, or None if unavailable.
    """
    if not _LOCAL_STATE.exists():
        logger.debug("Chrome Local State not found: %s", _LOCAL_STATE)
        return None
    try:
        with open(_LOCAL_STATE, "r", encoding="utf-8") as f:
            state = json.load(f)
        encrypted_key_b64 = state.get("os_crypt", {}).get("encrypted_key")
        if not encrypted_key_b64:
            return None
        import base64
        encrypted_key = base64.b64decode(encrypted_key_b64)
        # Remove DPAPI prefix "DPAPI"
        if encrypted_key[:5] == b"DPAPI":
            encrypted_key = encrypted_key[5:]
        import ctypes
        import ctypes.wintypes

        # Use Windows DPAPI to decrypt
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        p = ctypes.create_string_buffer(encrypted_key, len(encrypted_key))
        blob_in = DATA_BLOB(ctypes.sizeof(p), p)
        blob_out = DATA_BLOB()
        ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if blob_out.pbData:
            key = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return key
    except Exception as exc:
        logger.debug("Chrome key extraction failed: %s", exc)
    return None


def _decrypt_cookie_value(encrypted_value: bytes, key: Optional[bytes]) -> str:
    """Decrypt a Chrome cookie value.

    Chrome v80+ uses AES-256-GCM with a 96-bit nonce.
    Older Chrome uses DPAPI directly.

    Args:
        encrypted_value: Raw encrypted bytes from Cookies DB.
        key: AES key from Local State (may be None for legacy DPAPI cookies).

    Returns:
        Decrypted cookie value string, or empty string on failure.
    """
    if not encrypted_value:
        return ""

    # Chrome v80+ AES-GCM: prefix "v10" or "v11"
    if encrypted_value[:3] in (b"v10", b"v11") and key:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            nonce = encrypted_value[3:15]    # 12 bytes
            ciphertext = encrypted_value[15:]  # rest is ciphertext + 16-byte tag
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("AES-GCM decrypt failed: %s", exc)
            return ""

    # Legacy DPAPI encryption
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        p = ctypes.create_string_buffer(encrypted_value, len(encrypted_value))
        blob_in = DATA_BLOB(ctypes.sizeof(p), p)
        blob_out = DATA_BLOB()
        ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if blob_out.pbData:
            value = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return value.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("DPAPI decrypt failed: %s", exc)
    return ""


def get_cookies_from_chrome_profile(
    domains: Optional[set] = None,
    names: Optional[set] = None,
) -> Dict[str, str]:
    """Extract auth cookies from the Node server's Chrome profile.

    Reads Chrome's Cookies SQLite database (copying it first since Chrome
    keeps it locked), decrypts values, and returns the requested cookies.

    Args:
        domains: Set of domains to filter by. Defaults to Google auth domains.
        names: Set of cookie names to extract. Defaults to NLM auth cookies.

    Returns:
        Dict mapping cookie_name → cookie_value for all matching cookies.
    """
    if domains is None:
        domains = _GOOGLE_DOMAINS
    if names is None:
        names = _AUTH_COOKIE_NAMES

    if not _COOKIES_DB.exists():
        logger.warning("Chrome Cookies DB not found: %s", _COOKIES_DB)
        logger.warning("Run setup_auth() to authenticate the Chrome profile first")
        return {}

    # Copy DB to temp file (Chrome may have it locked)
    tmp_path = None
    cookies: Dict[str, str] = {}
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(_COOKIES_DB), tmp_path)

        aes_key = _get_chrome_encryption_key()
        if not aes_key:
            logger.warning("Could not extract Chrome AES key — cookies may not decrypt")

        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT name, host_key, encrypted_value, value FROM cookies"
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            name = row["name"]
            host = row["host_key"]
            # Filter by domain and name
            if not any(d in host for d in domains):
                continue
            if name not in names:
                continue
            # Try plaintext value first
            value = row["value"] or ""
            if not value and row["encrypted_value"]:
                value = _decrypt_cookie_value(bytes(row["encrypted_value"]), aes_key)
            if value:
                cookies[name] = value

        logger.info("Extracted %d auth cookies from Chrome profile", len(cookies))

    except Exception as exc:
        logger.error("Failed to read Chrome cookies: %s", exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return cookies


def update_proxy_cookies_from_chrome() -> bool:
    """Extract Chrome cookies and write them to the batchexecute proxy's cookie file.

    Replaces the need for manual HAR imports. Called automatically when the
    proxy detects auth failure.

    Returns:
        True if cookies were extracted and written successfully.
    """
    from engine.mcp.nlm_live_proxy import _DATA_DIR as PROXY_DATA_DIR  # type: ignore[attr-defined]

    cookies = get_cookies_from_chrome_profile()
    if not cookies:
        logger.error("No cookies extracted from Chrome — setup_auth first")
        return False

    cookie_file = PROXY_DATA_DIR / "nlm_cookies.json"
    # Convert to proxy format: list of {name, value, domain, path} dicts
    cookie_list = [
        {
            "name": name,
            "value": value,
            "domain": ".google.com",
            "path": "/",
        }
        for name, value in cookies.items()
    ]

    try:
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(cookie_list, f, indent=2)
        logger.info("Wrote %d cookies to proxy cookie file: %s", len(cookie_list), cookie_file)
        return True
    except Exception as exc:
        logger.error("Failed to write proxy cookie file: %s", exc)
        return False
