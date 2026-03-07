"""Multi-account Google cookie pool with round-robin rotation.

Manages a pool of authenticated Google accounts for use across Colab,
NotebookLM, and AI Studio integrations. Persists state to disk.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from engine.integrations.har_extractor import HARExtractor
from engine.integrations.google_service_profiles import (
    describe_google_services,
    get_google_service_profile,
    normalize_google_service_name,
    normalize_google_services,
)

logger = logging.getLogger(__name__)

_POOL_PATH = os.path.join("data", "accounts", "pool.json")
def _normalize_service_name(service: str) -> str:
    """Normalize historical service aliases to canonical names."""
    return normalize_google_service_name(service)


def _normalize_services(services: List[str]) -> List[str]:
    """Normalize and de-duplicate service names while preserving order."""
    return normalize_google_services(services)


def _get_nlm_meta_path(pool_path: str) -> Path:
    """Return the NotebookLM metadata path associated with a pool file."""
    return _get_service_export_path(pool_path, "nlm_meta.json")


def _get_service_export_path(pool_path: str, filename: str) -> Path:
    """Return a service artifact path associated with a pool file."""
    resolved = Path(pool_path).resolve()
    if resolved.name == "pool.json" and resolved.parent.name == "accounts":
        return resolved.parent.parent / filename
    return resolved.parent / filename


def _persist_nlm_meta(meta_path: Path, session: Dict[str, str]) -> None:
    """Persist NotebookLM session metadata for the live proxy and tooling."""
    if not session:
        return

    existing: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("Could not read existing NLM metadata from %s", meta_path, exc_info=True)

    updated = dict(existing)
    if session.get("bl"):
        updated["bl"] = session["bl"]
        updated["bl_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if session.get("f_sid"):
        updated["f_sid"] = session["f_sid"]
    if session.get("at"):
        updated["at"] = session["at"]

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(updated, indent=2), encoding="utf-8")


def _persist_service_cookies(
    export_path: Path,
    cookies: Dict[str, str],
    cookie_names: List[str] | tuple[str, ...],
) -> None:
    """Persist a service-specific cookie export file."""
    filtered = {
        key: value
        for key, value in cookies.items()
        if key in set(cookie_names) and value
    }
    if not filtered:
        return

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")


def _persist_service_artifacts(pool_path: str, account: "GoogleAccount") -> None:
    """Persist any known service-specific runtime artifacts for an account."""
    for service in account.services:
        profile = get_google_service_profile(service)
        if profile.cookie_export_filename:
            _persist_service_cookies(
                _get_service_export_path(pool_path, profile.cookie_export_filename),
                account.cookies,
                profile.cookie_names,
            )

        if (
            profile.name == "notebooklm"
            and profile.session_meta_filename
            and account.nlm_session
        ):
            _persist_nlm_meta(
                _get_service_export_path(pool_path, profile.session_meta_filename),
                account.nlm_session,
            )


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
        nlm_session: NotebookLM-specific session metadata extracted from HAR.
    """

    model_config = ConfigDict(validate_assignment=True)

    name: str
    cookies: Dict[str, str] = Field(default_factory=dict)
    authuser: int = 0
    services: List[str] = Field(default_factory=list)
    rate_limited: Dict[str, float] = Field(default_factory=dict)
    added_at: float = Field(default_factory=time.time)
    at_token: Optional[str] = None
    nlm_session: Dict[str, str] = Field(default_factory=dict)
    service_sessions: Dict[str, Dict[str, str]] = Field(default_factory=dict)

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
        services: Optional[List[str] | str] = None,
    ) -> GoogleAccount:
        """Import a Google account from a HAR file.

        Args:
            har_path: Path to the .har file.
            account_name: Human-readable name for this account.
            services: List of services this account should be used for.

        Returns:
            The created GoogleAccount.
        """
        extractor = HARExtractor(har_path)
        detected_services = extractor.detect_services()
        if services is None:
            requested_services = detected_services or ["colab", "notebooklm"]
        elif isinstance(services, str):
            requested_services = [services]
        else:
            requested_services = list(services)
        normalized_services = _normalize_services(requested_services)

        data = extractor.to_account_dict(account_name, normalized_services or detected_services)
        cookies = data["cookies"]
        detected_services = _normalize_services(data.get("detected_services") or detected_services)
        service_sessions = {
            _normalize_service_name(service): dict(session)
            for service, session in (data.get("service_sessions") or {}).items()
            if isinstance(session, dict) and session
        }
        nlm_session = service_sessions.get("notebooklm") or data.get("nlm_session") or {}

        if not cookies:
            raise ValueError(
                f"No Google cookies found in HAR file: {har_path}"
            )

        with self._lock:
            existing = self._accounts.get(account_name)
            merged_services = _normalize_services(
                (existing.services if existing else []) + normalized_services + detected_services
            )
            merged_service_sessions = dict(existing.service_sessions) if existing else {}
            for service_name, session in service_sessions.items():
                merged_session = dict(merged_service_sessions.get(service_name, {}))
                for key, value in session.items():
                    if value:
                        merged_session[key] = value
                if merged_session:
                    merged_service_sessions[service_name] = merged_session

            merged_nlm_session = dict(existing.nlm_session) if existing else {}
            for key, value in (merged_service_sessions.get("notebooklm") or nlm_session).items():
                if value:
                    merged_nlm_session[key] = value

            account = GoogleAccount(
                name=account_name,
                cookies=cookies,
                authuser=data["authuser"],
                services=merged_services,
                rate_limited=dict(existing.rate_limited) if existing else {},
                added_at=time.time(),
                at_token=merged_nlm_session.get("at") or data.get("at_token") or (
                    existing.at_token if existing else None
                ),
                nlm_session=merged_nlm_session,
                service_sessions=merged_service_sessions,
            )
            self._accounts[account_name] = account

        _persist_service_artifacts(self._path, account)

        logger.info(
            "Imported account '%s' with %d cookies for services: %s",
            account_name,
            len(cookies),
            account.services,
        )
        return account

    def add_account(self, account: GoogleAccount) -> None:
        """Add a pre-constructed GoogleAccount to the pool."""
        account.services = _normalize_services(account.services)
        account.rate_limited = {
            _normalize_service_name(service): expiry
            for service, expiry in account.rate_limited.items()
        }
        account.service_sessions = {
            _normalize_service_name(service): dict(session)
            for service, session in account.service_sessions.items()
            if isinstance(session, dict) and session
        }
        if not account.nlm_session and account.service_sessions.get("notebooklm"):
            account.nlm_session = dict(account.service_sessions["notebooklm"])
        with self._lock:
            self._accounts[account.name] = account
        _persist_service_artifacts(self._path, account)

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
        canonical_service = _normalize_service_name(service)
        with self._lock:
            eligible = [
                acct for acct in self._accounts.values()
                if canonical_service in acct.services and not acct.is_rate_limited(canonical_service)
            ]
            if not eligible:
                return None

            idx = self._rotation_indices.get(canonical_service, 0) % len(eligible)
            self._rotation_indices[canonical_service] = (idx + 1) % len(eligible)
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
        canonical_service = _normalize_service_name(service)
        with self._lock:
            account = self._accounts.get(account_name)
            if account:
                account.rate_limited[canonical_service] = time.time() + duration_seconds
                logger.warning(
                    "Account '%s' rate-limited for '%s' for %ds",
                    account_name,
                    canonical_service,
                    duration_seconds,
                )

    def mark_available(self, account_name: str, service: str) -> None:
        """Clear the rate-limit on an account for a service.

        Args:
            account_name: The account to unblock.
            service: The service to unblock.
        """
        canonical_service = _normalize_service_name(service)
        with self._lock:
            account = self._accounts.get(account_name)
            if account:
                account.rate_limited.pop(canonical_service, None)

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
                    "detected_services": sorted(set(acct.services) | set(acct.service_sessions.keys())),
                    "cookie_count": len(acct.cookies),
                    "authuser": acct.authuser,
                    "rate_limited": active_limits,
                    "added_at": acct.added_at,
                    "has_at_token": bool(acct.at_token),
                    "has_nlm_session": bool(acct.nlm_session),
                    "has_service_sessions": bool(acct.service_sessions),
                    "service_profiles": describe_google_services(acct.services, acct.service_sessions),
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
        canonical_service = _normalize_service_name(service)
        with self._lock:
            return [
                acct for acct in self._accounts.values()
                if canonical_service in acct.services
                and not acct.is_rate_limited(canonical_service)
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
                self._accounts = {}
                for name, acct_data in data.items():
                    account = GoogleAccount.from_dict(acct_data)
                    account.services = _normalize_services(account.services)
                    account.rate_limited = {
                        _normalize_service_name(service): expiry
                        for service, expiry in account.rate_limited.items()
                    }
                    account.service_sessions = {
                        _normalize_service_name(service): dict(session)
                        for service, session in account.service_sessions.items()
                        if isinstance(session, dict) and session
                    }
                    if not account.nlm_session and account.service_sessions.get("notebooklm"):
                        account.nlm_session = dict(account.service_sessions["notebooklm"])
                    self._accounts[name] = account
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
