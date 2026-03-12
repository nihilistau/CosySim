"""Google Workspace Gemini client for appsgenaiserver-pa endpoints.

Provides unified access to the Gemini AI features embedded in Google Workspace
apps (Sheets, Docs, Slides). These endpoints use gRPC-JSON transcoding with
API key authentication and ``application/json+protobuf`` content type.

Discovered via HAR mining of Sheets Gemini interactions (March 2026).
Host: appsgenaiserver-pa.clients6.google.com
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, Generator, List, Optional

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_GENAI_BASE = "https://appsgenaiserver-pa.clients6.google.com/v1/genai"
_CLOUD_SEARCH_BASE = "https://cloudsearch.clients6.google.com/v1/query"
_CONTENT_TYPE = "application/json+protobuf"
_ORIGIN = "https://docs.google.com"
_REFERER = "https://docs.google.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

# Default API key pattern observed in HAR captures.  Overridable via config.
_DEFAULT_API_KEY = ""


# ──── Client ─────────────────────────────────────────────────────────────────


class WorkspaceGeminiClient:
    """Unified Gemini client for Workspace-embedded AI endpoints.

    Uses the shared ``appsgenaiserver-pa.clients6.google.com`` host that powers
    Gemini features inside Sheets, Docs, and Slides.  Authentication combines
    an API key (query param) with SAPISIDHASH session cookies.

    Args:
        account: Authenticated GoogleAccount from the pool.
        api_key: Optional API key override.  Falls back to account-level or
            config-level key.
    """

    def __init__(
        self,
        account: GoogleAccount,
        api_key: Optional[str] = None,
    ) -> None:
        self._account = account
        self._api_key = api_key or _DEFAULT_API_KEY
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

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

        Returns:
            Settings dict from the API response.
        """
        headers = self._get_headers()
        params = self._get_params()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/getSettings",
                headers=headers,
                params=params,
                json={},
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_protobuf_json(resp)
        except requests.RequestException as exc:
            logger.error("Workspace Gemini getSettings failed: %s", exc)
            return {"error": str(exc)}

    def list_gems(self) -> List[Dict[str, Any]]:
        """List available Gemini models and capabilities.

        Returns:
            List of gem/model dicts with name, capabilities, and status.
        """
        headers = self._get_headers()
        params = self._get_params()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/listGems",
                headers=headers,
                params=params,
                json={},
                timeout=30,
            )
            resp.raise_for_status()
            data = self._parse_protobuf_json(resp)
            return data.get("gems", data.get("models", [data]))
        except requests.RequestException as exc:
            logger.error("Workspace Gemini listGems failed: %s", exc)
            return []

    def quota_summary(self) -> Dict[str, Any]:
        """Get API usage quota information for Workspace Gemini.

        Returns:
            Quota dict with usage counts, limits, and reset times.
        """
        headers = self._get_headers()
        params = self._get_params()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/quotaSummary",
                headers=headers,
                params=params,
                json={},
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_protobuf_json(resp)
        except requests.RequestException as exc:
            logger.error("Workspace Gemini quotaSummary failed: %s", exc)
            return {"error": str(exc)}

    def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update Gemini user settings.

        Args:
            settings: Settings dict to update.

        Returns:
            Updated settings response.
        """
        headers = self._get_headers()
        params = self._get_params()

        try:
            resp = self._session.post(
                f"{_GENAI_BASE}/updateUserSettings",
                headers=headers,
                params=params,
                json=settings,
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

        This powers cross-service semantic search across Drive, Docs, Sheets,
        Gmail, and other Workspace apps.

        Args:
            query: Search query string.
            page_size: Number of results to return.
            source_types: Optional list of source type filters
                (e.g. ["drive", "gmail", "docs"]).

        Returns:
            Search results dict with items and metadata.
        """
        payload: Dict[str, Any] = {
            "query": query,
            "pageSize": page_size,
        }
        if source_types:
            payload["dataSourceRestrictions"] = [
                {"source": {"name": s}} for s in source_types
            ]

        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        params = self._get_params()

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

    # ──── Payload Construction ───────────────────────────────────────────────

    def _build_generate_payload(
        self,
        prompt: str,
        context: Optional[str] = None,
        document_id: Optional[str] = None,
        document_type: str = "sheets",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Build the streamGenerate request payload.

        The payload follows the gRPC-JSON transcoded protobuf format observed
        in HAR captures of Sheets Gemini interactions.

        Args:
            prompt: User prompt.
            context: Optional context content.
            document_id: Optional document ID.
            document_type: Type of workspace document.
            temperature: Generation temperature.
            max_tokens: Maximum output tokens.

        Returns:
            Request payload dict.
        """
        payload: Dict[str, Any] = {
            "prompt": {
                "text": prompt,
            },
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "topP": 0.95,
                "topK": 40,
            },
        }

        if context:
            payload["prompt"]["context"] = context

        if document_id:
            doc_type_map = {
                "sheets": "SPREADSHEET",
                "docs": "DOCUMENT",
                "slides": "PRESENTATION",
            }
            payload["documentContext"] = {
                "documentId": document_id,
                "documentType": doc_type_map.get(document_type, "DOCUMENT"),
            }

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
        """Extract generated text from a stream chunk.

        Navigates the protobuf-JSON structure to find text content.  The
        exact path varies but common patterns are handled.

        Args:
            chunk: Parsed JSON chunk from the stream.

        Returns:
            Extracted text or empty string.
        """
        if isinstance(chunk, dict):
            for key in ("text", "content", "output"):
                if key in chunk:
                    val = chunk[key]
                    if isinstance(val, str):
                        return val
                    if isinstance(val, dict):
                        return val.get("text", val.get("parts", [{}])[0].get("text", ""))
            if "candidates" in chunk:
                candidates = chunk["candidates"]
                if candidates and isinstance(candidates, list):
                    first = candidates[0]
                    content = first.get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
        elif isinstance(chunk, list) and chunk:
            if isinstance(chunk[0], str):
                return chunk[0]
        return ""

    @staticmethod
    def _extract_model(chunks: List[Any]) -> str:
        """Extract model name from response chunks.

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
        return ""

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
) -> WorkspaceGeminiClient:
    """Create a WorkspaceGeminiClient with an account from the pool.

    Args:
        account_name: Optional account name to select from pool.
        api_key: Optional API key override.

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
    return WorkspaceGeminiClient(account=account, api_key=api_key)
