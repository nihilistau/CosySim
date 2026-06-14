"""Google Workspace Gemini client for appsgenaiserver-pa endpoints.

Provides unified access to the Gemini AI features embedded in Google Workspace
apps (Sheets, Docs, Slides). These endpoints use gRPC-JSON transcoding with
API key authentication and ``application/json+protobuf`` content type.

Payloads use protobuf-JSON arrays (not dict-style JSON).  Structures verified
against HAR captures of Sheets and Docs Gemini interactions (March–July 2026).

Host: appsgenaiserver-pa.clients6.google.com
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, Dict, Generator, List, Optional

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_GENAI_BASE = "https://appsgenaiserver-pa.clients6.google.com/v1/genai"
_CLOUD_SEARCH_BASE = "https://cloudsearch.clients6.google.com/v1/query"
_ESPRESSO_BASE = "https://espresso-pa.clients6.google.com"
_PEOPLE_BASE = "https://people-pa.clients6.google.com"
_CONTENT_TYPE = "application/json+protobuf"
_ORIGIN = "https://docs.google.com"
_REFERER = "https://docs.google.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

# Context codes (which Workspace app is calling)
CTX_DOCS = 1
CTX_SHEETS = 3
CTX_ESPRESSO_SHEETS = 7  # Prewarm uses 7 for Sheets, not 3

# Operation codes for streamGenerate
OP_INIT = 61
OP_GENERATE_SHEETS = 23
OP_GENERATE_DOCS = 96
OP_CONTINUE = 16
OP_INSERT = 15

# Tier markers (client-side only — free accounts CAN use pro tier)
TIER_FREE = 1
TIER_PRO = 2

# Document MIME types
MIME_SHEETS = "application/vnd.google-apps.ritz"
MIME_DOCS = "application/vnd.google-apps.kix"

# Default API keys per service (Google-embedded client keys from HAR mining)
# v1.61.0 [2026-06-13] — move hardcoded Workspace Gemini API keys to env
# (empty-string fallback). The three drive_* entries share the same real
# values as the Drive client, so they reuse the GOOGLE_DRIVE_KEY_* env vars.
_API_KEYS: Dict[str, str] = {
    "sheets": os.getenv("GOOGLE_WORKSPACE_KEY_SHEETS", ""),
    "docs": os.getenv("GOOGLE_WORKSPACE_KEY_DOCS", ""),
    "cloud_search": os.getenv("GOOGLE_WORKSPACE_KEY_CLOUD_SEARCH", ""),
    "people_autocomplete": os.getenv("GOOGLE_WORKSPACE_KEY_PEOPLE_AUTOCOMPLETE", ""),
    "people_autocomplete_alt": os.getenv("GOOGLE_WORKSPACE_KEY_PEOPLE_AUTOCOMPLETE_ALT", ""),
    "experiments": os.getenv("GOOGLE_WORKSPACE_KEY_EXPERIMENTS", ""),
    "consent": os.getenv("GOOGLE_WORKSPACE_KEY_CONSENT", ""),
    "addons": os.getenv("GOOGLE_WORKSPACE_KEY_ADDONS", ""),
    "addons_alt": os.getenv("GOOGLE_WORKSPACE_KEY_ADDONS_ALT", ""),
    "growth_promos": os.getenv("GOOGLE_WORKSPACE_KEY_GROWTH_PROMOS", ""),
    "analytics": os.getenv("GOOGLE_WORKSPACE_KEY_ANALYTICS", ""),
    "feedback": os.getenv("GOOGLE_WORKSPACE_KEY_FEEDBACK", ""),
    "feedback_trigger": os.getenv("GOOGLE_WORKSPACE_KEY_FEEDBACK_TRIGGER", ""),
    "drive_files": os.getenv("GOOGLE_DRIVE_KEY_UPLOAD", ""),
    "drive_files_alt": os.getenv("GOOGLE_DRIVE_KEY_READ", ""),
    "drive_permissions": os.getenv("GOOGLE_DRIVE_KEY_PERMS", ""),
    "ogads": os.getenv("GOOGLE_WORKSPACE_KEY_OGADS", ""),
}


# ──── Client ─────────────────────────────────────────────────────────────────


class WorkspaceGeminiClient:
    """Unified Gemini client for Workspace-embedded AI endpoints.

    Uses the shared ``appsgenaiserver-pa.clients6.google.com`` host that powers
    Gemini features inside Sheets, Docs, and Slides.  Authentication combines
    an API key (query param) with SAPISIDHASH session cookies.

    Payloads use protobuf-JSON arrays, not dict-style JSON.  The correct
    structure was verified via HAR captures of live Sheets/Docs sessions.

    Args:
        account: Authenticated GoogleAccount from the pool.
        api_key: Optional API key override.  Falls back to the embedded key
            for the given *document_type*.
        document_type: Default Workspace context — ``"sheets"`` or ``"docs"``.
    """

    def __init__(
        self,
        account: GoogleAccount,
        api_key: Optional[str] = None,
        document_type: str = "sheets",
    ) -> None:
        self._account = account
        self._document_type = document_type
        self._api_key = api_key or _API_KEYS.get(document_type, "")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ──── Helpers ─────────────────────────────────────────────────────────────

    def _get_ctx_code(self) -> int:
        """Return the context code for the current document type."""
        return CTX_SHEETS if self._document_type == "sheets" else CTX_DOCS

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _get_headers(
        self,
        origin: str = _ORIGIN,
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Build request headers with SAPISIDHASH auth.

        Args:
            origin: Origin header value (varies by calling app context).
            extra: Additional headers to merge in.

        Returns:
            Complete headers dict.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        sapisid = self._account.cookies.get("SAPISID", "")
        sapisid1p = self._account.cookies.get("__Secure-1PAPISID", sapisid)
        sapisid3p = self._account.cookies.get("__Secure-3PAPISID", sapisid)

        ts = str(int(time.time()))

        def _hash(key: str, prefix: str = "SAPISIDHASH") -> str:
            digest = hashlib.sha1(f"{ts} {key} {origin}".encode()).hexdigest()
            return f"{prefix} {ts}_{digest}"

        auth_parts: List[str] = []
        if sapisid:
            auth_parts.append(_hash(sapisid))
        if sapisid1p:
            auth_parts.append(_hash(sapisid1p, "SAPISID1PHASH"))
        if sapisid3p:
            auth_parts.append(_hash(sapisid3p, "SAPISID3PHASH"))

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": _CONTENT_TYPE,
            "Cookie": cookie_header,
            "Origin": origin,
            "Referer": _REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    def _get_params(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build query parameters with API key.

        Args:
            extra: Additional query parameters.

        Returns:
            Params dict.
        """
        params: Dict[str, str] = {}
        if self._api_key:
            params["key"] = self._api_key
        if extra:
            params.update(extra)
        return params

    # ──── Core Endpoints ─────────────────────────────────────────────────────

    def stream_generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        document_id: Optional[str] = None,
        document_type: str = "sheets",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Generate content using Workspace Gemini streamGenerate.

        This is the core generation endpoint that powers "Help me create" in
        Docs, "Build with Gemini" in Sheets, and other Workspace AI features.

        Args:
            prompt: The user prompt / instruction.
            context: Optional context string (e.g. existing sheet data, doc
                content, or file references).
            document_id: Optional document/spreadsheet ID for context binding.
            document_type: Type of document context (sheets, docs, slides).
            temperature: Generation temperature (0.0-1.0).
            max_tokens: Maximum output tokens.

        Returns:
            Dict with ``text`` (generated content), ``model`` (model used),
            ``usage`` (token counts), and ``raw`` (full response).
        """
        payload = self._build_generate_payload(
            prompt=prompt,
            context=context,
            document_id=document_id,
            document_type=document_type,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        headers = self._get_headers()
        params = self._get_params()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/streamGenerate",
                headers=headers,
                params=params,
                json=payload,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()

            text_parts: List[str] = []
            raw_chunks: List[Any] = []

            for chunk in self._parse_stream(resp):
                raw_chunks.append(chunk)
                text = self._extract_text(chunk)
                if text:
                    text_parts.append(text)

            result_text = "".join(text_parts)
            logger.info(
                "Workspace Gemini generated %d chars for prompt: %.60s",
                len(result_text),
                prompt,
            )

            return {
                "text": result_text,
                "model": self._extract_model(raw_chunks),
                "usage": self._extract_usage(raw_chunks),
                "raw": raw_chunks,
                "document_id": document_id,
            }

        except requests.RequestException as exc:
            logger.error("Workspace Gemini streamGenerate failed: %s", exc)
            return {
                "text": "",
                "model": "",
                "usage": {},
                "raw": [],
                "error": str(exc),
            }

    def get_settings(self) -> Dict[str, Any]:
        """Retrieve Gemini user settings for the current Workspace account.

        Payload is a protobuf-JSON array ``[[ctx, ctx]]`` where *ctx* is the
        context code for the active Workspace app.

        Returns:
            Parsed settings response (list or dict).
        """
        headers = self._get_headers()
        params = self._get_params()
        ctx = self._get_ctx_code()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/getSettings",
                headers=headers,
                params=params,
                json=[[ctx, ctx]],
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_protobuf_json(resp)
        except requests.RequestException as exc:
            logger.error("Workspace Gemini getSettings failed: %s", exc)
            return {"error": str(exc)}

    def list_gems(self, language: str = "en") -> List[Dict[str, Any]]:
        """List available Gemini models and capabilities.

        Payload: ``[ctx_code, language_code]``.

        Args:
            language: BCP-47 language tag (e.g. ``"en"``, ``"en-GB"``).

        Returns:
            List of gem/model dicts with name, capabilities, and status.
        """
        headers = self._get_headers()
        params = self._get_params()
        ctx = self._get_ctx_code()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/listGems",
                headers=headers,
                params=params,
                json=[ctx, language],
                timeout=30,
            )
            resp.raise_for_status()
            data = self._parse_protobuf_json(resp)
            if isinstance(data, dict):
                return data.get("gems", data.get("models", [data]))
            if isinstance(data, list):
                return data
            return [data]
        except requests.RequestException as exc:
            logger.error("Workspace Gemini listGems failed: %s", exc)
            return []

    def quota_summary(self) -> Dict[str, Any]:
        """Get API usage quota information for Workspace Gemini.

        Payload: ``[null, 1, [ctx]]``.

        Returns:
            Parsed quota dict with total, remaining, used, status, and
            reset_epoch fields.
        """
        headers = self._get_headers()
        params = self._get_params()
        ctx = self._get_ctx_code()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/quotaSummary",
                headers=headers,
                params=params,
                json=[None, 1, [ctx]],
                timeout=30,
            )
            resp.raise_for_status()
            raw = self._parse_protobuf_json(resp)
            return self._parse_quota_response(raw)
        except requests.RequestException as exc:
            logger.error("Workspace Gemini quotaSummary failed: %s", exc)
            return {"error": str(exc)}

    def update_settings(self, settings: Optional[List[Any]] = None) -> Dict[str, Any]:
        """Update Gemini user settings.

        Payload: ``[[], [ctx, ctx], null, 1]``.  The *settings* parameter is
        reserved for future per-field overrides but the default payload matches
        the HAR-observed format.

        Args:
            settings: Optional raw payload override.  When ``None`` the
                standard HAR-verified payload is used.

        Returns:
            Updated settings response.
        """
        headers = self._get_headers()
        params = self._get_params()
        ctx = self._get_ctx_code()
        payload: Any = settings if settings is not None else [[], [ctx, ctx], None, 1]

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/updateUserSettings",
                headers=headers,
                params=params,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_protobuf_json(resp)
        except requests.RequestException as exc:
            logger.error("Workspace Gemini updateSettings failed: %s", exc)
            return {"error": str(exc)}

    # ──── Cloud Search ───────────────────────────────────────────────────────

    def cloud_search(
        self,
        query: str,
        page_size: int = 20,
        source_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search across Google Workspace content using Cloud Search.

        Uses a standard JSON payload (not protobuf-JSON) against the
        ``cloudsearch.clients6.google.com`` endpoint with the dedicated
        Cloud Search API key.

        Args:
            query: Search query string.
            page_size: Number of results to return.
            source_types: Optional list of source type filters
                (e.g. ``["drive", "gmail", "docs"]``).

        Returns:
            Search results dict with items and metadata.
        """
        payload: Dict[str, Any] = {
            "query": query,
            "requestOptions": {
                "searchApplicationId": "searchapplications/docs_editor",
                "clientId": "DOCS_EDITOR",
            },
        }
        if page_size != 20:
            payload["pageSize"] = page_size
        if source_types:
            payload["dataSourceRestrictions"] = [
                {"source": {"name": s}} for s in source_types
            ]

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        params = self._get_params(
            extra={"key": _API_KEYS.get("cloud_search", self._api_key)}
        )

        try:
            resp = self._session.post(
                f"{_CLOUD_SEARCH_BASE}/search",
                headers=headers,
                params=params,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("Cloud Search failed: %s", exc)
            return {"error": str(exc), "results": []}

    # ──── Espresso Prewarm ───────────────────────────────────────────────────

    def prewarm(
        self,
        document_id: str,
        document_title: str = "",
        document_type: Optional[str] = None,
        locale: str = "en",
    ) -> Dict[str, Any]:
        """Fire-and-forget prewarm call to Espresso for faster first generation.

        Call this before the first ``stream_generate`` in a session to warm
        Google's model servers.  The endpoint returns an empty array on success.

        The Espresso endpoint uses a different context code mapping:
        Sheets=7 (not 3), Docs=1 (same).

        Args:
            document_id: Spreadsheet or document ID.
            document_title: Human-readable title (optional hint).
            document_type: ``"sheets"`` or ``"docs"``; falls back to instance
                default.
            locale: User locale string (default ``"en"``).

        Returns:
            Dict with ``success`` bool and optional ``error``.
        """
        doc_type = document_type or self._document_type
        espresso_ctx = CTX_ESPRESSO_SHEETS if doc_type == "sheets" else CTX_DOCS
        session_token = f"goog_{hash(document_id) % 2**31}"
        version = "6"

        payload = [
            [
                None, None, locale, None, espresso_ctx,
                [document_title] if document_title else [],
                version, None, document_id, session_token,
            ]
        ]

        api_key = _API_KEYS.get(doc_type, self._api_key)
        headers = self._get_headers()
        headers["Content-Type"] = _CONTENT_TYPE
        params = self._get_params(extra={"key": api_key})

        try:
            resp = self._session.post(
                f"{_ESPRESSO_BASE}/v1/prewarm",
                headers=headers,
                params=params,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            logger.debug("Prewarm succeeded for %s (%s)", document_id, doc_type)
            return {"success": True, "document_id": document_id}
        except requests.RequestException as exc:
            logger.warning("Prewarm failed (non-fatal): %s", exc)
            return {"success": False, "error": str(exc)}

    # ──── Gem Management ─────────────────────────────────────────────────────

    def select_gem(
        self,
        gem_id: str,
        prompt: str,
        document_id: Optional[str] = None,
        document_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate content using a specific Gem (custom AI persona).

        Uses the same ``streamGenerate`` endpoint but includes the gem_id
        in the payload to activate that persona's style and instructions.

        Args:
            gem_id: Gem identifier from ``list_gems()`` — e.g.
                ``"writing-editor"``, ``"brainstormer"``, or a hex hash for
                custom gems.
            prompt: User prompt.
            document_id: Optional document ID for context.
            document_type: ``"sheets"`` or ``"docs"``.

        Returns:
            Generation result dict with ``text``, ``model``, ``gem_id``.
        """
        doc_type = document_type or self._document_type
        ctx_code = CTX_SHEETS if doc_type == "sheets" else CTX_DOCS
        op_code = OP_GENERATE_SHEETS if doc_type == "sheets" else OP_GENERATE_DOCS
        session_id = f"goog_{hash(prompt) % 2**31}"

        context_array: List[Any] = [ctx_code, None, None, None, session_id]

        if doc_type == "sheets":
            prompt_array: List[Any] = [None, None, prompt] + [None] * 27 + ["0"]
        else:
            prompt_array = [None, None, None, [[[None, None, prompt]]]]

        # Gem reference is placed in the tier/config block
        tier_block: List[Any] = [
            TIER_PRO, None,
            [[None, "1", 1182]],
            None, None, None,
            gem_id,
        ]

        payload: List[Any] = [
            [op_code, None, context_array, prompt_array, None, tier_block, 1],
            [ctx_code, None, 1],
        ]

        return self._execute_generate(payload, gem_id=gem_id)

    def _execute_generate(
        self,
        payload: List[Any],
        gem_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a streamGenerate call with a pre-built payload.

        Args:
            payload: Complete protobuf-JSON payload array.
            gem_id: Optional gem ID for metadata tagging.

        Returns:
            Result dict with ``text``, ``model``, ``gem_id``, ``usage``,
            ``chunks``.
        """
        headers = self._get_headers()
        headers["Content-Type"] = _CONTENT_TYPE
        params = self._get_params(extra={"key": self._api_key, "alt": "sse"})

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/streamGenerate",
                headers=headers,
                params=params,
                json=payload,
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            chunks = list(self._parse_stream(resp))
            text_parts = [self._extract_text(c) for c in chunks]
            text = "\n".join(t for t in text_parts if t)
            model = self._extract_model(chunks)
            usage = self._extract_usage(chunks)

            result: Dict[str, Any] = {
                "text": text,
                "model": model,
                "usage": usage,
                "chunks": len(chunks),
            }
            if gem_id:
                result["gem_id"] = gem_id
            return result
        except requests.RequestException as exc:
            logger.error("streamGenerate failed: %s", exc)
            return {"text": "", "error": str(exc)}

    # ──── People Stack ───────────────────────────────────────────────────────

    def people_autocomplete(
        self,
        query: str,
        max_results: int = 10,
        context: str = "SHARING",
    ) -> Dict[str, Any]:
        """Autocomplete people/contacts search via PeopleStack gRPC.

        Uses the ``PeopleStackAutocompleteService/Autocomplete`` gRPC-Web
        endpoint to search for users by name or email prefix.

        Args:
            query: Search query (name or email prefix).
            max_results: Maximum number of results.
            context: Context hint (``"SHARING"``, ``"MENTION"``).

        Returns:
            Dict with ``results`` list and ``count``.
        """
        api_key = _API_KEYS.get("people_autocomplete", "")
        grpc_path = "/peoplestack.PeopleStackAutocompleteService/Autocomplete"

        payload = {
            "query": query,
            "maxResults": max_results,
            "context": context,
        }

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        headers["X-Goog-Api-Key"] = api_key

        try:
            resp = self._session.post(
                f"{_PEOPLE_BASE}{grpc_path}",
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", data.get("people", []))
            return {
                "results": results if isinstance(results, list) else [],
                "count": len(results) if isinstance(results, list) else 0,
                "query": query,
            }
        except requests.RequestException as exc:
            logger.error("PeopleStack autocomplete failed: %s", exc)
            return {"results": [], "count": 0, "error": str(exc)}

    def people_warmup(self) -> Dict[str, Any]:
        """Prewarm the PeopleStack autocomplete service.

        Fire-and-forget warmup call to reduce latency on subsequent
        autocomplete requests.

        Returns:
            Dict with ``success`` bool.
        """
        api_key = _API_KEYS.get("people_autocomplete", "")
        grpc_path = "/peoplestack.PeopleStackAutocompleteService/Warmup"

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        headers["X-Goog-Api-Key"] = api_key

        try:
            resp = self._session.post(
                f"{_PEOPLE_BASE}{grpc_path}",
                headers=headers,
                json={},
                timeout=5,
            )
            resp.raise_for_status()
            return {"success": True}
        except requests.RequestException as exc:
            logger.debug("PeopleStack warmup failed (non-fatal): %s", exc)
            return {"success": False, "error": str(exc)}

    # ──── Experiment Flags ───────────────────────────────────────────────────

    def get_experiment_flags(self) -> Dict[str, Any]:
        """Retrieve experiment/feature flags for the current user.

        Calls the ``PeopleStackExperimentsService/GetExperimentFlags`` gRPC
        endpoint to discover which features and A/B tests are active.

        Returns:
            Dict with ``flags`` list, ``count``, and ``raw`` response.
        """
        api_key = _API_KEYS.get("experiments", "")
        grpc_path = (
            "/peoplestackwebexperiments.PeopleStackExperimentsService"
            "/GetExperimentFlags"
        )

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        headers["X-Goog-Api-Key"] = api_key

        try:
            resp = self._session.post(
                f"{_PEOPLE_BASE}{grpc_path}",
                headers=headers,
                json={},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            flags = data.get("flags", data.get("experimentFlags", []))
            flag_list = flags if isinstance(flags, list) else []
            return {
                "flags": flag_list,
                "count": len(flag_list),
                "raw": data,
            }
        except requests.RequestException as exc:
            logger.error("GetExperimentFlags failed: %s", exc)
            return {"flags": [], "count": 0, "error": str(exc)}

    # ──── Addons ─────────────────────────────────────────────────────────────

    def list_addons(self) -> Dict[str, Any]:
        """List installed Google Workspace add-ons.

        Calls ``AddOnService/ListInstallations`` gRPC endpoint.

        Returns:
            Dict with ``addons`` list and ``count``.
        """
        api_key = _API_KEYS.get("addons", "")
        grpc_path = (
            "/google.internal.apps.addons.v1.AddOnService/ListInstallations"
        )

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        headers["X-Goog-Api-Key"] = api_key

        try:
            resp = self._session.post(
                f"{_PEOPLE_BASE}{grpc_path}",
                headers=headers,
                json={},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            addons = data.get("installations", data.get("addons", []))
            addon_list = addons if isinstance(addons, list) else []
            return {
                "addons": addon_list,
                "count": len(addon_list),
            }
        except requests.RequestException as exc:
            logger.error("ListInstallations failed: %s", exc)
            return {"addons": [], "count": 0, "error": str(exc)}

    # ──── Growth Promos ──────────────────────────────────────────────────────

    def fetch_promos(self, surface: str = "DOCS_EDITOR") -> Dict[str, Any]:
        """Fetch growth/promotional recommendations for the current surface.

        Calls ``FetchRecommendations`` to discover what features Google is
        pushing to the user — useful for tracking new capabilities.

        Args:
            surface: Product surface (``"DOCS_EDITOR"``, ``"SHEETS_EDITOR"``).

        Returns:
            Dict with ``promos`` list.
        """
        api_key = _API_KEYS.get("growth_promos", "")

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        headers["X-Goog-Api-Key"] = api_key

        payload = {"surface": surface}

        try:
            resp = self._session.post(
                f"{_PEOPLE_BASE}/growthpromos.GrowthPromosService/FetchRecommendations",
                headers=headers,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "promos": data.get("recommendations", []),
                "surface": surface,
            }
        except requests.RequestException as exc:
            logger.debug("FetchRecommendations failed (non-fatal): %s", exc)
            return {"promos": [], "error": str(exc)}

    # ──── Tier Override ──────────────────────────────────────────────────────

    def stream_generate_pro(
        self,
        prompt: str,
        context: Optional[str] = None,
        document_id: Optional[str] = None,
        document_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stream generate with Pro tier marker (client-side gating bypass).

        Identical to ``stream_generate`` but forces ``[2]`` (Pro) tier marker
        in the payload, which unlocks higher-quality model responses on free
        accounts.

        Args:
            prompt: User prompt.
            context: Optional context.
            document_id: Optional document ID.
            document_type: ``"sheets"`` or ``"docs"``.

        Returns:
            Generation result dict.
        """
        doc_type = document_type or self._document_type
        payload = self._build_generate_payload(
            prompt=prompt,
            context=context,
            document_id=document_id,
            document_type=doc_type,
        )
        # Override tier marker: payload[0][5][0] = 2 (Pro)
        if (isinstance(payload, list) and len(payload) > 0
                and isinstance(payload[0], list) and len(payload[0]) > 5
                and isinstance(payload[0][5], list) and len(payload[0][5]) > 0):
            payload[0][5][0] = TIER_PRO

        return self._execute_generate(payload)

    # ──── Payload Construction ───────────────────────────────────────────────

    def _build_generate_payload(
        self,
        prompt: str,
        context: Optional[str] = None,
        document_id: Optional[str] = None,
        document_type: str = "sheets",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> List[Any]:
        """Build the streamGenerate request payload as a protobuf-JSON array.

        The actual Google endpoint expects deeply nested arrays, not dict-style
        JSON.  Structure verified against HAR captures.

        Outer shape::

            body = [
                [op_code, null, context_array, prompt_array, null,
                 [null, null, 1], 1],
                [null, null, 1],
            ]

        Args:
            prompt: User prompt.
            context: Optional context content.
            document_id: Optional document/spreadsheet ID.
            document_type: ``"sheets"`` or ``"docs"``.
            temperature: Generation temperature (informational — the real API
                does not expose this directly in the payload).
            max_tokens: Maximum output tokens (informational).

        Returns:
            Nested list matching protobuf-JSON wire format.
        """
        ctx_code = CTX_SHEETS if document_type == "sheets" else CTX_DOCS
        mime = MIME_SHEETS if document_type == "sheets" else MIME_DOCS
        op_code = OP_GENERATE_SHEETS if document_type == "sheets" else OP_GENERATE_DOCS

        session_id = f"goog_{hash(prompt) % 2**31}"

        # Minimal context array
        context_array: List[Any] = [ctx_code, None, None, None, session_id]
        if document_id:
            context_array.append([])   # sheet/doc data placeholder
            context_array.append("0")  # position marker
            doc_ref_type = 1 if document_type == "docs" else 12
            context_array.append([None, None, None, [
                [[None, None, None, None, None, None, None, [None, None, [
                    [document_id, mime, doc_ref_type]
                ]]]]
            ]])

        # Build prompt array — format differs by app context
        if document_type == "sheets":
            prompt_array: List[Any] = [None, None, prompt] + [None] * 27 + ["0"]
        else:
            prompt_array = [None, None, None, [[[None, None, prompt]]]]

        payload: List[Any] = [
            [op_code, None, context_array, prompt_array, None, [None, None, 1], 1],
            [None, None, 1],
        ]
        return payload

    # ──── Response Parsing ───────────────────────────────────────────────────

    def _parse_stream(
        self, response: requests.Response
    ) -> Generator[Dict[str, Any], None, None]:
        """Parse a chunked streaming response from streamGenerate.

        The response uses chunked transfer encoding with protobuf-JSON frames.
        Each chunk may contain partial or complete JSON objects.

        Args:
            response: The streaming HTTP response.

        Yields:
            Parsed JSON chunks from the stream.
        """
        buffer = ""
        for chunk in response.iter_content(chunk_size=4096, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk
            while buffer:
                try:
                    obj, end_idx = json.JSONDecoder().raw_decode(buffer)
                    yield obj
                    buffer = buffer[end_idx:].lstrip()
                except json.JSONDecodeError:
                    break

    def _parse_protobuf_json(self, response: requests.Response) -> Dict[str, Any]:
        """Parse a non-streaming protobuf-JSON response.

        Handles the ``application/json+protobuf`` content type returned by
        non-streaming Workspace Gemini endpoints.

        Args:
            response: HTTP response.

        Returns:
            Parsed response dict.
        """
        text = response.text
        if text.startswith(")]}'"):
            text = text[text.index("\n") + 1:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse protobuf-JSON response: %.100s", text)
            return {"raw": text}

    @staticmethod
    def _extract_text(chunk: Any) -> str:
        """Extract generated text from a protobuf-JSON array response chunk.

        Recursively searches for human-readable text strings in deeply nested
        arrays, filtering out base64 tokens, hashes, and short identifiers.

        Args:
            chunk: Parsed JSON chunk from the stream.

        Returns:
            Longest readable text found, or empty string.
        """
        if isinstance(chunk, str):
            if len(chunk) < 20:
                return ""
            if chunk.startswith("$") or chunk.startswith("goog_"):
                return ""
            sample = chunk[:50]
            alpha_count = sum(1 for c in sample if c.isalpha() or c.isspace())
            if alpha_count / max(len(sample), 1) > 0.5:
                return chunk
            return ""

        if isinstance(chunk, list):
            best = ""
            for item in chunk:
                text = WorkspaceGeminiClient._extract_text(item)
                if text and len(text) > len(best):
                    best = text
            return best

        if isinstance(chunk, dict):
            for key in ("text", "content", "output", "candidates", "parts"):
                if key in chunk:
                    text = WorkspaceGeminiClient._extract_text(chunk[key])
                    if text:
                        return text

        return ""

    @staticmethod
    def _extract_model(chunks: List[Any]) -> str:
        """Extract model name from response chunks.

        Handles both dict-style and deeply nested array responses.

        Args:
            chunks: List of parsed response chunks.

        Returns:
            Model name string or empty string.
        """
        for chunk in chunks:
            if isinstance(chunk, dict):
                model = chunk.get("model", chunk.get("modelVersion", ""))
                if model:
                    return str(model)
            elif isinstance(chunk, list):
                found = WorkspaceGeminiClient._find_model_in_array(chunk)
                if found:
                    return found
        return ""

    @staticmethod
    def _find_model_in_array(arr: List[Any]) -> str:
        """Recursively search nested arrays for a model name string.

        Model strings typically contain ``"gemini"`` or ``"models/"``.

        Args:
            arr: Nested list to search.

        Returns:
            Model name string or empty string.
        """
        for item in arr:
            if isinstance(item, str) and ("gemini" in item.lower() or "models/" in item):
                return item
            if isinstance(item, list):
                found = WorkspaceGeminiClient._find_model_in_array(item)
                if found:
                    return found
        return ""

    @staticmethod
    def _parse_quota_response(data: Any) -> Dict[str, Any]:
        """Parse quota protobuf-JSON array response.

        Expected format::

            [[null, [total, null, remaining, status, null, null, [reset_epoch]],
              used_str, [ctx], 1], []]

        Args:
            data: Raw parsed JSON response (typically a nested list).

        Returns:
            Dict with ``total``, ``remaining``, ``used``, ``status``,
            ``reset_epoch``, and ``raw`` fields.
        """
        if not isinstance(data, list) or not data:
            return {"raw": data}
        try:
            quota_entry = data[0]
            if isinstance(quota_entry, list) and len(quota_entry) > 2:
                quota_detail = quota_entry[1]
                if isinstance(quota_detail, list) and len(quota_detail) >= 3:
                    reset_epoch = None
                    if len(quota_detail) > 6 and isinstance(quota_detail[6], list) and quota_detail[6]:
                        reset_epoch = quota_detail[6][0]
                    return {
                        "total": int(quota_detail[0]) if quota_detail[0] else 0,
                        "remaining": int(quota_detail[2]) if quota_detail[2] else 0,
                        "status": quota_detail[3] if len(quota_detail) > 3 else None,
                        "reset_epoch": reset_epoch,
                        "used": quota_entry[2] if len(quota_entry) > 2 else "0",
                        "raw": data,
                    }
        except (IndexError, TypeError, ValueError):
            pass
        return {"raw": data}

    @staticmethod
    def _extract_usage(chunks: List[Any]) -> Dict[str, int]:
        """Extract token usage statistics from response chunks.

        Args:
            chunks: List of parsed response chunks.

        Returns:
            Dict with prompt_tokens, completion_tokens, total_tokens.
        """
        for chunk in chunks:
            if isinstance(chunk, dict):
                usage = chunk.get("usageMetadata", chunk.get("usage", {}))
                if usage:
                    return {
                        "prompt_tokens": usage.get("promptTokenCount", 0),
                        "completion_tokens": usage.get("candidatesTokenCount", 0),
                        "total_tokens": usage.get("totalTokenCount", 0),
                    }
        return {}


# ──── Factory ────────────────────────────────────────────────────────────────


def get_workspace_gemini_client(
    account_name: Optional[str] = None,
    api_key: Optional[str] = None,
    document_type: str = "sheets",
) -> WorkspaceGeminiClient:
    """Create a WorkspaceGeminiClient with an account from the pool.

    Args:
        account_name: Optional account name to select from pool.
        api_key: Optional API key override.
        document_type: Workspace app context (``"sheets"`` or ``"docs"``).

    Returns:
        Configured WorkspaceGeminiClient instance.

    Raises:
        RuntimeError: If no suitable account is available.
    """
    pool = get_account_pool()
    if account_name:
        account = pool.get_account(account_name)
    else:
        account = pool.get_best_account(service="workspace")
    if not account:
        raise RuntimeError("No Google account available for Workspace Gemini")
    return WorkspaceGeminiClient(
        account=account, api_key=api_key, document_type=document_type,
    )
