"""Multi-account Google cookie pool with round-robin rotation.

Manages a pool of authenticated Google accounts for use across Colab,
NotebookLM, and AI Studio integrations. Persists state to disk.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from engine.integrations.har_extractor import HARExtractor, COOKIE_NAMES

logger = logging.getLogger(__name__)

_POOL_PATH = os.path.join("data", "accounts", "pool.json")


# ──── Data model ─────────────────────────────────────────────────────────────

class GoogleAccount(BaseModel):
    """A single authenticated Google account.

    Attributes:
        name: Human-readable identifier (e.g. "nihilistcod").
        cookies: Mapping of cookie name to value.
        authuser: x-goog-authuser index, usually 0.
        services: List of service keys this account is valid for.
        rate_limited: Mapping of service -> Unix timestamp when rate limit expires.
        added_at: Unix timestamp when account was added to the pool.
        at_token: XSRF at token, if extracted.
    """

    model_config = ConfigDict(validate_assignment=True)

    name: str
    cookies: Dict[str, str] = Field(default_factory=dict)
    authuser: int = 0
    services: List[str] = Field(default_factory=list)
    rate_limited: Dict[str, float] = Field(default_factory=dict)
    added_at: float = Field(default_factory=time.time)
    at_token: Optional[str] = None

    def is_rate_limited(self, service: str) -> bool:
        """Return True if this account is currently rate-limited for service."""
        expiry = self.rate_limited.get(service, 0.0)
        return time.time() < expiry

    def cookie_age_days(self) -> float:
        """Return how many days ago this account's cookies were captured."""
        return (time.time() - self.added_at) / 86400.0

    def is_stale(self, max_age_days: float = 7.0) -> bool:
        """Return True if cookies are older than max_age_days."""
        return self.cookie_age_days() > max_age_days

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoogleAccount":
        """Deserialize from dict."""
        return cls.model_validate(data)


# ──── Pool ────────────────────────────────────────────────────────────────────

class GoogleAccountPool:
    """Thread-safe pool of Google accounts with round-robin rotation.

    Persists the pool to ``data/accounts/pool.json``.
    """

    def __init__(self, pool_path: str = _POOL_PATH) -> None:
        self._path = pool_path
        self._accounts: Dict[str, GoogleAccount] = {}
        self._rotation_indices: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.load()

    # ──── Import / Management ─────────────────────────────────────────────────

    def import_from_har(
        self,
        har_path: str,
        account_name: str,
        services: Optional[List[str]] = None,
    ) -> GoogleAccount:
        """Import a Google account from a HAR file.

        Args:
            har_path: Path to the .har file.
            account_name: Human-readable name for this account.
            services: List of services this account should be used for.

        Returns:
            The created GoogleAccount.
        """
        if services is None:
            services = ["colab", "notebooklm"]

        extractor = HARExtractor(har_path)
        data = extractor.to_account_dict(account_name)
        cookies = data["cookies"]

        if not cookies:
            raise ValueError(
                f"No Google cookies found in HAR file: {har_path}"
            )

        account = GoogleAccount(
            name=account_name,
            cookies=cookies,
            authuser=data["authuser"],
            services=services,
            at_token=data.get("at_token"),
        )

        with self._lock:
            self._accounts[account_name] = account

        logger.info(
            "Imported account '%s' with %d cookies for services: %s",
            account_name,
            len(cookies),
            services,
        )
        return account

    def add_account(self, account: GoogleAccount) -> None:
        """Add a pre-constructed GoogleAccount to the pool."""
        with self._lock:
            self._accounts[account.name] = account

    def remove_account(self, account_name: str) -> None:
        """Remove an account from the pool."""
        with self._lock:
            self._accounts.pop(account_name, None)

    # ──── Rotation ────────────────────────────────────────────────────────────

    def get_account(self, service: str) -> Optional[GoogleAccount]:
        """Get the next available account for a service (round-robin).

        Skips accounts that are currently rate-limited for the service.

        Args:
            service: Service key (e.g. "colab", "notebooklm").

        Returns:
            A GoogleAccount, or None if no accounts are available.
        """
        with self._lock:
            eligible = [
                acct for acct in self._accounts.values()
                if service in acct.services and not acct.is_rate_limited(service)
            ]
            if not eligible:
                return None

            idx = self._rotation_indices.get(service, 0) % len(eligible)
            self._rotation_indices[service] = (idx + 1) % len(eligible)
            return eligible[idx]

    def mark_rate_limited(
        self,
        account_name: str,
        service: str,
        duration_seconds: int = 3600,
    ) -> None:
        """Mark an account as rate-limited for a service.

        Args:
            account_name: The account to mark.
            service: The service that is rate-limited.
            duration_seconds: How many seconds until the limit expires.
        """
        with self._lock:
            account = self._accounts.get(account_name)
            if account:
                account.rate_limited[service] = time.time() + duration_seconds
                logger.warning(
                    "Account '%s' rate-limited for '%s' for %ds",
                    account_name,
                    service,
                    duration_seconds,
                )

    def mark_available(self, account_name: str, service: str) -> None:
        """Clear the rate-limit on an account for a service.

        Args:
            account_name: The account to unblock.
            service: The service to unblock.
        """
        with self._lock:
            account = self._accounts.get(account_name)
            if account:
                account.rate_limited.pop(service, None)

    # ──── Cookie header helpers ────────────────────────────────────────────────

    def get_cookie_header(
        self,
        account: GoogleAccount,
        domain: str = "google.com",
    ) -> str:
        """Build a Cookie: header string from an account's cookies.

        Args:
            account: The account whose cookies to use.
            domain: Currently unused; reserved for domain filtering.

        Returns:
            A semicolon-separated Cookie header value string.
        """
        parts = [f"{k}={v}" for k, v in account.cookies.items() if v]
        return "; ".join(parts)

    # ──── Introspection ───────────────────────────────────────────────────────

    def list_accounts(self) -> List[Dict[str, Any]]:
        """List all accounts with summary info.

        Returns:
            List of dicts with: name, services, cookie_count, rate_limited.
        """
        with self._lock:
            result = []
            for acct in self._accounts.values():
                active_limits = {
                    svc: exp
                    for svc, exp in acct.rate_limited.items()
                    if time.time() < exp
                }
                result.append({
                    "name": acct.name,
                    "services": acct.services,
                    "cookie_count": len(acct.cookies),
                    "authuser": acct.authuser,
                    "rate_limited": active_limits,
                    "added_at": acct.added_at,
                })
            return result

    def get_by_name(self, name: str) -> Optional[GoogleAccount]:
        """Get a specific account by name."""
        with self._lock:
            return self._accounts.get(name)

    def get_stale_accounts(self, max_age_days: float = 7.0) -> List[Dict[str, Any]]:
        """Return accounts whose cookies are older than max_age_days.

        Args:
            max_age_days: Cookies older than this are considered stale.

        Returns:
            List of dicts with name, age_days, services.
        """
        with self._lock:
            return [
                {
                    "name": acct.name,
                    "age_days": round(acct.cookie_age_days(), 1),
                    "services": acct.services,
                    "added_at": acct.added_at,
                }
                for acct in self._accounts.values()
                if acct.is_stale(max_age_days)
            ]

    def get_available_accounts(
        self,
        service: str,
        exclude_stale: bool = False,
        max_age_days: float = 7.0,
    ) -> List[GoogleAccount]:
        """Return all accounts eligible for a service.

        Args:
            service: Service key to filter by.
            exclude_stale: If True, skip accounts with stale cookies.
            max_age_days: Age threshold for staleness check.

        Returns:
            List of eligible GoogleAccount instances.
        """
        with self._lock:
            return [
                acct for acct in self._accounts.values()
                if service in acct.services
                and not acct.is_rate_limited(service)
                and (not exclude_stale or not acct.is_stale(max_age_days))
            ]

    # ──── Persistence ─────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist the pool to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with self._lock:
            data = {name: acct.to_dict() for name, acct in self._accounts.items()}
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.debug("Saved account pool to %s (%d accounts)", self._path, len(data))

    def load(self) -> None:
        """Load the pool from disk, if it exists."""
        if not os.path.exists(self._path):
            logger.debug("No pool file at %s, starting empty", self._path)
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Support legacy format: {"accounts": [{name, cookies, ...}, ...]}
            if isinstance(data, dict) and "accounts" in data and isinstance(data["accounts"], list):
                data = {a["name"]: a for a in data["accounts"] if isinstance(a, dict) and "name" in a}
                # Migrate to new format on disk
                with open(self._path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                logger.info("Migrated pool.json from legacy list format → dict format")
            with self._lock:
                self._accounts = {
                    name: GoogleAccount.from_dict(acct_data)
                    for name, acct_data in data.items()
                }
            logger.debug("Loaded %d accounts from %s", len(self._accounts), self._path)
        except Exception as exc:
            logger.error("Failed to load account pool: %s", exc)


# ──── Singleton ───────────────────────────────────────────────────────────────

_pool_instance: Optional[GoogleAccountPool] = None
_pool_lock = threading.Lock()


def get_account_pool() -> GoogleAccountPool:
    """Get or create the singleton GoogleAccountPool."""
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = GoogleAccountPool()
    return _pool_instance
