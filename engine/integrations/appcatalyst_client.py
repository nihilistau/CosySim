"""AppCatalyst client — Google's internal Gemini 3 model access API.

Reverse-engineered from labs.google.har (2026-07-14).  AppCatalyst
provides direct REST access to Gemini models including **Gemini 3 Flash
Preview** via simple API-key auth (no WIZ batchexecute transport).

All 9 endpoints from ``config/nlm_rpcids.yaml`` v6.0 ``appcatalyst``
section are implemented:
  - check_app_access, create_cached_content, execute_step
  - generate_webpage_stream, get_email_preferences, set_email_preferences
  - get_location, generate_content, stream_generate_content

Additional convenience methods (embed, embed_batch, generate_vision,
count_tokens, batch_generate, list_models, fine_tune_list,
fine_tune_status) are also provided.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_BASE_URL = "https://appcatalyst.pa.googleapis.com"
_BASE_PATH = "/v1beta1"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

_DEFAULT_MODEL = "gemini-3-flash-preview"
_DEFAULT_EMBED_MODEL = "text-embedding-004"


# ──── Client ─────────────────────────────────────────────────────────────────


class AppCatalystClient:
    """Client for Google AppCatalyst — direct Gemini 3 model access.

    Auth: API key loaded from SecretManager (``appcatalyst.api_key`` or
    ``google.api_key``), config, or the ``APPCATALYST_API_KEY`` / 
    ``GOOGLE_API_KEY`` environment variables.  Never hardcoded.

    Args:
        api_key: Explicit API key override (mainly for testing).
        config_override: Optional config dict for testing.
    """

    BASE_URL: str = _BASE_URL

    def __init__(
        self,
        api_key: Optional[str] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._cfg = config_override or {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})
        self._api_key: Optional[str] = api_key
        if not self._api_key:
            self._load_api_key()

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _load_api_key(self) -> None:
        """Load API key from SecretManager, config, or environment."""
        # 1. Try SecretManager
        try:
            from engine.integrations.secret_manager import get_secret
            key = get_secret("appcatalyst_api_key") or get_secret("google_api_key")
            if key:
                self._api_key = key
                logger.debug("AppCatalyst API key loaded from SecretManager")
                return
        except Exception as e:
            logger.debug("[AppCatalystClient] SecretManager key lookup failed (operation=load_api_key): %s", e)

        # 2. Try config
        try:
            cfg = get_config()
            key = (
                cfg.get("appcatalyst.api_key")
                or cfg.get("google.api_key")
                or cfg.get("google.gemini_api_key")
            )
            if key:
                self._api_key = key
                logger.debug("AppCatalyst API key loaded from config")
                return
        except Exception as e:
            logger.debug("[AppCatalystClient] Config key lookup failed (operation=load_api_key): %s", e)

        # 3. Environment variable
        import os
        key = os.environ.get("APPCATALYST_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            self._api_key = key
            logger.debug("AppCatalyst API key loaded from environment")

        if not self._api_key:
            logger.warning(
                "AppCatalyst: no API key found — requests will fail without auth"
            )

    def _get_headers(self) -> Dict[str, str]:
        """Build AppCatalyst REST request headers.

        Returns:
            Headers dict with Content-Type and optional X-Goog-Api-Key.
        """
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if self._api_key:
            headers["X-Goog-Api-Key"] = self._api_key
        return headers

    def _url(self, path: str) -> str:
        """Build a full AppCatalyst endpoint URL.

        Args:
            path: Path suffix (e.g. ``"/v1beta1/checkAppAccess"``).

        Returns:
            Full URL string.
        """
        return f"{self.BASE_URL}{path}"

    # ──── 9 Core Endpoints ────────────────────────────────────────────────────

    def check_app_access(self, app_id: str = "") -> Dict[str, Any]:
        """Check if the current user has access to an app or project.

        Endpoint: ``POST /v1beta1/checkAppAccess``

        Args:
            app_id: Optional application / project identifier.

        Returns:
            Dict with ``hasAccess`` boolean and optional metadata.
        """
        url = self._url(f"{_BASE_PATH}/checkAppAccess")
        body: Dict[str, Any] = {}
        if app_id:
            body["appId"] = app_id
        logger.debug("AppCatalyst check_app_access: app_id=%r", app_id)
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def create_cached_content(
        self,
        content: str,
        model: str = _DEFAULT_MODEL,
        ttl_seconds: int = 3600,
        display_name: str = "",
    ) -> Dict[str, Any]:
        """Create server-side cached content for reuse across requests.

        Endpoint: ``POST /v1beta1/cachedContents``

        Args:
            content: Text content to cache on the server.
            model: Model name to associate the cache entry with.
            ttl_seconds: Time-to-live for the cache entry.
            display_name: Human-readable label for the cached content.

        Returns:
            Dict with ``name`` (resource ID) and cache metadata.
        """
        url = self._url(f"{_BASE_PATH}/cachedContents")
        body: Dict[str, Any] = {
            "model": f"models/{model}",
            "contents": [{"parts": [{"text": content}], "role": "user"}],
            "ttl": f"{ttl_seconds}s",
        }
        if display_name:
            body["displayName"] = display_name
        logger.info(
            "AppCatalyst create_cached_content: model=%s ttl=%ds", model, ttl_seconds
        )
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def execute_step(
        self,
        step_name: str,
        inputs: Optional[Dict[str, Any]] = None,
        app_id: str = "",
    ) -> Dict[str, Any]:
        """Execute a single step in an AppCatalyst agent workflow.

        Endpoint: ``POST /v1beta1/executeStep``

        Args:
            step_name: Name of the workflow step to execute.
            inputs: Input parameters for the step.
            app_id: Optional app / project identifier.

        Returns:
            Step execution result dict.
        """
        url = self._url(f"{_BASE_PATH}/executeStep")
        body: Dict[str, Any] = {"stepName": step_name, "inputs": inputs or {}}
        if app_id:
            body["appId"] = app_id
        logger.info("AppCatalyst execute_step: step=%s", step_name)
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def generate_webpage_stream(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        context: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        """Generate webpage content via SSE streaming.

        Endpoint: ``POST /v1beta1/generateWebpageStream``

        Args:
            prompt: Text prompt for webpage generation.
            model: Model to use.
            context: Optional context dict for the generation.

        Yields:
            Incremental text chunks from the SSE stream.
        """
        url = self._url(f"{_BASE_PATH}/generateWebpageStream")
        body: Dict[str, Any] = {
            "prompt": prompt,
            "model": f"models/{model}",
        }
        if context:
            body["context"] = context
        logger.info("AppCatalyst generate_webpage_stream: model=%s", model)
        headers = self._get_headers()
        headers["Accept"] = "text/event-stream"
        with self._session.post(
            url, headers=headers, json=body, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        text = (
                            data.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "")
                        )
                        if text:
                            yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        yield chunk

    def get_email_preferences(self) -> Dict[str, Any]:
        """Get email notification preferences for the authenticated user.

        Endpoint: ``GET /v1beta1/getEmailPreferences``

        Returns:
            Dict of email preference settings.
        """
        url = self._url(f"{_BASE_PATH}/getEmailPreferences")
        logger.debug("AppCatalyst get_email_preferences")
        resp = self._session.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def set_email_preferences(
        self, preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update email notification preferences.

        Endpoint: ``POST /v1beta1/setEmailPreferences``

        Args:
            preferences: Dict of preference key-value pairs to set.

        Returns:
            Updated preferences dict.
        """
        url = self._url(f"{_BASE_PATH}/setEmailPreferences")
        logger.info("AppCatalyst set_email_preferences: keys=%s", list(preferences))
        resp = self._session.post(
            url, headers=self._get_headers(), json=preferences, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def get_location(self) -> Dict[str, Any]:
        """Get the user's current location context.

        Endpoint: ``GET /v1beta1/getLocation``

        Returns:
            Dict with location context (region, country, etc.).
        """
        url = self._url(f"{_BASE_PATH}/getLocation")
        logger.debug("AppCatalyst get_location")
        resp = self._session.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ──── Inference: generate (non-streaming) ─────────────────────────────────

    def generate(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
    ) -> Dict[str, Any]:
        """Direct model inference — non-streaming.

        Endpoint: ``POST /v1beta1/models/{model}:generateContent``

        Args:
            prompt: User prompt text.
            model: Model identifier (e.g. ``"gemini-3-flash-preview"``).
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum output tokens.
            system_prompt: Optional system-level instruction.

        Returns:
            Dict with ``text`` (extracted response) and full ``response`` body.
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:generateContent")
        body = self._build_generate_body(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        logger.info(
            "AppCatalyst generate: model=%s temp=%.2f max_tokens=%d",
            model,
            temperature,
            max_tokens,
        )
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        text = self._extract_text(data)
        return {"text": text, "model": model, "response": data}

    def generate_stream(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
    ) -> Iterator[str]:
        """Direct model inference — SSE streaming.

        Endpoint: ``POST /v1beta1/models/{model}:streamGenerateContent``

        Args:
            prompt: User prompt text.
            model: Model identifier.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            system_prompt: Optional system instruction.

        Yields:
            Incremental text chunks as they arrive.
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:streamGenerateContent")
        body = self._build_generate_body(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        logger.info("AppCatalyst generate_stream: model=%s", model)
        headers = self._get_headers()
        headers["Accept"] = "text/event-stream"
        with self._session.post(
            url, headers=headers, json=body, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        text = self._extract_text(data)
                        if text:
                            yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass

    # ──── Inference: vision (multimodal) ──────────────────────────────────────

    def generate_vision(
        self,
        prompt: str,
        image_b64: str,
        model: str = _DEFAULT_MODEL,
        mime_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """Multimodal vision inference with base64-encoded image.

        Args:
            prompt: Text prompt.
            image_b64: Base64-encoded image bytes.
            model: Model identifier (must support vision).
            mime_type: MIME type of the image (default ``"image/jpeg"``).

        Returns:
            Dict with ``text`` (extracted response) and full ``response`` body.
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:generateContent")
        body: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": image_b64,
                            }
                        },
                    ],
                    "role": "user",
                }
            ],
            "generationConfig": {"maxOutputTokens": 2048},
        }
        logger.info("AppCatalyst generate_vision: model=%s mime=%s", model, mime_type)
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return {"text": self._extract_text(data), "model": model, "response": data}

    # ──── Embeddings ──────────────────────────────────────────────────────────

    def embed(
        self,
        text: str,
        model: str = _DEFAULT_EMBED_MODEL,
    ) -> List[float]:
        """Get a text embedding vector.

        Args:
            text: Input text to embed.
            model: Embedding model identifier.

        Returns:
            List of float embedding values.
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:embedContent")
        body: Dict[str, Any] = {
            "content": {"parts": [{"text": text}]},
            "model": f"models/{model}",
        }
        logger.debug("AppCatalyst embed: model=%s text_len=%d", model, len(text))
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding", {}).get("values", [])

    def embed_batch(
        self,
        texts: List[str],
        model: str = _DEFAULT_EMBED_MODEL,
    ) -> List[List[float]]:
        """Get embedding vectors for a batch of texts.

        Args:
            texts: List of input strings.
            model: Embedding model identifier.

        Returns:
            List of embedding vectors (one per input text).
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:batchEmbedContents")
        body: Dict[str, Any] = {
            "requests": [
                {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": t}]},
                }
                for t in texts
            ]
        }
        logger.debug("AppCatalyst embed_batch: model=%s count=%d", model, len(texts))
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return [
            item.get("embedding", {}).get("values", [])
            for item in data.get("embeddings", [])
        ]

    # ──── Utility endpoints ───────────────────────────────────────────────────

    def list_models(self) -> List[Dict[str, Any]]:
        """List all available AppCatalyst models.

        Returns:
            List of model info dicts with ``name``, ``displayName``, etc.
        """
        url = self._url(f"{_BASE_PATH}/models")
        logger.debug("AppCatalyst list_models")
        resp = self._session.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])

    def count_tokens(
        self,
        prompt: str,
        model: str = _DEFAULT_MODEL,
    ) -> Dict[str, Any]:
        """Count the number of tokens in a prompt without running inference.

        Args:
            prompt: Text to count tokens for.
            model: Model whose tokeniser to use.

        Returns:
            Dict with ``totalTokens`` count.
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:countTokens")
        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}]
        }
        logger.debug("AppCatalyst count_tokens: model=%s", model)
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def batch_generate(
        self,
        prompts: List[str],
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> List[Dict[str, Any]]:
        """Run inference on multiple prompts in a single request.

        Args:
            prompts: List of prompt strings.
            model: Model identifier.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens per prompt.

        Returns:
            List of result dicts (same shape as ``generate()``).
        """
        url = self._url(f"{_BASE_PATH}/models/{model}:batchGenerateContent")
        body: Dict[str, Any] = {
            "requests": [
                self._build_generate_body(
                    prompt=p,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                for p in prompts
            ]
        }
        logger.info(
            "AppCatalyst batch_generate: model=%s count=%d", model, len(prompts)
        )
        resp = self._session.post(url, headers=self._get_headers(), json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        results: List[Dict[str, Any]] = []
        for item in data.get("responses", []):
            results.append(
                {"text": self._extract_text(item), "model": model, "response": item}
            )
        return results

    def fine_tune_list(self) -> List[Dict[str, Any]]:
        """List fine-tuning jobs for the current project.

        Returns:
            List of fine-tuning job dicts.
        """
        url = self._url(f"{_BASE_PATH}/tunedModels")
        logger.debug("AppCatalyst fine_tune_list")
        resp = self._session.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("tunedModels", [])

    def fine_tune_status(self, job_id: str) -> Dict[str, Any]:
        """Get the status of a fine-tuning job.

        Args:
            job_id: Fine-tuning job / tuned model identifier.

        Returns:
            Dict with job state, progress, and metadata.
        """
        url = self._url(f"{_BASE_PATH}/tunedModels/{job_id}")
        logger.debug("AppCatalyst fine_tune_status: job_id=%s", job_id)
        resp = self._session.get(url, headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ──── Helpers ─────────────────────────────────────────────────────────────

    def _build_generate_body(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
    ) -> Dict[str, Any]:
        """Build the request body for a generateContent call.

        Args:
            prompt: User prompt text.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            system_prompt: Optional system instruction.

        Returns:
            Request body dict.
        """
        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        return body

    def _extract_text(self, response: Dict[str, Any]) -> str:
        """Extract plain text from a generateContent response.

        Args:
            response: Parsed JSON response dict.

        Returns:
            Concatenated text from all parts, or empty string.
        """
        try:
            parts = (
                response.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            return "".join(p.get("text", "") for p in parts)
        except (IndexError, AttributeError, TypeError):
            return ""


# ──── Module-level convenience ────────────────────────────────────────────────

_appcatalyst_instance: Optional[AppCatalystClient] = None


def get_appcatalyst_client() -> AppCatalystClient:
    """Return a shared AppCatalystClient singleton.

    Returns:
        The module-level AppCatalystClient instance.
    """
    global _appcatalyst_instance
    if _appcatalyst_instance is None:
        _appcatalyst_instance = AppCatalystClient()
    return _appcatalyst_instance


def reset_appcatalyst_client() -> None:
    """Reset the singleton (for testing)."""
    global _appcatalyst_instance
    _appcatalyst_instance = None
