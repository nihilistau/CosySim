"""HAR file extractor for Google authentication credentials.

Parses browser HAR (HTTP Archive) files to extract session cookies,
auth headers, and XSRF tokens needed for direct Google API access.
Also extracts NotebookLM session metadata from batchexecute traffic so
clients can reuse the exact build label and session identifiers captured
from the browser instead of guessing them from a later page load.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, unquote

from engine.integrations.google_service_profiles import (
    GOOGLE_COOKIE_NAMES,
    detect_google_services,
    get_google_service_profile,
    normalize_google_services,
)

logger = logging.getLogger(__name__)

# Backwards-compatible export for existing callers/tests.
COOKIE_NAMES: List[str] = list(GOOGLE_COOKIE_NAMES)

_NLM_BATCH_PATH = "notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
_NLM_BUILD_LABEL_PREFIX = "boq_labs-tailwind-frontend_"


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

    def iter_urls(self) -> List[str]:
        """Return request URLs captured in the HAR."""
        return [
            entry.get("request", {}).get("url", "")
            for entry in self._entries
            if entry.get("request", {}).get("url", "")
        ]

    def list_domains(self) -> List[str]:
        """Return the distinct request hostnames seen in the HAR."""
        domains = {
            parsed.netloc
            for parsed in (urlparse(url) for url in self.iter_urls())
            if parsed.netloc
        }
        return sorted(domains)

    def detect_services(self) -> List[str]:
        """Detect known Google services represented in the HAR."""
        return detect_google_services(self.iter_urls())

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
                if name in target_names and value:
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
                            if k in target_names and v:
                                collected[k] = v

        logger.debug("Extracted %d cookies for domain '%s'", len(collected), domain)
        return collected

    def extract_cookies_for_service(self, service: str) -> Dict[str, str]:
        """Extract canonical cookies scoped to a known Google service surface."""
        profile = get_google_service_profile(service)
        if not profile.hosts:
            return self.extract_cookies("google.com")

        collected: Dict[str, str] = {}
        target_names = set(profile.cookie_names)

        for entry in self._entries:
            request = entry.get("request", {})
            url = request.get("url", "")
            if not profile.matches_url(url):
                continue

            for cookie in request.get("cookies", []):
                name = cookie.get("name", "")
                value = cookie.get("value", "")
                if name in target_names and value:
                    collected[name] = value

            for header in request.get("headers", []):
                if header.get("name", "").lower() != "cookie":
                    continue
                for part in header.get("value", "").split(";"):
                    part = part.strip()
                    if "=" not in part:
                        continue
                    key, _, value = part.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key in target_names and value:
                        collected[key] = value

        return collected or self.extract_cookies("google.com")

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
            token = self._extract_at_from_body(text)
            if token:
                return token
        return None

    @staticmethod
    def _extract_at_from_body(text: str) -> Optional[str]:
        """Extract an ``at`` token from a form-encoded request body."""
        if not text:
            return None
        try:
            params = parse_qs(text)
            if "at" in params and params["at"]:
                return params["at"][0]
        except (TypeError, ValueError):
            logger.debug("Could not parse request body for at token", exc_info=True)

        if "at=" not in text:
            return None

        for part in text.split("&"):
            if part.startswith("at="):
                value = unquote(part[3:])
                if value:
                    return value
        return None

    @staticmethod
    def _is_valid_nlm_build_label(build_label: Optional[str]) -> bool:
        """Return True when a build label looks like a NotebookLM frontend build."""
        return bool(build_label and build_label.startswith(_NLM_BUILD_LABEL_PREFIX))

    def _extract_page_params_from_html(self, html: str) -> Dict[str, str]:
        """Extract NotebookLM session params from page HTML when available."""
        session: Dict[str, str] = {}
        if not html:
            return session

        wiz_match = re.search(r"WIZ_global_data\s*=\s*({.*?});", html, re.DOTALL)
        wiz_data: Dict[str, Any] = {}
        if wiz_match:
            try:
                wiz_data = json.loads(wiz_match.group(1))
            except json.JSONDecodeError:
                logger.debug("Could not parse WIZ_global_data from HAR HTML response")

        for key in ("IxjpMA", "FdrFJe"):
            value = wiz_data.get(key)
            if value not in (None, ""):
                session["f_sid"] = str(value)
                break

        if "f_sid" not in session:
            fsid_match = re.search(r'"(?:IxjpMA|FdrFJe)"\s*:\s*"([^"]+)"', html)
            if fsid_match:
                session["f_sid"] = fsid_match.group(1)

        at_token = wiz_data.get("SNlM0e")
        if isinstance(at_token, str) and at_token:
            session["at"] = at_token
        else:
            at_match = re.search(r'"SNlM0e"\s*:\s*"([^"]+)"', html)
            if at_match:
                session["at"] = at_match.group(1)

        for key in ("QrtxK", "cfb2h", "bl"):
            value = wiz_data.get(key)
            if isinstance(value, str) and self._is_valid_nlm_build_label(value):
                session["bl"] = value
                break

        if "bl" not in session:
            bl_match = re.search(r'"(boq_labs-tailwind-frontend_[^"]+)"', html)
            if bl_match:
                session["bl"] = bl_match.group(1)

        return session

    def extract_nlm_session_metadata(self) -> Dict[str, str]:
        """Extract NotebookLM session metadata from HAR traffic.

        Returns:
            Dict with any of: ``bl``, ``f_sid``, ``at``, ``source_path``,
            and ``notebook_id``.
        """
        session: Dict[str, str] = {}

        for entry in self._entries:
            request = entry.get("request", {})
            url = request.get("url", "")
            if _NLM_BATCH_PATH not in url:
                continue

            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            build_label = params.get("bl", [None])[0]
            if self._is_valid_nlm_build_label(build_label):
                session["bl"] = build_label

            f_sid = params.get("f.sid", [None])[0]
            if f_sid:
                session["f_sid"] = f_sid

            source_path = params.get("source-path", [None])[0]
            if source_path:
                decoded_source_path = unquote(source_path)
                session["source_path"] = decoded_source_path
                notebook_match = re.search(r"/notebook/([a-f0-9-]{36})", decoded_source_path)
                if notebook_match:
                    session["notebook_id"] = notebook_match.group(1)

            at_token = self._extract_at_from_body(request.get("postData", {}).get("text", ""))
            if at_token:
                session["at"] = at_token

        if "at" not in session:
            at_token = self.extract_at_token()
            if at_token:
                session["at"] = at_token

        if session.get("bl") and session.get("f_sid"):
            return session

        for entry in self._entries:
            url = entry.get("request", {}).get("url", "")
            if "notebooklm.google.com" not in url:
                continue

            html = entry.get("response", {}).get("content", {}).get("text", "")
            if not html:
                continue

            html_session = self._extract_page_params_from_html(html)
            for key, value in html_session.items():
                if value and key not in session:
                    session[key] = value

            if session.get("bl") and session.get("f_sid"):
                break

        return session

    def extract_service_bundle(self, service: str) -> Dict[str, Any]:
        """Extract cookies, sessions, and surface metadata for one Google service."""
        profile = get_google_service_profile(service)
        matched_urls = [url for url in self.iter_urls() if profile.matches_url(url)]
        matched_hosts = sorted({urlparse(url).netloc for url in matched_urls if urlparse(url).netloc})
        cookies = self.extract_cookies_for_service(profile.name)
        session = profile.extract_session(self)

        return {
            "service": profile.name,
            "aliases": list(profile.aliases),
            "hosts": matched_hosts or list(profile.hosts),
            "protocols": list(profile.protocols),
            "cookie_count": len(cookies),
            "cookies": cookies,
            "session": session,
        }

    def extract_service_bundles(self, services: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Extract bundles for detected or requested Google services."""
        target_services = normalize_google_services(services or self.detect_services())
        return {
            service: self.extract_service_bundle(service)
            for service in target_services
        }

    # ──── Convenience ─────────────────────────────────────────────────────────

    def to_account_dict(
        self,
        account_name: str,
        services: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a full account dictionary suitable for GoogleAccountPool.

        Args:
            account_name: Human-readable name for this account.
            services: Optional service allow-list to extract richer bundles for.

        Returns:
            Dictionary with account cookies plus detected per-service bundles.
        """
        cookies = self.extract_cookies("google.com")
        authuser = self.extract_authuser()
        detected_services = self.detect_services()
        service_bundles = self.extract_service_bundles(services or detected_services)
        service_sessions = {
            service: bundle["session"]
            for service, bundle in service_bundles.items()
            if bundle.get("session")
        }
        nlm_session = service_sessions.get("notebooklm") or self.extract_nlm_session_metadata()
        at_token = (
            nlm_session.get("at")
            or next(
                (
                    session.get("at")
                    for session in service_sessions.values()
                    if isinstance(session, dict) and session.get("at")
                ),
                None,
            )
            or self.extract_at_token()
        )

        return {
            "name": account_name,
            "cookies": cookies,
            "authuser": authuser,
            "at_token": at_token,
            "nlm_session": nlm_session,
            "detected_services": detected_services,
            "service_bundles": service_bundles,
            "service_sessions": service_sessions,
            "domains": self.list_domains(),
        }
