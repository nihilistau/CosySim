"""GitHub Copilot API client.

Authenticates via a GitHub browser session (cookies) to obtain a short-lived
Bearer token, then calls the Copilot individual API for chat and models.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_TOKEN_URL = "https://github.com/github-copilot/chat/token"
_API_BASE = "https://api.individual.githubcopilot.com"
_INTEGRATION_ID = "copilot-chat"
_API_VERSION = "2025-05-01"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
_MODELS_CACHE_TTL = 6 * 3600  # 6 hours
_TOKEN_BUFFER_SECS = 60       # refresh token this many seconds before expiry

_FALLBACK_COOKIES_DIR = os.path.join("data", "accounts")


# ──── Singleton registry ──────────────────────────────────────────────────────

_instances: Dict[str, "GithubCopilotClient"] = {}
_instances_lock = threading.Lock()


# ──── Client ──────────────────────────────────────────────────────────────────


class GithubCopilotClient:
    """Authenticated GitHub Copilot API client.

    Attributes:
        account_name: Account identifier used to look up cookies.
    """

    def __init__(self, account_name: str = "nihilistcod") -> None:
        self.account_name = account_name
        self._token: str = ""
        self._token_expires: float = 0.0
        self._models_cache: List[Dict[str, Any]] = []
        self._models_cache_time: float = 0.0
        self._lock = threading.Lock()

    # ──── Cookie loading ──────────────────────────────────────────────────────

    def _get_cookies(self) -> Dict[str, str]:
        """Load GitHub cookies from GoogleAccountPool or fallback JSON.

        Returns:
            Mapping of cookie name to value.

        Raises:
            RuntimeError: If no cookies are available for the account.
        """
        # Primary: account pool
        try:
            from engine.integrations.google_account_pool import get_account_pool

            pool = get_account_pool()
            account = pool.get_by_name(self.account_name)
            if account and "github" in account.services and account.cookies:
                return dict(account.cookies)
        except Exception as exc:
            logger.debug("Could not load cookies from account pool: %s", exc)

        # Fallback: JSON file
        json_path = os.path.join(
            _FALLBACK_COOKIES_DIR,
            f"github_{self.account_name}_cookies.json",
        )
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    cookies = json.load(fh)
                if isinstance(cookies, dict) and cookies:
                    logger.debug(
                        "Loaded %d cookies from %s", len(cookies), json_path
                    )
                    return cookies
            except Exception as exc:
                logger.debug("Could not load fallback cookies from %s: %s", json_path, exc)

        raise RuntimeError(
            f"No GitHub cookies available for account '{self.account_name}'. "
            f"Import cookies via GithubAccountImporter or place them at {json_path}."
        )

    # ──── Token management ────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Return a valid Bearer token, refreshing if expired.

        Returns:
            GitHub-Bearer token string.

        Raises:
            RuntimeError: If the token endpoint returns a non-200 status.
        """
        with self._lock:
            if self._token and time.time() < self._token_expires - _TOKEN_BUFFER_SECS:
                return self._token

            cookies = self._get_cookies()
            nonce = f"v2:{uuid.uuid4()}"

            headers = {
                "github-verified-fetch": "true",
                "x-fetch-nonce": nonce,
                "x-github-client-version": "191f53bffd9c6093d6271325d1f6fdf25bb9557a",
                "x-requested-with": "XMLHttpRequest",
                "accept": "application/json",
                "content-type": "application/json",
                "user-agent": _USER_AGENT,
                "origin": "https://github.com",
                "referer": "https://github.com/copilot",
            }

            resp = requests.post(
                _TOKEN_URL,
                headers=headers,
                cookies=cookies,
                json={},
                timeout=30,
            )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Copilot token endpoint returned {resp.status_code}: {resp.text[:200]}"
                )

            data = resp.json()
            token = data.get("token", "")
            expiration_str = data.get("expiration", "")

            # Parse ISO 8601 expiry
            expires_at = time.time() + 3600  # default 1 hour
            if expiration_str:
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(
                        expiration_str.replace("Z", "+00:00")
                    )
                    expires_at = dt.timestamp()
                except Exception:
                    pass

            self._token = token
            self._token_expires = expires_at
            logger.debug(
                "Refreshed Copilot token for '%s', expires in %.0fs",
                self.account_name,
                expires_at - time.time(),
            )
            return self._token

    # ──── Request helpers ──────────────────────────────────────────────────────

    def _base_headers(self) -> Dict[str, str]:
        """Build base headers for Copilot API calls.

        Returns:
            Header dict with Authorization, integration-id, api-version, user-agent.
        """
        token = self._get_token()
        return {
            "Authorization": f"GitHub-Bearer {token}",
            "copilot-integration-id": _INTEGRATION_ID,
            "x-github-api-version": _API_VERSION,
            "user-agent": _USER_AGENT,
            "origin": "https://github.com",
            "referer": "https://github.com/copilot",
            "accept": "application/json",
            "content-type": "application/json",
        }

    # ──── Models ──────────────────────────────────────────────────────────────

    def list_models(self) -> List[Dict[str, Any]]:
        """List all available Copilot models (cached for 6 hours).

        Returns:
            List of model dicts from the API, each containing at least ``id``.
        """
        now = time.time()
        if self._models_cache and now - self._models_cache_time < _MODELS_CACHE_TTL:
            return self._models_cache

        headers = self._base_headers()
        resp = requests.get(f"{_API_BASE}/models", headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        models = data.get("data", data if isinstance(data, list) else [])
        self._models_cache = models
        self._models_cache_time = now
        logger.debug("Fetched %d Copilot models", len(models))
        return models

    # ──── Threads ─────────────────────────────────────────────────────────────

    def create_thread(self) -> str:
        """Create a new Copilot chat thread.

        Returns:
            The UUID thread_id string.

        Raises:
            RuntimeError: If thread creation fails.
        """
        headers = self._base_headers()
        resp = requests.post(
            f"{_API_BASE}/github/chat/threads",
            headers=headers,
            json={},
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"create_thread returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        thread_id = data.get("thread_id") or data.get("thread", {}).get("id", "")
        if not thread_id:
            raise RuntimeError(f"No thread_id in response: {data}")
        logger.debug("Created Copilot thread: %s", thread_id)
        return thread_id

    # ──── Send message ────────────────────────────────────────────────────────

    def send_message(
        self,
        thread_id: str,
        content: str,
        model: str = "claude-sonnet-4.6",
        parent_message_id: str = "root",
    ) -> Tuple[str, str]:
        """Send a message to a thread and stream the response.

        Args:
            thread_id: Thread to post to.
            content: User message text.
            model: Copilot model ID.
            parent_message_id: Parent message ID for threading (``"root"`` for first).

        Returns:
            Tuple of (response_text, message_id).

        Raises:
            RuntimeError: If the API returns a non-2xx status.
        """
        response_message_id = str(uuid.uuid4())
        payload = {
            "responseMessageID": response_message_id,
            "content": content,
            "intent": "conversation",
            "references": [],
            "context": [],
            "currentURL": "https://github.com/copilot",
            "streaming": True,
            "confirmations": [],
            "customInstructions": [],
            "model": model,
            "mode": "immersive",
            "parentMessageID": parent_message_id,
            "mediaContent": [],
            "skillOptions": {"deepCodeSearch": False},
            "requestTrace": False,
        }

        headers = self._base_headers()
        headers["content-type"] = "text/event-stream"
        # Accept SSE
        headers["accept"] = "text/event-stream, text/event-stream"

        url = f"{_API_BASE}/github/chat/threads/{thread_id}/messages"

        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=120,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"send_message returned {resp.status_code}: {resp.text[:200]}"
            )

        full_text = ""
        final_message_id = response_message_id

        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            # SSE format: lines starting with "data: "
            if raw_line.startswith("data: "):
                chunk_str = raw_line[6:]
                if chunk_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_str)
                    chunk_type = chunk.get("type", "")
                    if chunk_type == "content":
                        full_text += chunk.get("body", "")
                    elif chunk_type == "complete":
                        final_message_id = chunk.get("id", final_message_id)
                        # May also contain body text
                        body = chunk.get("body", "")
                        if body and not full_text:
                            full_text = body
                except json.JSONDecodeError:
                    pass

        return full_text, final_message_id

    # ──── High-level helpers ──────────────────────────────────────────────────

    def ask(
        self,
        prompt: str,
        model: str = "claude-sonnet-4.6",
    ) -> str:
        """Create a thread, send a prompt, return the response.

        Args:
            prompt: Question or instruction.
            model: Copilot model ID.

        Returns:
            Full response text from the model.
        """
        thread_id = self.create_thread()
        text, _ = self.send_message(thread_id, prompt, model=model)
        return text

    def embed(
        self,
        text: str,
        model: str = "text-embedding-3-small",
    ) -> List[float]:
        """Generate an embedding vector for text.

        Args:
            text: Input text to embed.
            model: Embedding model ID.

        Returns:
            List of floats representing the embedding.

        Raises:
            NotImplementedError: Copilot individual API does not expose an
                embeddings endpoint at this time. Use LMStudio or another provider.
        """
        raise NotImplementedError(
            "The Copilot individual API (/api.individual.githubcopilot.com) does not "
            "expose a dedicated embeddings endpoint. Use LMStudio "
            "(http://localhost:1234/v1/embeddings) or sentence-transformers instead."
        )


# ──── Singleton factory ───────────────────────────────────────────────────────


def get_copilot_client(account_name: str = "nihilistcod") -> GithubCopilotClient:
    """Get or create a GithubCopilotClient singleton per account_name.

    Args:
        account_name: Account identifier (maps to cookie storage).

    Returns:
        Shared GithubCopilotClient for that account.
    """
    with _instances_lock:
        if account_name not in _instances:
            _instances[account_name] = GithubCopilotClient(account_name)
        return _instances[account_name]
