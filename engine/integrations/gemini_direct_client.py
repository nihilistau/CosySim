"""Gemini BardChatUi client — reverse-engineered batchexecute API.

Derived from HAR + V8 heap analysis (March 2026).
Same batchexecute protocol as NotebookLM.
See docs/GEMINI_API_REFERENCE.md for full protocol spec.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

BATCHEXECUTE_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
STREAM_GENERATE_URL = (
    "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
)
RESPONSE_PREFIX = ")]}'\n"


def _parse_batchexecute(text: str) -> list[Any]:
    """Strip )]}' prefix and parse streaming wrb.fr frames."""
    results = []
    if text.startswith(RESPONSE_PREFIX):
        text = text[len(RESPONSE_PREFIX):]
    for match in re.finditer(r'\[\[\[.*?"wrb\.fr".*?\]\]', text, re.DOTALL):
        try:
            frame = json.loads(match.group())
            if frame and frame[0] and len(frame[0]) > 2:
                inner = frame[0][2]
                if inner:
                    results.append(json.loads(inner))
        except (json.JSONDecodeError, IndexError):
            continue
    return results


class GeminiDirectClient:
    """Programmatic Gemini access via reverse-engineered BardChatUi batchexecute API.

    Args:
        cookies: Dict of Google session cookies (SAPISID, SID, etc.)
        locale: Locale string (default: en-AU)
    """

    def __init__(self, cookies: dict[str, str], locale: str = "en-AU") -> None:
        self._cookies = cookies
        self._locale = locale
        self._session = requests.Session()
        self._session.cookies.update(cookies)
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/",
        })

    # ──── Internal ────

    def _call(self, rpcid: str, payload: str) -> list[Any]:
        """Execute a batchexecute call."""
        f_req = json.dumps([[[rpcid, payload, None, "generic"]]])
        data = f"f.req={requests.utils.quote(f_req)}"
        try:
            resp = self._session.post(
                BATCHEXECUTE_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
            return _parse_batchexecute(resp.text)
        except Exception as exc:
            logger.error("Gemini batchexecute %s failed: %s", rpcid, exc)
            return []

    # ──── Public API ────

    def get_models(self) -> list[dict]:
        """Return available Gemini models (rpcid: otAQ7b).

        Returns:
            List of model dicts with id, display_name, etc.
        """
        results = self._call("otAQ7b", "[]")
        models = []
        try:
            for item in results[0][0]:
                if isinstance(item, list) and len(item) >= 2:
                    models.append({"id": item[0], "name": item[1]})
        except (IndexError, TypeError):
            pass
        return models

    def list_conversations(self) -> list[dict]:
        """Return all Gemini conversation history (rpcid: CNgdBe).

        Returns:
            List of dicts with conv_id, title, turn_count, system_prompt.
        """
        payload = json.dumps([1, [self._locale], 0])
        results = self._call("CNgdBe", payload)
        convs = []
        try:
            for item in results[0][2]:
                conv_id = item[0]
                meta = item[1]
                system_prompt = item[2] if len(item) > 2 else ""
                convs.append({
                    "id": conv_id,
                    "title": meta[0] if meta else "",
                    "turn_count": meta[12] if len(meta) > 12 else 0,
                    "system_prompt": system_prompt,
                })
        except (IndexError, TypeError):
            pass
        return convs

    def get_linked_notebooks(self) -> list[dict]:
        """Return all NotebookLM notebooks linked to this Gemini account (rpcid: NXpLKc).

        This is the Gemini↔NLM bridge — returns ALL NLM notebooks without
        needing separate NLM authentication.

        Returns:
            List of dicts with id, title, source_count, timestamp.
        """
        results = self._call("NXpLKc", "[]")
        notebooks = []
        try:
            for item in results[0][0]:
                nb_path = item[0]   # e.g. "notebooks/UUID"
                nb_id = nb_path.split("/")[-1] if "/" in nb_path else nb_path
                notebooks.append({
                    "id": nb_id,
                    "path": nb_path,
                    "title": item[1],
                    "timestamp": item[2][0] if item[2] else 0,
                    "source_count": item[3] if len(item) > 3 else 0,
                })
        except (IndexError, TypeError):
            pass
        return sorted(notebooks, key=lambda x: x["source_count"], reverse=True)

    def get_usage_quota(self) -> list[dict]:
        """Return usage quota info (rpcid: qpEbW).

        Returns:
            List of quota items with type, used, limit, remaining.
        """
        payload = json.dumps([[[1, 4], [6, 6], [1, 15]]])
        results = self._call("qpEbW", payload)
        quotas = []
        try:
            for item in results[0][0]:
                quotas.append({
                    "type": item[0],
                    "used": item[2],
                    "limit": item[4],
                    "remaining": item[5],
                })
        except (IndexError, TypeError):
            pass
        return quotas

    def get_starter_prompts(self) -> list[dict]:
        """Return localized example prompts (rpcid: ku4Jyf).

        Returns:
            List of dicts with title, prompt, categories.
        """
        payload = json.dumps([self._locale, None, None, None, 4, None, None, [2, 4, 7, 19], None, []])
        results = self._call("ku4Jyf", payload)
        prompts = []
        try:
            for item in results[0][0]:
                prompts.append({
                    "title": item[0],
                    "prompt": item[2],
                    "lang": item[3],
                    "categories": item[4],
                    "id": item[5],
                })
        except (IndexError, TypeError):
            pass
        return prompts

    def list_extensions(self) -> list[dict]:
        """Return enabled Gemini extensions (rpcid: cYRIkd).

        Returns:
            List of extension dicts with id, name, icon_url.
        """
        payload = json.dumps([self._locale])
        results = self._call("cYRIkd", payload)
        exts = []
        try:
            for item in results[0][0]:
                exts.append({
                    "id": item[0][0] if item[0] else "",
                    "name": item[1],
                    "icon": item[2],
                })
        except (IndexError, TypeError):
            pass
        return exts

    def get_user_settings(self, key: str = "bard_activity_enabled") -> Any:
        """Return a user setting value (rpcid: ESY5D).

        Args:
            key: Settings key string.

        Returns:
            Setting value.
        """
        payload = json.dumps([[[key]]])
        results = self._call("ESY5D", payload)
        try:
            return results[0][0][4]
        except (IndexError, TypeError):
            return None

    def get_user_location(self) -> dict:
        """Return approximate user location (rpcid: K4WWud).

        Returns:
            Dict with city and map metadata.
        """
        payload = json.dumps([[1], [self._locale]])
        results = self._call("K4WWud", payload)
        try:
            return {"city": results[0][0], "swml_key": results[0][1]}
        except (IndexError, TypeError):
            return {}

    def generate_session_token(self) -> Optional[str]:
        """Generate a signed session token (rpcid: MaZiqc).

        Returns:
            Base64 token string.
        """
        results = self._call("MaZiqc", "[13,null,[0,null,1]]")
        try:
            return results[0][1]
        except (IndexError, TypeError):
            return None

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation (rpcid: PCck7e).

        Args:
            conv_id: Conversation ID (with r_ prefix).

        Returns:
            True if deleted.
        """
        payload = json.dumps([conv_id])
        results = self._call("PCck7e", payload)
        return results is not None


# ──── Singleton ────

_client: Optional[GeminiDirectClient] = None


def get_gemini_client(cookies: Optional[dict] = None) -> GeminiDirectClient:
    """Get or create the singleton Gemini client.

    Args:
        cookies: Override cookies (uses pool if not provided).

    Returns:
        GeminiDirectClient instance.
    """
    global _client
    if _client is None or cookies:
        if cookies is None:
            try:
                from engine.integrations.google_account_pool import get_account_pool
                pool = get_account_pool()
                account = pool.get_best_account(["gemini", "notebooklm"])
                cookies = account.cookies if account else {}
            except Exception:
                cookies = {}
        _client = GeminiDirectClient(cookies)
    return _client
