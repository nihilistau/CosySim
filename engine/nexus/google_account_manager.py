"""Google Account Manager — Multi-account cookie pool for Google services.

Manages cookies extracted from HAR files across multiple Google accounts.
Provides round-robin rotation with rate-limit backoff.
Supports NotebookLM (batchexecute) and AI Studio (gRPC-Web) services.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.integrations.google_service_profiles import (
    GOOGLE_COOKIE_NAMES,
    describe_google_services,
    normalize_google_service_name,
    normalize_google_services,
)
from engine.integrations.har_extractor import HARExtractor

logger = logging.getLogger(__name__)

# ──── Constants ────

_GOOGLE_AUTH_COOKIES = set(GOOGLE_COOKIE_NAMES)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "google_accounts"

# ──── Singleton ────

_MANAGER_INSTANCE: Optional[GoogleAccountManager] = None


def get_account_manager() -> "GoogleAccountManager":
    """Return the singleton GoogleAccountManager instance.

    Returns:
        The global GoogleAccountManager.
    """
    global _MANAGER_INSTANCE
    if _MANAGER_INSTANCE is None:
        _MANAGER_INSTANCE = GoogleAccountManager()
    return _MANAGER_INSTANCE


# ──── Manager Class ────

class GoogleAccountManager:
    """Manages a pool of Google accounts for cookie-based authentication.

    Stores account cookies extracted from HAR files and provides rotation
    with rate-limit awareness.

    Usage:
        manager = get_account_manager()
        manager.import_from_har("capture.har", "account1")
        account = manager.get_account()
        header = manager.get_sapisid_hash(account["account_id"], "https://aistudio.google.com")
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        """Initialise the manager.

        Args:
            data_dir: Optional override for the cookie storage directory.
        """
        self._data_dir: Path = data_dir or _DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ──── Storage Helpers ────

    def _account_path(self, account_id: str) -> Path:
        """Return the cookie JSON path for an account."""
        account_dir = self._data_dir / account_id
        account_dir.mkdir(parents=True, exist_ok=True)
        return account_dir / "cookies.json"

    def _load_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Load account data from disk.

        Args:
            account_id: The account identifier.

        Returns:
            Account dict or None if not found.
        """
        path = self._account_path(account_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load account %s: %s", account_id, exc)
            return None

    def _save_account(self, account_id: str, data: Dict[str, Any]) -> None:
        """Persist account data to disk.

        Args:
            account_id: The account identifier.
            data: Account dict to save.
        """
        path = self._account_path(account_id)
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save account %s: %s", account_id, exc)

    def _all_account_ids(self) -> List[str]:
        """Enumerate account IDs from the data directory.

        Returns:
            Sorted list of account IDs.
        """
        if not self._data_dir.exists():
            return []
        return sorted(
            p.name
            for p in self._data_dir.iterdir()
            if p.is_dir() and (p / "cookies.json").exists()
        )

    # ──── Cookie Parsing Helpers ────

    @staticmethod
    def _parse_cookie_header(header_value: str) -> Dict[str, str]:
        """Parse a Cookie HTTP header string into a name→value dict.

        Args:
            header_value: Raw cookie header string, semicolon-separated.

        Returns:
            Dict of cookie name to value.
        """
        cookies: Dict[str, str] = {}
        for part in header_value.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    # ──── Public API ────

    def import_from_har(
        self,
        har_path: str,
        account_id: str,
        service: str = "google",
    ) -> bool:
        """Import Google auth cookies from a HAR file.

        Finds entries to NotebookLM or AI Studio, extracts auth cookies and
        optional API key, then saves to ``data/google_accounts/{account_id}/``.

        Args:
            har_path: Path to the .har file.
            account_id: Identifier to assign to this account.
            service: Service label (e.g. "google", "aistudio").

        Returns:
            True on success, False on failure.
        """
        canonical_service = normalize_google_service_name(service)
        path = Path(har_path)
        if not path.exists():
            logger.error("HAR file not found: %s", har_path)
            return False

        try:
            har = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            logger.error("Failed to parse HAR file %s: %s", har_path, exc)
            return False

        extractor = HARExtractor(har_path)
        extracted = extractor.to_account_dict(account_id, [canonical_service])
        entries = har.get("log", {}).get("entries", [])
        cookies: Dict[str, str] = dict(extracted.get("cookies", {}))
        api_keys: Dict[str, str] = {}
        detected_services = normalize_google_services(
            extracted.get("detected_services") or [canonical_service]
        )
        services = normalize_google_services([canonical_service] + detected_services)
        service_sessions = {
            normalize_google_service_name(name): dict(session)
            for name, session in (extracted.get("service_sessions") or {}).items()
            if isinstance(session, dict) and session
        }

        for entry in entries:
            url: str = entry.get("request", {}).get("url", "")
            if not any(host in url for host in ("notebooklm.google.com", "alkalimakersuite-pa.clients6.google.com")):
                continue

            headers: List[Dict[str, str]] = entry.get("request", {}).get("headers", [])
            for header in headers:
                name_lower = header.get("name", "").lower()
                value = header.get("value", "")

                if header.get("name", "") == "X-Goog-Api-Key" and value:
                    api_keys["aistudio"] = value

        if not cookies:
            logger.warning("No auth cookies found in %s for account %s", har_path, account_id)
            return False

        data: Dict[str, Any] = {
            "account_id": account_id,
            "service": canonical_service,
            "services": services,
            "detected_services": detected_services,
            "cookies": cookies,
            "api_keys": api_keys,
            "at_token": extracted.get("at_token"),
            "nlm_session": extracted.get("nlm_session") or {},
            "service_sessions": service_sessions,
            "service_profiles": describe_google_services(services, service_sessions),
            "domains": extracted.get("domains", []),
            "imported_at": time.time(),
            "last_used": None,
            "rate_limited_until": None,
            "request_count": 0,
        }
        self._save_account(account_id, data)
        logger.info(
            "Imported account %s: %d cookies, api_keys=%s",
            account_id,
            len(cookies),
            list(api_keys.keys()),
        )
        return True

    def get_account(self, service: str = "google") -> Optional[Dict[str, Any]]:
        """Return the least-recently-used non-rate-limited account.

        Args:
            service: Filter by service label (currently informational).

        Returns:
            Account dict with cookies, or None if none available.
        """
        now = time.time()
        canonical_service = normalize_google_service_name(service)
        candidates: List[Dict[str, Any]] = []

        for account_id in self._all_account_ids():
            data = self._load_account(account_id)
            if data is None:
                continue
            available_services = normalize_google_services(
                data.get("services") or [data.get("service", "google")]
            )
            if canonical_service not in available_services and canonical_service != "google":
                continue
            rate_until = data.get("rate_limited_until")
            if rate_until and now < rate_until:
                continue
            candidates.append(data)

        if not candidates:
            return None

        # Least-recently-used: sort by last_used (None sorts first = oldest)
        candidates.sort(key=lambda d: d.get("last_used") or 0.0)
        chosen = candidates[0]

        # Update last_used
        chosen["last_used"] = now
        chosen["request_count"] = chosen.get("request_count", 0) + 1
        self._save_account(chosen["account_id"], chosen)
        return chosen

    def mark_rate_limited(
        self,
        account_id: str,
        backoff_seconds: int = 3600,
    ) -> None:
        """Mark an account as rate-limited for a backoff period.

        Args:
            account_id: The account to mark.
            backoff_seconds: Duration in seconds before the account is usable again.
        """
        data = self._load_account(account_id)
        if data is None:
            logger.warning("Cannot mark unknown account %s as rate-limited", account_id)
            return
        data["rate_limited_until"] = time.time() + backoff_seconds
        self._save_account(account_id, data)
        logger.info("Account %s rate-limited for %ds", account_id, backoff_seconds)

    def get_sapisid_hash(
        self,
        account_id: str,
        origin: str,
    ) -> Optional[str]:
        """Compute the SAPISIDHASH authorisation value for a request.

        The hash format is ``{timestamp}_{SHA1(timestamp + ' ' + SAPISID + ' ' + origin)}``.

        Args:
            account_id: Account whose SAPISID cookie to use.
            origin: The ``Origin`` header value (e.g. ``"https://aistudio.google.com"``).

        Returns:
            Formatted hash string, or None if account has no SAPISID.
        """
        data = self._load_account(account_id)
        if data is None:
            return None
        sapisid = data.get("cookies", {}).get("SAPISID")
        if not sapisid:
            return None
        timestamp = int(time.time())
        digest = hashlib.sha1(
            f"{timestamp} {sapisid} {origin}".encode("utf-8")
        ).hexdigest()
        return f"{timestamp}_{digest}"

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Return all accounts with their current status.

        Returns:
            List of account dicts, each augmented with ``is_rate_limited`` bool.
        """
        now = time.time()
        accounts: List[Dict[str, Any]] = []
        for account_id in self._all_account_ids():
            data = self._load_account(account_id)
            if data is None:
                continue
            rate_until = data.get("rate_limited_until")
            data["is_rate_limited"] = bool(rate_until and now < rate_until)
            accounts.append(data)
        return accounts

    def account_count(self) -> int:
        """Return total number of registered accounts.

        Returns:
            Account count.
        """
        return len(self._all_account_ids())

    def available_count(self, service: str = "google") -> int:
        """Return the number of accounts not currently rate-limited.

        Args:
            service: Filter label (currently informational).

        Returns:
            Count of available accounts.
        """
        now = time.time()
        canonical_service = normalize_google_service_name(service)
        count = 0
        for account_id in self._all_account_ids():
            data = self._load_account(account_id)
            if data is None:
                continue
            available_services = normalize_google_services(
                data.get("services") or [data.get("service", "google")]
            )
            if canonical_service not in available_services and canonical_service != "google":
                continue
            rate_until = data.get("rate_limited_until")
            if not rate_until or now >= rate_until:
                count += 1
        return count

    def import_all_from_directory(
        self,
        har_dir: str,
        service: str = "google",
    ) -> int:
        """Import all .har files from a directory.

        Derives account_id from each filename (without extension).

        Args:
            har_dir: Directory to scan for .har files.
            service: Service label to assign.

        Returns:
            Number of successfully imported accounts.
        """
        dir_path = Path(har_dir)
        if not dir_path.exists() or not dir_path.is_dir():
            logger.warning("HAR directory not found: %s", har_dir)
            return 0

        imported = 0
        for har_file in sorted(dir_path.glob("*.har")):
            account_id = har_file.stem
            if self.import_from_har(str(har_file), account_id, service):
                imported += 1

        logger.info("Imported %d accounts from %s", imported, har_dir)
        return imported
