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

    # ──── SDK gap methods (ARGUS audit — 17 GEMINI_RPCIDS) ────────────────────

    def get_feature_flags(
        self,
        flag_ids: Optional[list[int]] = None,
    ) -> dict[int, Any]:
        """Probe Gemini feature flag values (rpcid: ozz5Z).

        Returns a dict of {flag_id: value}. Useful for discovering hidden
        features and A/B tests in the Gemini frontend.

        Args:
            flag_ids: List of integer flag IDs to probe. If None, probes the
                default set discovered in HAR captures: [447, 448, 702, 960, 961, 1062].

        Returns:
            Dict mapping flag_id → value.
        """
        if flag_ids is None:
            flag_ids = [447, 448, 702, 960, 961, 1062]
        payload = json.dumps([[[None, "1", fid]] for fid in flag_ids])
        results = self._call("ozz5Z", payload)
        flags: dict[int, Any] = {}
        try:
            for i, item in enumerate(results[0]):
                flag_id = flag_ids[i] if i < len(flag_ids) else i
                flags[flag_id] = item
        except (IndexError, TypeError):
            pass
        return flags

    def get_locale_preferences(self) -> dict[str, str]:
        """Return user locale and regional preferences (rpcid: DYBcR).

        Returns:
            Dict with locale, language, region strings.
        """
        payload = json.dumps([self._locale])
        results = self._call("DYBcR", payload)
        try:
            raw = results[0] if results else None
            if raw is None:
                return {"locale": self._locale}
            # Unwrap one level of list nesting
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                return raw[0]
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {"locale": str(raw[0]) if raw else self._locale}
        except (IndexError, TypeError):
            pass
        return {"locale": self._locale}

    def proxy_unary_call(
        self,
        service: str,
        method: str,
        request_body: Any,
    ) -> dict[str, Any]:
        """Proxy a gRPC unary call through Gemini (rpcid: boaYGb).

        Used by the Gemini frontend to call internal Google services.
        Returns a thoughtSignature for grounding.

        Args:
            service: Target gRPC service name.
            method: Method name on the service.
            request_body: Proto-JSON request body.

        Returns:
            Dict with thought_signature, response data.
        """
        payload = json.dumps([service, method, request_body])
        results = self._call("boaYGb", payload)
        try:
            raw = results[0]
            if isinstance(raw, list) and len(raw) >= 2:
                return {"thought_signature": raw[0], "response": raw[1]}
            return {"raw": raw}
        except (IndexError, TypeError):
            return {}

    def generate_content(
        self,
        prompt: str,
        model: str = "gemini-2.0-flash",
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
    ) -> str:
        """Generate content via Gemini AI (rpcid: jKHnxe).

        Args:
            prompt: User prompt text.
            model: Gemini model ID.
            system_instruction: Optional system instruction.
            temperature: Sampling temperature (0.0–2.0).

        Returns:
            Generated text string.
        """
        payload = json.dumps([
            prompt,
            model,
            system_instruction,
            [[temperature]],
        ])
        results = self._call("jKHnxe", payload)
        try:
            return str(results[0][0]) if results else ""
        except (IndexError, TypeError):
            return ""

    def stream_generate_content(
        self,
        prompt: str,
        model: str = "gemini-2.0-flash",
    ) -> str:
        """Stream generate content (rpcid: r7Bvze).

        Same as generate_content but uses the streaming rpcid.
        Response is collected and returned as a single string.

        Args:
            prompt: User prompt text.
            model: Gemini model ID.

        Returns:
            Complete generated text string.
        """
        payload = json.dumps([prompt, model])
        results = self._call("r7Bvze", payload)
        chunks: list[str] = []
        try:
            for item in results:
                if isinstance(item, list) and item:
                    chunks.append(str(item[0]))
        except (IndexError, TypeError):
            pass
        return "".join(chunks)

    def count_tokens(self, text: str, model: str = "gemini-2.0-flash") -> int:
        """Count tokens for a text string (rpcid: mMEAEd).

        Args:
            text: Text to tokenise.
            model: Model to use for tokenisation.

        Returns:
            Token count integer.
        """
        payload = json.dumps([text, model])
        results = self._call("mMEAEd", payload)
        try:
            return int(results[0][0])
        except (IndexError, TypeError, ValueError):
            return 0

    def list_models(self) -> list[dict[str, Any]]:
        """List available Gemini models (rpcid: k9yDXd).

        Different from ``get_models()`` (rpcid: otAQ7b) — this returns
        the full model registry with capabilities.

        Returns:
            List of model dicts with id, display_name, capabilities.
        """
        results = self._call("k9yDXd", "[]")
        models: list[dict[str, Any]] = []
        try:
            for item in results[0]:
                if isinstance(item, list):
                    models.append({
                        "id": item[0] if item else "",
                        "display_name": item[1] if len(item) > 1 else "",
                        "raw": item,
                    })
        except (IndexError, TypeError):
            pass
        return models

    def get_model(self, model_id: str) -> dict[str, Any]:
        """Get metadata for a specific Gemini model (rpcid: XqsOBb).

        Args:
            model_id: Model identifier string (e.g. ``'gemini-2.0-flash'``).

        Returns:
            Model metadata dict.
        """
        payload = json.dumps([model_id])
        results = self._call("XqsOBb", payload)
        try:
            raw = results[0]
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {"id": model_id, "raw": raw}
        except (IndexError, TypeError):
            pass
        return {"id": model_id}

    def create_file(
        self,
        file_data: bytes,
        mime_type: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        """Upload a file to Gemini Files API (rpcid: BgXnQc).

        Args:
            file_data: Raw file bytes.
            mime_type: MIME type (e.g. ``'image/png'``).
            display_name: Human-readable name for the file.

        Returns:
            Dict with file_id, uri, state, expiry_time.
        """
        import base64
        b64 = base64.b64encode(file_data).decode("ascii")
        payload = json.dumps([b64, mime_type, display_name])
        results = self._call("BgXnQc", payload)
        try:
            raw = results[0]
            if isinstance(raw, list) and len(raw) >= 2:
                return {"file_id": raw[0], "uri": raw[1], "state": raw[2] if len(raw) > 2 else ""}
            return {"raw": raw}
        except (IndexError, TypeError):
            return {}

    def list_files(self) -> list[dict[str, Any]]:
        """List uploaded files in the Files API (rpcid: mfvMVb).

        Returns:
            List of file dicts with id, uri, display_name, mime_type, state.
        """
        results = self._call("mfvMVb", "[]")
        files: list[dict[str, Any]] = []
        try:
            for item in results[0]:
                if isinstance(item, list):
                    files.append({
                        "id": item[0] if item else "",
                        "uri": item[1] if len(item) > 1 else "",
                        "display_name": item[2] if len(item) > 2 else "",
                        "mime_type": item[3] if len(item) > 3 else "",
                        "state": item[4] if len(item) > 4 else "",
                    })
        except (IndexError, TypeError):
            pass
        return files

    def delete_file(self, file_id: str) -> bool:
        """Delete an uploaded file (rpcid: qVSQ5c).

        Args:
            file_id: File ID from create_file or list_files.

        Returns:
            True if the call was made without error.
        """
        payload = json.dumps([file_id])
        results = self._call("qVSQ5c", payload)
        return results is not None

    def get_file(self, file_id: str) -> dict[str, Any]:
        """Get metadata for an uploaded file (rpcid: ozVbQb).

        Args:
            file_id: File ID.

        Returns:
            File metadata dict.
        """
        payload = json.dumps([file_id])
        results = self._call("ozVbQb", payload)
        try:
            raw = results[0]
            if isinstance(raw, list) and len(raw) >= 2:
                return {"id": file_id, "uri": raw[1], "raw": raw}
            if isinstance(raw, dict):
                return raw
        except (IndexError, TypeError):
            pass
        return {"id": file_id}

    def create_cached_content(
        self,
        content: str,
        model: str = "gemini-2.0-flash",
        ttl_seconds: int = 3600,
        display_name: str = "",
    ) -> dict[str, Any]:
        """Create a cached content entry (rpcid: VUBhEd).

        Cache large context (up to 1M tokens) so it isn't re-encoded on
        every call. The cache_id is passed as ``cachedContent`` in future
        generate calls to reduce token usage significantly.

        Args:
            content: Text content to cache.
            model: Model for which to cache the content.
            ttl_seconds: Time-to-live in seconds.
            display_name: Human-readable label.

        Returns:
            Dict with cache_id, name, expiry_time.
        """
        payload = json.dumps([content, model, ttl_seconds, display_name])
        results = self._call("VUBhEd", payload)
        try:
            raw = results[0]
            if isinstance(raw, list) and len(raw) >= 1:
                return {"cache_id": raw[0], "name": display_name, "raw": raw}
            if isinstance(raw, dict):
                return raw
        except (IndexError, TypeError):
            pass
        return {}

    def list_cached_contents(self) -> list[dict[str, Any]]:
        """List all cached content entries (rpcid: dXH9nb).

        Returns:
            List of cache dicts with cache_id, name, expiry_time, model.
        """
        results = self._call("dXH9nb", "[]")
        caches: list[dict[str, Any]] = []
        try:
            for item in results[0]:
                if isinstance(item, list):
                    caches.append({
                        "cache_id": item[0] if item else "",
                        "name": item[1] if len(item) > 1 else "",
                        "model": item[2] if len(item) > 2 else "",
                        "expiry_time": item[3] if len(item) > 3 else 0,
                    })
        except (IndexError, TypeError):
            pass
        return caches

    def delete_cached_content(self, cache_id: str) -> bool:
        """Delete a cached content entry (rpcid: sPOurf).

        Args:
            cache_id: Cache ID from create_cached_content.

        Returns:
            True if the call was made without error.
        """
        payload = json.dumps([cache_id])
        results = self._call("sPOurf", payload)
        return results is not None

    def get_cached_content(self, cache_id: str) -> dict[str, Any]:
        """Get metadata for a cached content entry (rpcid: jPv1oc).

        Args:
            cache_id: Cache ID.

        Returns:
            Cache metadata dict with cache_id, model, token_count, expiry_time.
        """
        payload = json.dumps([cache_id])
        results = self._call("jPv1oc", payload)
        try:
            raw = results[0]
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {
                    "cache_id": cache_id,
                    "model": raw[0] if raw else "",
                    "token_count": raw[1] if len(raw) > 1 else 0,
                    "expiry_time": raw[2] if len(raw) > 2 else 0,
                }
        except (IndexError, TypeError):
            pass
        return {"cache_id": cache_id}


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
