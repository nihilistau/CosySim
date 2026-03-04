"""Chrome DPAPI Cookie Extractor.

Decrypts Chrome's AES-GCM encrypted cookies from the on-disk SQLite database
using the DPAPI master key stored in Chrome's Local State file.

Targets: google.com, notebooklm.google.com, colab.research.google.com, github.com

Outputs to: data/accounts/chrome_cookies_<timestamp>.json
Optionally: updates google_account_pool.json with fresh cookies

Usage:
    python scripts/chrome_cookie_extractor.py
    python scripts/chrome_cookie_extractor.py --domains notebooklm colab
    python scripts/chrome_cookie_extractor.py --update-pool nihilistcod
    python scripts/chrome_cookie_extractor.py --profile "Profile 1"
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ──── DPAPI + AES deps ────
try:
    import win32crypt
    HAS_DPAPI = True
except ImportError:
    HAS_DPAPI = False
    print("[WARN] win32crypt not available — DPAPI decryption disabled", file=sys.stderr)

try:
    from Crypto.Cipher import AES
    HAS_AES = True
except ImportError:
    HAS_AES = False
    print("[WARN] PyCryptodome not available — AES-GCM decryption disabled", file=sys.stderr)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ──── Paths ────
CHROME_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
DEFAULT_PROFILE = "Default"
LOCAL_STATE_FILE = CHROME_USER_DATA / "Local State"

# Domains to target — covers every relevant Google/GitHub service
TARGET_DOMAINS = {
    "google",
    "notebooklm",
    "colab",
    "github",
    "googleapis",
    "gstatic",
    "googleusercontent",
    "accounts.google",
}

# Chrome AES-GCM constants
DPAPI_PREFIX = b"DPAPI"
AES_KEY_PREFIX = b"v10"
NONCE_SIZE = 12
TAG_SIZE = 16

OUT_DIR = Path("data/accounts")


def _copy_locked_file(src: str, dst: str) -> None:
    """Copy a file even if it's locked by another process (Chrome's SQLite WAL).

    Uses Windows CreateFile with FILE_SHARE_READ|WRITE|DELETE sharing flags,
    then reads in chunks and writes to the destination.
    Falls back to shutil.copy2 on non-Windows or if ctypes fails.
    """
    import ctypes
    import ctypes.wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    try:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = k32.CreateFileW(
            src,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise OSError(f"CreateFileW failed for {src} (error {k32.GetLastError()})")
        try:
            chunk = 1024 * 1024  # 1 MB
            buf = ctypes.create_string_buffer(chunk)
            read = ctypes.wintypes.DWORD(0)
            with open(dst, "wb") as out:
                while True:
                    ok = k32.ReadFile(handle, buf, chunk, ctypes.byref(read), None)
                    if not ok or read.value == 0:
                        break
                    out.write(buf.raw[: read.value])
        finally:
            k32.CloseHandle(handle)
    except Exception:
        # Fallback — may fail if Chrome is running, but worth trying
        shutil.copy2(src, dst)


def get_chrome_profiles(user_data: Path = CHROME_USER_DATA) -> List[str]:
    """Return list of Chrome profile directory names."""
    profiles = []
    if (user_data / "Default").is_dir():
        profiles.append("Default")
    for d in user_data.iterdir():
        if d.is_dir() and d.name.startswith("Profile "):
            profiles.append(d.name)
    return profiles


def decrypt_master_key(local_state_path: Path = LOCAL_STATE_FILE) -> Optional[bytes]:
    """Read Chrome's encrypted master key from Local State and decrypt with DPAPI."""
    if not HAS_DPAPI:
        logger.error("win32crypt unavailable — cannot decrypt master key")
        return None
    if not local_state_path.exists():
        logger.error("Local State not found: %s", local_state_path)
        return None

    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)

    # Encrypted key is base64 in os_crypt.encrypted_key
    encrypted_key_b64 = local_state.get("os_crypt", {}).get("encrypted_key", "")
    if not encrypted_key_b64:
        logger.error("No encrypted_key found in Local State")
        return None

    encrypted_key = base64.b64decode(encrypted_key_b64)

    # Strip "DPAPI" prefix (first 5 bytes)
    if encrypted_key[:5] == DPAPI_PREFIX:
        encrypted_key = encrypted_key[5:]
    else:
        logger.warning("Expected DPAPI prefix not found")

    # Decrypt with DPAPI (uses current user's credentials)
    try:
        master_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
        logger.info("Master key decrypted successfully (%d bytes)", len(master_key))
        return master_key
    except Exception as e:
        logger.error("DPAPI decryption failed: %s", e)
        return None


def _decrypt_app_bound_key(local_state_path: Path = LOCAL_STATE_FILE) -> Optional[bytes]:
    """Decrypt the Chrome v127+ app-bound encryption key via the elevation service COM.

    Chrome 127+ stores cookies encrypted with a key that is itself encrypted by the
    Chrome Elevation Service (SYSTEM-level DPAPI) rather than user DPAPI.
    We call the elevation service COM interface `IElevator::DecryptData` to retrieve it.
    Returns the raw 32-byte AES key, or None if unavailable.
    """
    if not local_state_path.exists():
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            ls = json.load(f)
        app_bound_key_b64 = ls.get("os_crypt", {}).get("app_bound_encrypted_key", "")
        if not app_bound_key_b64:
            return None
        encrypted_key = base64.b64decode(app_bound_key_b64)
        # Strip "APPB" prefix (4 bytes)
        if encrypted_key[:4] == b"APPB":
            encrypted_key = encrypted_key[4:]
    except Exception:
        return None

    # Try calling Chrome Elevation Service COM interface
    try:
        import comtypes
        import comtypes.client
        # Chrome's elevation service CLSID (changes per Chrome channel)
        # Stable: {708860E0-F641-4611-8895-7D867DD3675B}
        CLSID_CHROME_ELEVATOR = "{708860E0-F641-4611-8895-7D867DD3675B}"
        IID_IELEVATOR = "{A949CB4E-C4F9-44C4-B213-6BF8AA9AC69C}"
        elevator = comtypes.client.CreateObject(CLSID_CHROME_ELEVATOR)
        # IElevator::DecryptData(ciphertext) -> decrypted
        decrypted = elevator.DecryptData(encrypted_key)
        if decrypted and len(decrypted) >= 32:
            # Strip the inner DPAPI layer if present
            if decrypted[:5] == DPAPI_PREFIX and HAS_DPAPI:
                decrypted = win32crypt.CryptUnprotectData(decrypted[5:], None, None, None, 0)[1]
            return bytes(decrypted[-32:])  # last 32 bytes = AES key
    except Exception as e:
        logger.debug("COM elevation service unavailable: %s", e)

    # Fallback: try user DPAPI directly (works if elevation service saved with user key)
    if HAS_DPAPI:
        try:
            result = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
            if result and len(result) >= 32:
                return bytes(result[-32:])
        except Exception:
            pass

    return None


def decrypt_cookie_value(encrypted_value: bytes, master_key: bytes) -> Optional[str]:
    """Decrypt a single Chrome cookie value using AES-GCM.

    Handles both v10 (Chrome <127) and v20 (Chrome 127+ app-bound encryption) formats.
    """
    if not encrypted_value:
        return ""
    if not HAS_AES:
        return None

    try:
        prefix = encrypted_value[:3]
        # v10/v20: AES-GCM encrypted
        if prefix in (b"v10", b"v20"):
            nonce = encrypted_value[3:3 + NONCE_SIZE]
            ciphertext_tag = encrypted_value[3 + NONCE_SIZE:]
            ciphertext = ciphertext_tag[:-TAG_SIZE]
            tag = ciphertext_tag[-TAG_SIZE:]

            cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
            decrypted = cipher.decrypt_and_verify(ciphertext, tag)
            return decrypted.decode("utf-8", errors="replace")

        # Legacy DPAPI-encrypted cookie (older Chrome versions)
        elif HAS_DPAPI:
            decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
            return decrypted.decode("utf-8", errors="replace")

        return None

    except Exception:
        return None


def _domain_matches_targets(host_key: str, domains: Optional[List[str]]) -> bool:
    """Return True if host_key matches any of the target domains."""
    targets = domains or list(TARGET_DOMAINS)
    host_lower = host_key.lower().lstrip(".")
    return any(t in host_lower for t in targets)


def extract_cookies(
    profile: str = DEFAULT_PROFILE,
    master_key: Optional[bytes] = None,
    domains: Optional[List[str]] = None,
    include_all: bool = False,
) -> List[Dict[str, Any]]:
    """Extract and decrypt cookies from a Chrome profile.

    Args:
        profile: Chrome profile directory name (e.g. "Default", "Profile 1").
        master_key: Pre-decrypted master key. If None, auto-decrypts.
        domains: Filter domains. If None, uses TARGET_DOMAINS.
        include_all: If True, include all domains (ignore filter).

    Returns:
        List of cookie dicts with name, value, domain, path, expires, secure, httponly.
    """
    if master_key is None:
        master_key = decrypt_master_key()
    if master_key is None:
        logger.error("Cannot decrypt without master key")
        return []

    # Also attempt app-bound key (Chrome 127+ v20 cookies)
    app_bound_key = _decrypt_app_bound_key()

    cookie_db = CHROME_USER_DATA / profile / "Network" / "Cookies"
    if not cookie_db.exists():
        # Older Chrome layout
        cookie_db = CHROME_USER_DATA / profile / "Cookies"
    if not cookie_db.exists():
        logger.error("Cookie DB not found: %s", cookie_db)
        return []

    logger.info("Reading cookies from: %s", cookie_db)

    # Strategy 1: connect via SQLite immutable URI (works with WAL, no file copy needed)
    # Strategy 2: copy with Windows sharing flags + connect to copy
    # Strategy 3: copy with regular shutil (Chrome not running)
    cookies: List[Dict[str, Any]] = []
    rows = []

    def _read_db(path: str) -> list:
        """Read Chrome cookies DB safely, handling binary encrypted_value column."""
        # Convert Windows backslashes; encode spaces for SQLite URI
        path_uri = path.replace("\\", "/").replace(" ", "%20")
        if len(path_uri) > 1 and path_uri[1] == ":":
            path_uri = "/" + path_uri  # /C:/...

        def _connect(uri_or_path: str, is_uri: bool = False) -> Optional[sqlite3.Connection]:
            try:
                conn = sqlite3.connect(uri_or_path, uri=is_uri)
                # CRITICAL: return bytes for text fields to handle binary BLOB columns
                # (Python 3.13 raises on binary data decoded as UTF-8)
                conn.text_factory = lambda b: b  # type: ignore[assignment]
                return conn
            except Exception:
                return None

        conn = None
        for params in ["mode=ro&nolock=1", "mode=ro", "immutable=1"]:
            conn = _connect(f"file://{path_uri}?{params}", is_uri=True)
            if conn:
                break
        if conn is None:
            conn = _connect(path)
        if conn is None:
            raise OSError(f"Cannot open {path}")

        try:
            # Read text fields first (now returned as bytes by text_factory)
            meta_cur = conn.cursor()
            meta_cur.execute(
                "SELECT rowid, host_key, name, path, "
                "expires_utc, is_secure, is_httponly, creation_utc, last_access_utc "
                "FROM cookies ORDER BY host_key, name"
            )
            meta_rows = meta_cur.fetchall()

            # Read BLOB field separately using blob-safe approach
            blob_cur = conn.cursor()
            blob_cur.execute("SELECT rowid, encrypted_value FROM cookies")
            blob_map = {r[0]: r[1] for r in blob_cur.fetchall()}
        finally:
            conn.close()

        result = []
        for row in meta_rows:
            rowid = row[0]
            ev_raw = blob_map.get(rowid, b"")
            # Decode text fields (bytes due to text_factory)
            def _d(v: Any) -> str:
                if isinstance(v, (bytes, bytearray)):
                    return v.decode("utf-8", errors="replace")
                return str(v) if v is not None else ""
            result.append((
                _d(row[1]),  # host_key
                _d(row[2]),  # name
                bytes(ev_raw) if ev_raw else b"",  # encrypted_value (bytes)
                _d(row[3]),  # path
                row[4],      # expires_utc
                row[5],      # is_secure
                row[6],      # is_httponly
                row[7],      # creation_utc
                row[8],      # last_access_utc
            ))
        return result

    try:
        rows = _read_db(str(cookie_db))
        logger.info("Direct immutable read: %d rows", len(rows))
    except Exception as direct_err:
        logger.debug("Direct read failed (%s), trying copy...", direct_err)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            _copy_locked_file(str(cookie_db), tmp_path)
            # Also copy WAL file if present (Chrome WAL mode)
            wal_src = str(cookie_db) + "-wal"
            wal_dst = tmp_path + "-wal"
            shm_src = str(cookie_db) + "-shm"
            shm_dst = tmp_path + "-shm"
            if Path(wal_src).exists():
                _copy_locked_file(wal_src, wal_dst)
            if Path(shm_src).exists():
                _copy_locked_file(shm_src, shm_dst)
            rows = _read_db(tmp_path)
            logger.info("Copy read: %d rows", len(rows))
        except Exception as copy_err:
            logger.error("All read strategies failed: %s / %s", direct_err, copy_err)
            return []
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    logger.info("Total raw cookies: %d", len(rows))

    for row in rows:
        # Rows are plain tuples: (host_key, name, encrypted_value, path,
        #   expires_utc, is_secure, is_httponly, creation_utc, last_access_utc)
        host_key = row[0] or ""
        name = row[1]
        encrypted_value = row[2]
        path_val = row[3]
        expires_utc = row[4]
        is_secure = row[5]
        is_httponly = row[6]
        creation_utc = row[7]
        last_access_utc = row[8]

        if not include_all and not _domain_matches_targets(host_key, domains):
            continue

        ev_bytes = bytes(encrypted_value) if encrypted_value else b""
        value = decrypt_cookie_value(ev_bytes, master_key)
        # Try app-bound key for v20 cookies if v10 key failed
        if value is None and app_bound_key is not None:
            value = decrypt_cookie_value(ev_bytes, app_bound_key)
        if value is None:
            value = "[DECRYPTION_FAILED]"

        cookies.append({
            "domain": host_key,
            "name": name,
            "value": value,
            "path": path_val,
            "expires_utc": expires_utc,
            "secure": bool(is_secure),
            "httponly": bool(is_httponly),
            "creation_utc": creation_utc,
            "last_access_utc": last_access_utc,
        })

    logger.info("Matched %d cookies after domain filter", len(cookies))
    return cookies


def cookies_to_jar(cookies: List[Dict[str, Any]]) -> Dict[str, str]:
    """Convert cookie list to a flat name→value dict (for HTTP requests)."""
    return {c["name"]: c["value"] for c in cookies if c["value"] != "[DECRYPTION_FAILED]"}


def cookies_to_header_string(cookies: List[Dict[str, Any]], domain_filter: Optional[str] = None) -> str:
    """Convert to Cookie: header string for a specific domain."""
    filtered = cookies
    if domain_filter:
        filtered = [c for c in cookies if domain_filter in c["domain"]]
    parts = [f"{c['name']}={c['value']}" for c in filtered if c["value"] not in ("", "[DECRYPTION_FAILED]")]
    return "; ".join(parts)


def update_account_pool(
    cookies: List[Dict[str, Any]],
    account_name: str,
    pool_path: Path = Path("data/accounts/pool.json"),
) -> bool:
    """Update google_account_pool with fresh cookies for an account.

    Args:
        cookies: Decrypted cookie list.
        account_name: Pool account key (e.g. "nihilistcod").
        pool_path: Path to pool JSON file.

    Returns:
        True on success.
    """
    if not pool_path.exists():
        logger.error("Pool file not found: %s", pool_path)
        return False

    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)

    if account_name not in pool:
        logger.warning("Account '%s' not in pool — creating new entry", account_name)
        pool[account_name] = {"name": account_name, "cookies": {}}

    # Organize by domain
    domain_cookies: Dict[str, List[Dict]] = {}
    for c in cookies:
        d = c["domain"].lstrip(".").lower()
        domain_cookies.setdefault(d, []).append({"name": c["name"], "value": c["value"]})

    # Map to service keys used by pool
    service_map = {
        "notebooklm": ["notebooklm.google.com"],
        "colab": ["colab.research.google.com"],
        "google": ["google.com", "accounts.google.com"],
        "github": ["github.com"],
    }

    pool[account_name]["cookies"] = {}
    pool[account_name]["last_refreshed"] = datetime.now(timezone.utc).isoformat()

    for service, domains in service_map.items():
        service_cookies = []
        for d in domains:
            for host, clist in domain_cookies.items():
                if d in host or host in d:
                    service_cookies.extend(clist)
        if service_cookies:
            pool[account_name]["cookies"][service] = service_cookies

    with open(pool_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=2)

    logger.info("Updated pool '%s' with %d service cookie sets", account_name, len(pool[account_name]["cookies"]))
    return True


def save_report(
    cookies: List[Dict[str, Any]],
    output_dir: Path = OUT_DIR,
    include_values: bool = True,
) -> Path:
    """Save cookies to JSON report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"chrome_cookies_{ts}.json"

    report = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "total": len(cookies),
        "by_domain": {},
    }

    # Group by domain
    for c in cookies:
        domain = c["domain"]
        report["by_domain"].setdefault(domain, [])
        entry = {"name": c["name"], "secure": c["secure"], "httponly": c["httponly"]}
        if include_values:
            entry["value"] = c["value"]
        report["by_domain"][domain].append(entry)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info("Report saved: %s", out_path)
    return out_path


def print_summary(cookies: List[Dict[str, Any]]) -> None:
    """Print a human-readable summary to stdout."""
    by_domain: Dict[str, List] = {}
    for c in cookies:
        by_domain.setdefault(c["domain"], []).append(c)

    print(f"\n{'═' * 60}")
    print(f"  Chrome Cookie Extraction — {len(cookies)} cookies across {len(by_domain)} domains")
    print(f"{'═' * 60}")

    # High-value cookies to highlight
    high_value_names = {
        "SAPISID", "APISID", "SID", "HSID", "SSID", "__Secure-1PSID",
        "__Secure-3PSID", "NID", "user_session", "dotcom_user",
        "logged_in", "CONSENT", "GAPS",
    }

    for domain in sorted(by_domain.keys()):
        clist = by_domain[domain]
        high = [c for c in clist if c["name"] in high_value_names]
        marker = " ★" if high else ""
        print(f"\n  {domain} ({len(clist)} cookies){marker}")
        for c in clist:
            val_preview = (c["value"] or "")[:40]
            if len(c["value"] or "") > 40:
                val_preview += "…"
            flag = "★ " if c["name"] in high_value_names else "  "
            print(f"    {flag}{c['name']}: {val_preview}")

    # Print cookie header strings for each key domain
    print(f"\n{'─' * 60}")
    print("  Cookie headers for direct API use:")
    for domain_fragment in ["notebooklm", "colab", "github"]:
        header = cookies_to_header_string(cookies, domain_fragment)
        if header:
            preview = header[:80] + "…" if len(header) > 80 else header
            print(f"\n  [{domain_fragment}] Cookie: {preview}")
    print(f"{'═' * 60}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Decrypt Chrome cookies and optionally update the account pool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Chrome profile directory (default: Default)")
    parser.add_argument("--all-profiles", action="store_true", help="Extract from all detected Chrome profiles")
    parser.add_argument("--domains", nargs="*", help="Domain filters (e.g. notebooklm colab github)")
    parser.add_argument("--all-domains", action="store_true", help="Include all domains (no filter)")
    parser.add_argument("--update-pool", metavar="ACCOUNT", help="Update account pool with this account name")
    parser.add_argument("--no-save", action="store_true", help="Don't save report JSON")
    parser.add_argument("--no-values", action="store_true", help="Exclude values from saved report")
    parser.add_argument("--list-profiles", action="store_true", help="List available Chrome profiles and exit")
    args = parser.parse_args()

    if args.list_profiles:
        profiles = get_chrome_profiles()
        print("Chrome profiles found:")
        for p in profiles:
            print(f"  {p}")
        return

    # Decrypt master key once
    master_key = decrypt_master_key()
    if not master_key:
        logger.error("Failed to decrypt master key — aborting")
        sys.exit(1)

    profiles = get_chrome_profiles() if args.all_profiles else [args.profile]
    all_cookies: List[Dict[str, Any]] = []

    for profile in profiles:
        logger.info("Processing profile: %s", profile)
        cookies = extract_cookies(
            profile=profile,
            master_key=master_key,
            domains=args.domains,
            include_all=args.all_domains,
        )
        all_cookies.extend(cookies)

    if not all_cookies:
        logger.warning("No cookies extracted")
        return

    print_summary(all_cookies)

    if not args.no_save:
        report_path = save_report(all_cookies, include_values=not args.no_values)
        print(f"  Report saved to: {report_path}")

    if args.update_pool:
        success = update_account_pool(all_cookies, args.update_pool)
        if success:
            print(f"  Account pool updated for: {args.update_pool}")
        else:
            print(f"  Failed to update pool for: {args.update_pool}")


if __name__ == "__main__":
    main()
