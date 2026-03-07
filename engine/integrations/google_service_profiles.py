"""Google service profile registry for HAR and cookie tooling.

Provides a single extensible place to describe Google properties, their
aliases, host patterns, supported protocols, and any service-specific session
metadata extractors. The goal is to let the auth/import stack grow from a
NotebookLM-specific path into a reusable Google service surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Canonical Google account cookies reused across most first-party properties.
GOOGLE_COOKIE_NAMES: Tuple[str, ...] = (
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "OSID",
    "__Secure-OSID",
    "__Secure-BUCKET",
    "SIDCC",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
    "__Secure-1PSIDTS",
    "__Secure-1PSIDRTS",
    "__Secure-3PSIDTS",
    "__Secure-3PSIDRTS",
    "AEC",
    "NID",
    "LSID",
    "CONSENT",
    "SEARCH_SAMESITE",
)


@dataclass(frozen=True)
class GoogleServiceProfile:
    """Describes one Google service surface handled by the auth stack."""

    name: str
    aliases: Tuple[str, ...] = ()
    hosts: Tuple[str, ...] = ()
    protocols: Tuple[str, ...] = ()
    cookie_names: Tuple[str, ...] = GOOGLE_COOKIE_NAMES
    session_extractor: Optional[str] = None
    nexus_category: str = "google-services"
    cookie_export_filename: Optional[str] = None
    session_meta_filename: Optional[str] = None

    def matches_url(self, url: str) -> bool:
        """Return True when this profile applies to a request URL."""
        return any(host in url for host in self.hosts)

    def extract_session(self, extractor: Any) -> Dict[str, str]:
        """Extract service-specific session metadata through the HAR extractor."""
        if not self.session_extractor:
            return {}
        handler = getattr(extractor, self.session_extractor, None)
        if not callable(handler):
            return {}
        session = handler()
        return session if isinstance(session, dict) else {}


_PROFILE_LIST: Tuple[GoogleServiceProfile, ...] = (
    GoogleServiceProfile(
        name="notebooklm",
        aliases=("nlm", "notebook-lm"),
        hosts=("notebooklm.google.com",),
        protocols=("batchexecute", "html"),
        session_extractor="extract_nlm_session_metadata",
        nexus_category="notebooklm",
        cookie_export_filename="nlm_cookies.json",
        session_meta_filename="nlm_meta.json",
    ),
    GoogleServiceProfile(
        name="colab",
        hosts=("colab.research.google.com",),
        protocols=("rpc", "html"),
        nexus_category="colab",
    ),
    GoogleServiceProfile(
        name="aistudio",
        aliases=("ai_studio", "gemini"),
        hosts=("aistudio.google.com", "alkalimakersuite-pa.clients6.google.com"),
        protocols=("grpc-web", "html"),
        nexus_category="aistudio",
    ),
    GoogleServiceProfile(
        name="drive",
        aliases=("google-drive", "google_drive"),
        hosts=("drive.google.com",),
        protocols=("html", "rpc"),
        nexus_category="drive",
    ),
    GoogleServiceProfile(
        name="sheets",
        aliases=("google-sheets", "google_sheets", "googlesheets"),
        hosts=("docs.google.com/spreadsheets",),
        protocols=("html", "rpc"),
        nexus_category="sheets",
    ),
    GoogleServiceProfile(
        name="docs",
        hosts=("docs.google.com/document",),
        protocols=("html", "rpc"),
        nexus_category="docs",
    ),
    GoogleServiceProfile(
        name="gmail",
        hosts=("mail.google.com",),
        protocols=("html", "rpc"),
        nexus_category="gmail",
    ),
    GoogleServiceProfile(
        name="calendar",
        hosts=("calendar.google.com",),
        protocols=("html", "rpc"),
        nexus_category="calendar",
    ),
    GoogleServiceProfile(
        name="gas",
        aliases=("apps-script", "apps_script"),
        hosts=("script.google.com", "script.googleusercontent.com"),
        protocols=("batchexecute", "html"),
        nexus_category="gas",
    ),
    GoogleServiceProfile(
        name="google",
        hosts=("accounts.google.com", "myaccount.google.com", "google.com"),
        protocols=("html",),
        nexus_category="google",
    ),
    GoogleServiceProfile(
        name="youtube",
        hosts=("youtube.com", "studio.youtube.com"),
        protocols=("html", "rpc"),
        nexus_category="youtube",
    ),
)

_PROFILE_MAP: Dict[str, GoogleServiceProfile] = {profile.name: profile for profile in _PROFILE_LIST}
_ALIAS_MAP: Dict[str, str] = {}
for _profile in _PROFILE_LIST:
    _ALIAS_MAP[_profile.name] = _profile.name
    for _alias in _profile.aliases:
        _ALIAS_MAP[_alias] = _profile.name


def get_google_service_profiles() -> Dict[str, GoogleServiceProfile]:
    """Return the canonical Google service profile registry."""
    return dict(_PROFILE_MAP)


def normalize_google_service_name(service: str) -> str:
    """Normalize historical or shorthand service aliases to canonical names."""
    lowered = service.strip().lower()
    return _ALIAS_MAP.get(lowered, lowered)


def normalize_google_services(services: Optional[Iterable[str]]) -> List[str]:
    """Normalize and de-duplicate a list of Google service names."""
    if not services:
        return []

    normalized: List[str] = []
    for service in services:
        canonical = normalize_google_service_name(service)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def get_google_service_profile(service: str) -> GoogleServiceProfile:
    """Return the profile for a canonical or aliased Google service name."""
    canonical = normalize_google_service_name(service)
    return _PROFILE_MAP.get(canonical, GoogleServiceProfile(name=canonical))


def detect_google_services(urls: Iterable[str]) -> List[str]:
    """Detect which registered Google services appear in a set of request URLs."""
    seen_urls = [url for url in urls if url]
    detected: List[str] = []

    for profile in _PROFILE_LIST:
        if profile.name == "google":
            continue
        if any(profile.matches_url(url) for url in seen_urls):
            detected.append(profile.name)

    if not detected and any("google.com" in url or "googleusercontent.com" in url for url in seen_urls):
        detected.append("google")

    return detected


def describe_google_services(
    services: Iterable[str],
    service_sessions: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a UI/Nexus-friendly description of service capabilities."""
    described: Dict[str, Dict[str, Any]] = {}
    sessions = service_sessions or {}

    for service in normalize_google_services(services):
        profile = get_google_service_profile(service)
        session = sessions.get(profile.name, {})
        described[profile.name] = {
            "aliases": list(profile.aliases),
            "hosts": list(profile.hosts),
            "protocols": list(profile.protocols),
            "nexus_category": profile.nexus_category,
            "has_session": bool(session),
            "session_keys": sorted(session.keys()),
        }

    return described
