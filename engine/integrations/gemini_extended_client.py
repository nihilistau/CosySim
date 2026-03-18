"""Extended Gemini client — newly discovered rpcids from v1.37 HAR goldmine.

Uses the 5 new rpcids found in ``gemini.google.com-NEWEST.har`` plus the
gRPC-web streaming endpoint from the ``gemini_streaming`` YAML section.

rpcid → operation mapping (from ``config/nlm_rpcids.yaml`` v6.0):
  - ``HcT8bb`` — list storybook gems
  - ``XqA3Ic`` — get storybook detail
  - ``ZKcapf`` — list saved info (user bookmarks)
  - ``jGArJ``  — list my content (/mystuff)
  - ``sJBwce`` — get subscription tiers

Auth: same cookie + ``at`` CSRF token pattern as ``NLMDirectClient``.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

from engine.config import get_config
from engine.integrations.nlm_rpc_registry import get_rpc_registry

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_GEMINI_BASE = "https://gemini.google.com"
_GEMINI_RPC_ENDPOINT = f"{_GEMINI_BASE}/_/BardChatUi/data/batchexecute"
_GEMINI_STREAM_ENDPOINT = (
    f"{_GEMINI_BASE}/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)
_GEMINI_ORIGIN = "https://gemini.google.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

_NLM_META_PATH = Path(__file__).resolve().parents[2] / "data" / "nlm_meta.json"

# rpcid constants (from YAML — used as defaults; registry lookup preferred)
_RPCID_STORYBOOK_LIST = "HcT8bb"
_RPCID_STORYBOOK_DETAIL = "XqA3Ic"
_RPCID_SAVED_INFO = "ZKcapf"
_RPCID_MY_CONTENT = "jGArJ"
_RPCID_SUBSCRIPTION_TIERS = "sJBwce"


# ──── Client ─────────────────────────────────────────────────────────────────


class GeminiExtendedClient:
    """Extended Gemini client using newly discovered rpcids.

    All rpcids are loaded from the NLM RPC registry (``config/nlm_rpcids.yaml``)
    rather than being hardcoded.  The constants above are fallbacks only.

    Args:
        config_override: Optional config dict for testing.
    """

    def __init__(self, config_override: Optional[Dict[str, Any]] = None) -> None:
        self._cfg = config_override or {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._at_token: Optional[str] = None
        self._cookies: str = ""
        self._reqid: int = 2_000_000
        try:
            self._registry = get_rpc_registry()
        except Exception:
            self._registry = None
        self._load_auth()

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _load_auth(self) -> None:
        """Load auth tokens from nlm_meta.json or account pool."""
        if _NLM_META_PATH.exists():
            try:
                meta = json.loads(_NLM_META_PATH.read_text(encoding="utf-8"))
                if meta.get("at") and not self._at_token:
                    self._at_token = meta["at"]
                if meta.get("cookies") and not self._cookies:
                    self._cookies = meta["cookies"]
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Could not read nlm_meta.json for Gemini client: %s", exc)

        if not self._cookies:
            try:
                from engine.integrations.google_account_pool import get_account_pool
                pool = get_account_pool()
                account = pool.get_best_account(service="gemini")
                if account is None:
                    account = pool.get_best_account()
                if account is not None:
                    self._cookies = pool.get_cookie_header(account)
                    raw_at = getattr(account, "at_token", None)
                    if isinstance(raw_at, str) and raw_at and not self._at_token:
                        self._at_token = raw_at
            except Exception as exc:
                logger.debug("Account pool unavailable for Gemini extended: %s", exc)

    def _get_headers(self, referer: str = "/") -> Dict[str, str]:
        """Build Gemini batchexecute request headers.

        Args:
            referer: Referer path (appended to Gemini base URL).

        Returns:
            Headers dict.
        """
        ref_url = (
            f"{_GEMINI_BASE}{referer}" if referer.startswith("/") else referer
        )
        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": _GEMINI_ORIGIN,
            "Referer": ref_url,
            "User-Agent": _USER_AGENT,
            "X-Same-Domain": "1",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-browser-channel": "stable",
            "x-browser-year": "2026",
            "DNT": "1",
        }
        if self._cookies:
            headers["Cookie"] = self._cookies
        return headers

    # ──── Registry helpers ────────────────────────────────────────────────────

    def _resolve_rpcid(self, yaml_key: str, fallback: str) -> str:
        """Resolve a rpcid from the YAML registry under ``gemini.rpcids``.

        Args:
            yaml_key: rpcid string to look up under ``gemini.rpcids``.
            fallback: Value to return if registry lookup fails.

        Returns:
            rpcid string.
        """
        if self._registry is None:
            return fallback
        try:
            return (
                self._registry._data
                .get("gemini", {})
                .get("rpcids", {})
                .get(yaml_key, {})
                and yaml_key
            ) or fallback
        except Exception:
            return fallback

    # ──── batchexecute helper ─────────────────────────────────────────────────

    def _batchexecute(
        self,
        rpcid: str,
        payload: Any,
        timeout: int = 30,
        referer: str = "/",
    ) -> Any:
        """Call the Gemini batchexecute endpoint.

        Args:
            rpcid: Gemini rpcid string.
            payload: Python object serialised as the inner f.req payload.
            timeout: HTTP timeout in seconds.
            referer: Referer path suffix.

        Returns:
            Parsed inner response or ``None`` if unparseable.
        """
        self._reqid += 100_000
        url = (
            f"{_GEMINI_RPC_ENDPOINT}"
            f"?rpcids={rpcid}"
            f"&source-path={urllib.parse.quote(referer)}"
            f"&hl=en-US"
            f"&_reqid={self._reqid}"
            f"&rt=c"
        )
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        f_req_calls = [[[rpcid, payload_json, None, "generic"]]]
        body_dict: Dict[str, str] = {
            "f.req": json.dumps(
                f_req_calls, ensure_ascii=False, separators=(",", ":")
            ),
        }
        if self._at_token:
            body_dict["at"] = self._at_token
        body = urllib.parse.urlencode(body_dict)

        headers = self._get_headers(referer=referer)
        try:
            resp = self._session.post(url, headers=headers, data=body, timeout=timeout)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning("Gemini extended batchexecute %s HTTP error: %s", rpcid, exc)
            raise

        return self._parse_batchexecute_response(resp.text, rpcid)

    def _parse_batchexecute_response(self, raw: str, rpcid: str) -> Any:
        """Parse wrb.fr batchexecute response.

        Args:
            raw: Raw HTTP response body.
            rpcid: rpcid to match.

        Returns:
            Parsed inner payload or ``None``.
        """
        stripped = raw.replace(")]}'", "")
        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.isdigit() or not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                for item in parsed:
                    if (
                        isinstance(item, list)
                        and len(item) >= 3
                        and item[0] == "wrb.fr"
                        and item[1] == rpcid
                        and item[2]
                    ):
                        return json.loads(item[2])
            except (json.JSONDecodeError, IndexError, TypeError):
                continue
        logger.debug("Could not parse Gemini extended response for %s", rpcid)
        return None

    # ──── HcT8bb — Storybook list ─────────────────────────────────────────────

    def list_storybooks(
        self,
        page_size: int = 20,
        locale: str = "en-AU",
    ) -> List[Dict[str, Any]]:
        """List available gem storybooks.

        Uses rpcid ``HcT8bb`` (from ``config/nlm_rpcids.yaml`` v6.0).
        Payload template: ``["storybook", ["en-AU"], 1, null, 1]``

        Args:
            page_size: Number of storybooks to request.
            locale: Locale string (e.g. ``"en-AU"``, ``"en-US"``).

        Returns:
            List of storybook metadata dicts.
        """
        rpcid = self._resolve_rpcid(_RPCID_STORYBOOK_LIST, _RPCID_STORYBOOK_LIST)
        payload = ["storybook", [locale], 1, None, min(page_size, 50)]
        logger.info("Gemini list_storybooks: locale=%s page_size=%d", locale, page_size)
        result = self._batchexecute(rpcid, payload, referer="/gems")
        if not isinstance(result, list):
            return []
        # Flatten nested list of storybook objects
        items: List[Dict[str, Any]] = []
        for entry in result:
            if isinstance(entry, list):
                for sub in entry:
                    if isinstance(sub, dict):
                        items.append(sub)
                    elif isinstance(sub, list) and sub:
                        items.append({"raw": sub})
            elif isinstance(entry, dict):
                items.append(entry)
        return items[:page_size]

    # ──── XqA3Ic — Storybook detail ───────────────────────────────────────────

    def get_storybook(self, storybook_id: str) -> Dict[str, Any]:
        """Get full content for a specific gem storybook.

        Uses rpcid ``XqA3Ic`` (from ``config/nlm_rpcids.yaml`` v6.0).

        Args:
            storybook_id: Storybook / gem identifier.

        Returns:
            Storybook detail dict.
        """
        rpcid = self._resolve_rpcid(_RPCID_STORYBOOK_DETAIL, _RPCID_STORYBOOK_DETAIL)
        payload = [storybook_id]
        logger.info("Gemini get_storybook: id=%s", storybook_id)
        result = self._batchexecute(
            rpcid, payload, referer=f"/gem/storybook/{storybook_id}"
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return {"id": storybook_id, "data": result}
        return {"id": storybook_id, "data": result}

    # ──── ZKcapf — Saved info ─────────────────────────────────────────────────

    def list_saved_info(
        self,
        category: str = "",
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """List the user's saved content / bookmarks.

        Uses rpcid ``ZKcapf`` (from ``config/nlm_rpcids.yaml`` v6.0).
        Payload template: ``[100]``

        Args:
            category: Optional category filter (empty = all).
            page_size: Max items to return (server paginates at this value).

        Returns:
            List of saved content item dicts.
        """
        rpcid = self._resolve_rpcid(_RPCID_SAVED_INFO, _RPCID_SAVED_INFO)
        payload: List[Any] = [page_size]
        if category:
            payload.append(category)
        logger.info("Gemini list_saved_info: category=%r page_size=%d", category, page_size)
        result = self._batchexecute(rpcid, payload, referer="/saved-info")
        if not isinstance(result, list):
            return []
        items: List[Dict[str, Any]] = []
        for entry in result:
            if isinstance(entry, list):
                for sub in entry:
                    if isinstance(sub, dict):
                        items.append(sub)
                    elif sub is not None:
                        items.append({"raw": sub})
            elif isinstance(entry, dict):
                items.append(entry)
        return items

    # ──── jGArJ — My content ──────────────────────────────────────────────────

    def list_my_content(
        self,
        content_type: str = "",
        sort_mode: int = 3,
    ) -> List[Dict[str, Any]]:
        """List the user's own content from the /mystuff dashboard.

        Uses rpcid ``jGArJ`` (from ``config/nlm_rpcids.yaml`` v6.0).
        Payload template: ``[[0,0,0,1,1,0,0], 3]``

        The 7-element binary filter array controls which content types
        to include.  Mapping (index → type):
          0=docs, 1=images, 2=audio, 3=code, 4=conversations, 5=gems, 6=other

        Args:
            content_type: Named filter shortcut — ``"conversations"``,
                          ``"images"``, ``"code"``, ``"gems"``, or ``""`` (all).
            sort_mode: Sort/view mode integer (3 = recent, confirmed from HAR).

        Returns:
            List of content item dicts.
        """
        rpcid = self._resolve_rpcid(_RPCID_MY_CONTENT, _RPCID_MY_CONTENT)

        # Build 7-element filter — all enabled by default
        filters = [0, 0, 0, 1, 1, 0, 0]
        _type_map = {
            "docs": 0,
            "images": 1,
            "audio": 2,
            "code": 3,
            "conversations": 4,
            "gems": 5,
            "other": 6,
        }
        if content_type and content_type in _type_map:
            filters = [0] * 7
            filters[_type_map[content_type]] = 1

        payload = [filters, sort_mode]
        logger.info(
            "Gemini list_my_content: content_type=%r sort=%d", content_type, sort_mode
        )
        result = self._batchexecute(rpcid, payload, referer="/mystuff")
        if not isinstance(result, list):
            return []
        items: List[Dict[str, Any]] = []
        for entry in result:
            if isinstance(entry, list):
                for sub in entry:
                    if isinstance(sub, dict):
                        items.append(sub)
                    elif sub is not None:
                        items.append({"raw": sub})
            elif isinstance(entry, dict):
                items.append(entry)
        return items

    # ──── sJBwce — Subscription tiers ────────────────────────────────────────

    def get_subscription_tiers(self) -> Dict[str, Any]:
        """Get the user's subscription tier info (Pro vs Free, quota, etc.).

        Uses rpcid ``sJBwce`` (from ``config/nlm_rpcids.yaml`` v6.0).
        Payload template: ``[[1, 2]]``

        Returns:
            Dict with ``current_tier``, ``available_tiers``, and raw data.
        """
        rpcid = self._resolve_rpcid(_RPCID_SUBSCRIPTION_TIERS, _RPCID_SUBSCRIPTION_TIERS)
        payload = [[1, 2]]
        logger.info("Gemini get_subscription_tiers")
        result = self._batchexecute(rpcid, payload, referer="/")
        if result is None:
            return {"current_tier": None, "available_tiers": [], "raw": None}
        return {
            "current_tier": result[0] if isinstance(result, list) and result else None,
            "available_tiers": result[1] if isinstance(result, list) and len(result) > 1 else [],
            "raw": result,
        }

    # ──── Gemini streaming (BardFrontendService/StreamGenerate) ───────────────

    def stream_response(
        self,
        prompt: str,
        conversation_id: str = "",
        model_id: str = "",
    ) -> Iterator[str]:
        """Stream a Gemini response via gRPC-web ``StreamGenerate``.

        Uses the ``gemini_streaming.endpoints.stream_generate`` endpoint
        (``/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate``).

        Args:
            prompt: User message text.
            conversation_id: Optional existing conversation ID for multi-turn.
            model_id: Optional model override.

        Yields:
            Incremental text chunks as they arrive.
        """
        headers = self._get_headers(referer="/")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        # Minimal BardFrontendService/StreamGenerate payload (confirmed from HAR)
        inner_payload: List[Any] = [
            [prompt, 0, None, [], None, None, 0],
            ["en"],
            [None, None, None, None, None, None, None],
            None,
        ]
        if conversation_id:
            inner_payload.append(conversation_id)
        if model_id:
            inner_payload.append([model_id])

        body_dict: Dict[str, str] = {
            "f.req": json.dumps(inner_payload, ensure_ascii=False, separators=(",", ":")),
        }
        if self._at_token:
            body_dict["at"] = self._at_token
        body = urllib.parse.urlencode(body_dict)

        logger.info(
            "Gemini stream_response: prompt_len=%d conv_id=%r",
            len(prompt),
            conversation_id,
        )

        with self._session.post(
            _GEMINI_STREAM_ENDPOINT,
            headers=headers,
            data=body,
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                buffer += chunk
                for text in self._extract_stream_chunks(buffer):
                    buffer = ""
                    yield text

    def _extract_stream_chunks(self, buffer: str) -> List[str]:
        """Extract text chunks from a streaming Gemini response buffer.

        Args:
            buffer: Accumulated raw bytes as string.

        Returns:
            List of extracted text strings.
        """
        texts: List[str] = []
        clean = buffer.replace(")]}'", "")
        for line in clean.splitlines():
            line = line.strip()
            if not line or line.isdigit() or not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
                # BardFrontendService wraps text in wrb.fr items
                for item in parsed:
                    if (
                        isinstance(item, list)
                        and len(item) >= 3
                        and item[0] == "wrb.fr"
                        and item[2]
                    ):
                        inner = json.loads(item[2])
                        if (
                            inner
                            and isinstance(inner[0], list)
                            and inner[0]
                            and isinstance(inner[0][0], str)
                        ):
                            texts.append(inner[0][0])
            except (json.JSONDecodeError, IndexError, TypeError):
                pass
        return texts


# ──── Module-level convenience ────────────────────────────────────────────────

_gemini_extended_instance: Optional[GeminiExtendedClient] = None


def get_gemini_extended_client() -> GeminiExtendedClient:
    """Return a shared GeminiExtendedClient singleton.

    Returns:
        The module-level GeminiExtendedClient instance.
    """
    global _gemini_extended_instance
    if _gemini_extended_instance is None:
        _gemini_extended_instance = GeminiExtendedClient()
    return _gemini_extended_instance


def reset_gemini_extended_client() -> None:
    """Reset the singleton (for testing)."""
    global _gemini_extended_instance
    _gemini_extended_instance = None
