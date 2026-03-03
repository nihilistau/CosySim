"""AI Studio Client — Interact with Google AI Studio via gRPC-Web RPC calls.

Extracted from HAR analysis of alkalimakersuite-pa.clients6.google.com.
Auth: SAPISIDHASH header + X-Goog-Api-Key + Google cookies.
Uses GoogleAccountManager for multi-account rotation.

Key capabilities:
- GenerateContent / text generation with Gemini models
- GenerateAccessToken — get Bearer token for direct Gemini API calls
- ListModels — discover available models
- ListPrompts — list saved prompts
- StreamCodeAssistantOfflineGeneration — code generation (streaming)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from engine.nexus.google_account_manager import GoogleAccountManager, get_account_manager

logger = logging.getLogger(__name__)

# ──── Constants ────

_BASE_URL = (
    "https://alkalimakersuite-pa.clients6.google.com"
    "/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService"
)
_APPLET_URL = (
    "https://alkalimakersuite-pa.clients6.google.com"
    "/$rpc/google.internal.alkali.applications.makersuite.v1.MakersuiteAppletControlService"
)
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_ORIGIN = "https://aistudio.google.com"
_DEFAULT_MODEL = "gemini-2.0-flash"

# Token expiry: tokens last ~1h; cache for 55 minutes to be safe
_TOKEN_TTL = 55 * 60

# ──── Singleton ────

_CLIENT_INSTANCE: Optional[AiStudioClient] = None


def get_aistudio_client() -> "AiStudioClient":
    """Return the singleton AiStudioClient instance.

    Returns:
        The global AiStudioClient.
    """
    global _CLIENT_INSTANCE
    if _CLIENT_INSTANCE is None:
        _CLIENT_INSTANCE = AiStudioClient()
    return _CLIENT_INSTANCE


# ──── Client Class ────

class AiStudioClient:
    """HTTP client for Google AI Studio via gRPC-Web-style $rpc endpoints.

    Uses GoogleAccountManager for multi-account cookie rotation and
    SAPISIDHASH authentication.

    Usage:
        client = get_aistudio_client()
        text = client.generate("Explain quantum entanglement in one paragraph")
        models = client.list_models()
    """

    def __init__(self, manager: Optional[GoogleAccountManager] = None) -> None:
        """Initialise the client.

        Args:
            manager: Optional GoogleAccountManager override; defaults to the singleton.
        """
        self._manager: GoogleAccountManager = manager or get_account_manager()
        # token cache: account_id -> (token_str, expires_at)
        self._token_cache: Dict[str, tuple[str, float]] = {}

    # ──── Header Construction ────

    def _get_headers(self, account_id: Optional[str] = None) -> Dict[str, str]:
        """Build authenticated request headers for an AI Studio call.

        Fetches the least-recently-used account (or the specified one),
        computes SAPISIDHASH, and assembles the full header dict.

        Args:
            account_id: Optional specific account to use.

        Returns:
            Dict of HTTP headers, or empty dict if no account is available.
        """
        if account_id:
            account = self._manager._load_account(account_id)  # noqa: SLF001
        else:
            account = self._manager.get_account("aistudio")

        if account is None:
            logger.warning("No available AI Studio account for headers")
            return {}

        aid = account["account_id"]
        sapisid_hash = self._manager.get_sapisid_hash(aid, _ORIGIN)
        api_key = account.get("api_keys", {}).get("aistudio", "")

        # Build cookie string from stored cookies
        cookies = account.get("cookies", {})
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

        headers: Dict[str, str] = {
            "Content-Type": "application/json+protobuf",
            "Origin": _ORIGIN,
            "X-Goog-AuthUser": "0",
            "Cookie": cookie_str,
        }
        if sapisid_hash:
            headers["Authorization"] = f"SAPISIDHASH {sapisid_hash}"
        if api_key:
            headers["X-Goog-Api-Key"] = api_key

        return headers

    # ──── Core RPC Helper ────

    def _rpc(
        self,
        method: str,
        body: Any,
        service: str = "maker",
        account_id: Optional[str] = None,
    ) -> Any:
        """Execute a gRPC-Web style $rpc call to AI Studio.

        Args:
            method: The RPC method name (e.g. "ListModels").
            body: Request body; will be JSON-serialised.
            service: "maker" for MakerSuiteService, "applet" for AppletControlService.
            account_id: Optional account override.

        Returns:
            Parsed JSON response (with XSSI prefix stripped), or None on error.
        """
        base = _APPLET_URL if service == "applet" else _BASE_URL
        url = f"{base}/{method}"
        headers = self._get_headers(account_id)
        if not headers:
            return None

        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            logger.warning("RPC %s HTTP %d: %s", method, exc.code, exc.reason)
            if exc.code == 429:
                account = self._manager.get_account("aistudio")
                if account:
                    self._manager.mark_rate_limited(account["account_id"])
            return None
        except Exception as exc:
            logger.error("RPC %s failed: %s", method, exc)
            return None

        # Strip XSSI prefix (")]}'\n")
        stripped = raw.lstrip(")]}'\n")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug("Failed to parse RPC %s response as JSON", method)
            return None

    # ──── Access Token ────

    def generate_access_token(
        self,
        account_id: Optional[str] = None,
    ) -> Optional[str]:
        """Obtain a short-lived Bearer token from AI Studio.

        Tokens are cached for 55 minutes (tokens last approximately 1 hour).

        Args:
            account_id: Optional specific account to use.

        Returns:
            Bearer token string (``ya29.a0...``), or None on failure.
        """
        # Resolve which account we'll use for caching
        if account_id is None:
            account = self._manager.get_account("aistudio")
            if account is None:
                return None
            account_id = account["account_id"]

        # Check cache
        cached = self._token_cache.get(account_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at:
                return token

        result = self._rpc("GenerateAccessToken", ["users/me"], account_id=account_id)
        if not result or not isinstance(result, list) or not result:
            logger.warning("GenerateAccessToken returned unexpected result: %s", type(result))
            return None

        token = result[0] if isinstance(result[0], str) else None
        if token:
            self._token_cache[account_id] = (token, time.time() + _TOKEN_TTL)
            logger.debug("Cached access token for account %s (expires in %ds)", account_id, _TOKEN_TTL)
        return token

    # ──── Text Generation ────

    def generate(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        account_id: Optional[str] = None,
    ) -> Optional[str]:
        """Generate text using the Gemini API via a Bearer access token.

        Acquires a Bearer token from AI Studio then calls the public
        Gemini REST API directly.  On rate-limit the current account is
        marked and None is returned.

        Args:
            prompt: The user prompt.
            model: Gemini model ID (default ``gemini-2.0-flash``).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            account_id: Optional account to use.

        Returns:
            Generated text string, or None on failure.
        """
        # Resolve account for rate-limit marking
        if account_id is None:
            account = self._manager.get_account("aistudio")
            if account is None:
                logger.warning("No available account for generate()")
                return None
            account_id = account["account_id"]

        token = self.generate_access_token(account_id)
        if not token:
            logger.warning("Could not acquire access token for account %s", account_id)
            return None

        # Get API key from account for the URL parameter
        acct_data = self._manager._load_account(account_id)  # noqa: SLF001
        api_key = (acct_data or {}).get("api_keys", {}).get("aistudio", "")
        key_param = f"?key={api_key}" if api_key else ""

        url = f"{_GEMINI_API_BASE}/models/{model}:generateContent{key_param}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": _ORIGIN,
        }
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                logger.warning("Rate limit on account %s", account_id)
                self._manager.mark_rate_limited(account_id)
            else:
                logger.warning("generate() HTTP %d: %s", exc.code, exc.reason)
            return None
        except Exception as exc:
            logger.error("generate() failed: %s", exc)
            return None

        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Failed to parse generate() response: %s", exc)
            return None

    def generate_with_rotation(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Optional[str]:
        """Try generating with each available account in rotation.

        Attempts every non-rate-limited account until one succeeds.

        Args:
            prompt: The user prompt.
            model: Gemini model ID.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            First successful generated text, or None if all accounts fail.
        """
        accounts = self._manager.get_all_accounts()
        available = [a for a in accounts if not a.get("is_rate_limited")]
        if not available:
            logger.warning("No available accounts for generate_with_rotation()")
            return None

        for account in available:
            aid = account["account_id"]
            result = self.generate(prompt, model, temperature, max_tokens, account_id=aid)
            if result is not None:
                return result
            logger.debug("Account %s failed, trying next", aid)

        return None

    # ──── Model Discovery ────

    def list_models(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available Gemini models in AI Studio.

        Args:
            account_id: Optional account override.

        Returns:
            List of model dicts with keys: id, version, name, description,
            context_window, max_output.  Empty list on failure.
        """
        result = self._rpc("ListModels", [], account_id=account_id)
        if not result or not isinstance(result, list):
            return []

        models: List[Dict[str, Any]] = []
        # Top-level result[0] is typically the model list
        model_list = result[0] if result and isinstance(result[0], list) else result
        for entry in model_list:
            if not isinstance(entry, list):
                continue
            try:
                models.append({
                    "id": entry[0] if len(entry) > 0 else "",
                    "version": entry[2] if len(entry) > 2 else "",
                    "name": entry[3] if len(entry) > 3 else "",
                    "description": entry[4] if len(entry) > 4 else "",
                    "context_window": entry[5] if len(entry) > 5 else 0,
                    "max_output": entry[6] if len(entry) > 6 else 0,
                })
            except (IndexError, TypeError):
                continue
        return models

    # ──── Prompt Management ────

    def list_prompts(
        self,
        page_size: int = 100,
        account_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List saved prompts in AI Studio.

        Args:
            page_size: Maximum number of prompts to return.
            account_id: Optional account override.

        Returns:
            List of prompt dicts, or empty list on failure.
        """
        result = self._rpc("ListPrompts", [page_size], account_id=account_id)
        if not result or not isinstance(result, list):
            return []
        # Normalise: wrap bare items in dicts
        prompts: List[Dict[str, Any]] = []
        raw_list = result[0] if result and isinstance(result[0], list) else result
        for item in raw_list:
            if isinstance(item, dict):
                prompts.append(item)
            elif isinstance(item, list):
                prompts.append({"data": item})
        return prompts

    # ──── Availability ────

    def is_available(self) -> bool:
        """Check whether any non-rate-limited account is available.

        Returns:
            True if at least one account can be used.
        """
        return self._manager.available_count("aistudio") > 0
