"""Opal client — Google's experimental creative workspace service.

Reverse-engineered from labs.google.har (2026-07-14).  Opal uses the
standard WIZ batchexecute transport at opal.google.com with the same
cookie + CSRF ``at`` token pattern as NotebookLM.

rpcids and REST endpoints defined in ``config/nlm_rpcids.yaml`` v6.0
under the ``opal`` top-level key.
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

_OPAL_BASE = "https://opal.google.com"
_OPAL_RPC_PATH = "/_/Opal/data/batchexecute"
_OPAL_RPC_ENDPOINT = f"{_OPAL_BASE}{_OPAL_RPC_PATH}"
_OPAL_ORIGIN = "https://opal.google.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

_NLM_META_PATH = Path(__file__).resolve().parents[2] / "data" / "nlm_meta.json"

# rpcid for Opal Gemini initialisation (from YAML opal.rpcids.ug7pge)
_RPCID_GENERATE = "ug7pge"


# ──── Client ─────────────────────────────────────────────────────────────────


class OpalClient:
    """Client for Google Opal creative content service.

    Uses the same cookie + ``at`` CSRF token auth pattern as the NLM client.
    Auth credentials are never hardcoded — loaded from ``data/nlm_meta.json``
    or ``get_config()``.

    Args:
        config_override: Optional config dict for testing.
    """

    def __init__(self, config_override: Optional[Dict[str, Any]] = None) -> None:
        self._cfg = config_override or {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._at_token: Optional[str] = None
        self._cookies: str = ""
        self._reqid: int = 1_000_000
        try:
            self._registry = get_rpc_registry()
        except Exception:
            self._registry = None
        self._load_auth()

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _load_auth(self) -> None:
        """Load auth tokens from nlm_meta.json or config (never hardcoded)."""
        # 1. Try data/nlm_meta.json (shared with NLM client)
        if _NLM_META_PATH.exists():
            try:
                meta = json.loads(_NLM_META_PATH.read_text(encoding="utf-8"))
                if not self._at_token and meta.get("at"):
                    self._at_token = meta["at"]
                if not self._cookies and meta.get("cookies"):
                    self._cookies = meta["cookies"]
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Could not read nlm_meta.json: %s", exc)

        # 2. Try account pool for cookie header
        if not self._cookies:
            try:
                from engine.integrations.google_account_pool import get_account_pool
                pool = get_account_pool()
                account = pool.get_best_account(service="opal")
                if account is None:
                    account = pool.get_best_account()
                if account is not None:
                    self._cookies = pool.get_cookie_header(account)
                    raw_at = getattr(account, "at_token", None)
                    if isinstance(raw_at, str) and raw_at and not self._at_token:
                        self._at_token = raw_at
            except Exception as exc:
                logger.debug("Account pool unavailable for Opal: %s", exc)

        # 3. Fallback to config
        if not self._at_token:
            try:
                cfg = get_config()
                self._at_token = cfg.get("opal.at_token") or cfg.get("google.at_token")
            except Exception:
                pass

    def _refresh_auth(self) -> None:
        """Reload auth credentials from disk."""
        self._at_token = None
        self._cookies = ""
        self._load_auth()
        logger.info("Opal auth refreshed")

    def _get_headers(self, referer: str = "/") -> Dict[str, str]:
        """Build Opal request headers with cookie auth.

        Args:
            referer: Referer path suffix appended to the Opal base URL.

        Returns:
            Headers dict ready for ``requests``.
        """
        ref_url = f"{_OPAL_BASE}{referer}" if referer.startswith("/") else referer
        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": _OPAL_ORIGIN,
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

    # ──── batchexecute RPC ────────────────────────────────────────────────────

    def _batchexecute(
        self,
        rpcid: str,
        payload: Any,
        timeout: int = 30,
    ) -> Any:
        """Call Opal via the batchexecute endpoint.

        Args:
            rpcid: Opal rpcid string (e.g. ``"ug7pge"``).
            payload: Python object serialised as the inner f.req payload.
            timeout: HTTP timeout in seconds.

        Returns:
            Parsed inner response or ``None`` if unparseable.
        """
        self._reqid += 100_000
        url = (
            f"{_OPAL_RPC_ENDPOINT}"
            f"?rpcids={rpcid}"
            f"&source-path=%2F"
            f"&hl=en-US"
            f"&_reqid={self._reqid}"
            f"&rt=c"
        )
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        f_req_calls = [[[rpcid, payload_json, None, "generic"]]]
        body_dict: Dict[str, str] = {
            "f.req": json.dumps(f_req_calls, ensure_ascii=False, separators=(",", ":")),
        }
        if self._at_token:
            body_dict["at"] = self._at_token
        body = urllib.parse.urlencode(body_dict)

        headers = self._get_headers()
        try:
            resp = self._session.post(url, headers=headers, data=body, timeout=timeout)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning("Opal batchexecute %s HTTP error: %s", rpcid, exc)
            raise

        return self._parse_batchexecute_response(resp.text, rpcid)

    def _parse_batchexecute_response(self, raw: str, rpcid: str) -> Any:
        """Parse a batchexecute wrb.fr response.

        Args:
            raw: Raw HTTP response body.
            rpcid: rpcid to match in the response.

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
        logger.debug("Could not parse Opal batchexecute response for %s", rpcid)
        return None

    # ──── Core batchexecute RPC (ug7pge) ─────────────────────────────────────

    def generate_content(self, prompt: str, style: str = "default") -> Dict[str, Any]:
        """Generate creative content via Opal using rpcid ug7pge.

        Args:
            prompt: Text prompt for content generation.
            style: Style hint (e.g. ``"default"``, ``"formal"``, ``"creative"``).

        Returns:
            Dict with ``content``, ``rpcid``, and raw ``response`` keys.
        """
        rpcid = _RPCID_GENERATE
        if self._registry:
            try:
                rpcid = self._registry._data.get("opal", {}).get("rpcids", {}).get(
                    "ug7pge", {}
                ) and _RPCID_GENERATE
            except Exception:
                pass

        payload: List[Any] = [prompt, style]
        logger.info("Opal generate_content: prompt_len=%d style=%s", len(prompt), style)
        result = self._batchexecute(rpcid, payload)
        return {
            "content": result[0] if isinstance(result, list) and result else "",
            "rpcid": rpcid,
            "response": result,
        }

    # ──── REST: Drive proxy ───────────────────────────────────────────────────

    def drive_proxy_get(self, content_id: str) -> Dict[str, Any]:
        """Fetch an Opal content item via the Drive proxy.

        Maps to ``GET /api/drive-proxy/drive/v3/files/{file_id}`` from YAML.

        Args:
            content_id: Drive file ID of the Opal content item.

        Returns:
            Dict of file metadata from Drive proxy.

        Raises:
            requests.HTTPError: On non-2xx response.
        """
        url = f"{_OPAL_BASE}/api/drive-proxy/drive/v3/files/{urllib.parse.quote(content_id)}"
        headers = self._get_headers(referer=f"/drive/{content_id}")
        headers["Content-Type"] = "application/json"
        logger.debug("Opal drive_proxy_get: content_id=%s", content_id)
        resp = self._session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def drive_proxy_list(self, page_size: int = 20) -> List[Dict[str, Any]]:
        """List Opal content items via the Drive proxy.

        Args:
            page_size: Maximum number of items to return.

        Returns:
            List of file metadata dicts.
        """
        url = f"{_OPAL_BASE}/api/drive-proxy/drive/v3/files"
        headers = self._get_headers(referer="/")
        headers["Content-Type"] = "application/json"
        params = {"pageSize": page_size}
        logger.debug("Opal drive_proxy_list: page_size=%d", page_size)
        resp = self._session.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("files", [])

    # ──── REST: Gallery ───────────────────────────────────────────────────────

    def gallery_list(
        self,
        category: str = "",
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """List items in the Opal gallery.

        Maps to ``GET /api/gallery/list`` from YAML.

        Args:
            category: Optional category filter (empty string = all).
            page_size: Maximum items to return.

        Returns:
            List of gallery item dicts.
        """
        url = f"{_OPAL_BASE}/api/gallery/list"
        headers = self._get_headers(referer="/gallery")
        headers["Content-Type"] = "application/json"
        params: Dict[str, Any] = {"pageSize": page_size}
        if category:
            params["category"] = category
        logger.debug("Opal gallery_list: category=%r page_size=%d", category, page_size)
        resp = self._session.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", data if isinstance(data, list) else [])

    def gallery_get(self, item_id: str) -> Dict[str, Any]:
        """Get a specific Opal gallery item by ID.

        Args:
            item_id: Gallery item identifier.

        Returns:
            Dict of gallery item metadata.

        Raises:
            requests.HTTPError: On non-2xx response.
        """
        url = f"{_OPAL_BASE}/api/gallery/list/{urllib.parse.quote(item_id)}"
        headers = self._get_headers(referer=f"/gallery/{item_id}")
        headers["Content-Type"] = "application/json"
        logger.debug("Opal gallery_get: item_id=%s", item_id)
        resp = self._session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()


# ──── Module-level convenience ────────────────────────────────────────────────

_opal_client_instance: Optional[OpalClient] = None


def get_opal_client() -> OpalClient:
    """Return a shared OpalClient singleton.

    Returns:
        The module-level OpalClient instance.
    """
    global _opal_client_instance
    if _opal_client_instance is None:
        _opal_client_instance = OpalClient()
    return _opal_client_instance


def reset_opal_client() -> None:
    """Reset the singleton (for testing)."""
    global _opal_client_instance
    _opal_client_instance = None
