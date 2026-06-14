"""
Gemini Context Cache Client — Reuse large prompts across API calls
==================================================================
Caches context.md + CLAUDE.md as a persistent Gemini context prefix.
Every subsequent Gemini call can reference this cache instead of
re-sending 50K+ tokens, saving time and tokens.

Version: v1.57.0 [2026-03-26]
Author:  CosySim Team

Usage:
    from engine.integrations.context_cache_client import get_context_cache

    cache = get_context_cache()
    cache_name = cache.ensure_project_context()  # creates or reuses
    answer = cache.generate_with_context("What is the interceptor pipeline?")

Change Log:
    v1.57.0 [2026-03-26] — Initial implementation: create/reuse caches,
                           project context auto-loading, generate with cache,
                           structured output support, singleton accessor
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ──── Context Cache Client ────────────────────────────────────────────────

class ContextCacheClient:
    """Gemini Context Caching — reuse large project context across calls.

    Wraps the google.genai SDK caching API. Caches large text blobs
    (context.md, CLAUDE.md, architecture docs) so subsequent generation
    calls skip re-processing those tokens.

    Args:
        api_key: Google AI Studio API key. Falls back to aistudio_client keys.
        model: Gemini model name (must support caching).
    """

    # v1.57.0 [2026-03-26] — Core class with cache lifecycle management
    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash"):
        from google import genai

        if not api_key:
            from engine.integrations.aistudio_client import API_KEYS
            api_key = API_KEYS[0]

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._cache_name: Optional[str] = None
        self._cache_expires: float = 0.0
        self._ttl_seconds = 3600  # 1 hour default

    # ──── Cache Lifecycle ─────────────────────────────────────────────

    def create_cache(self, content: str, ttl_seconds: int = 3600) -> str:
        """Create a new context cache from raw text.

        Args:
            content: The text to cache (must be large enough for Gemini
                     to accept — typically 32K+ characters).
            ttl_seconds: Time-to-live in seconds (default 1 hour).

        Returns:
            Cache name string (e.g. "cachedContents/wdbnkwrttw559...").
        """
        from google.genai import types

        cache = self._client.caches.create(
            model=self._model,
            config=types.CreateCachedContentConfig(
                contents=[types.Content(
                    role="user",
                    parts=[types.Part(text=content)],
                )],
                ttl=f"{ttl_seconds}s",
            ),
        )
        self._cache_name = cache.name
        self._cache_expires = time.time() + ttl_seconds
        logger.info(
            "[ContextCache] Created: %s (ttl=%ds, operation=create_cache)",
            cache.name, ttl_seconds,
        )
        return cache.name

    def ensure_project_context(self, ttl_seconds: int = 3600) -> Optional[str]:
        """Create or reuse a cache with project context (context.md + CLAUDE.md).

        Reads project documentation files and caches them as a Gemini
        context prefix. If the cache is still valid (with 60s safety margin),
        returns the existing cache name without creating a new one.

        Args:
            ttl_seconds: Time-to-live in seconds for newly created caches.

        Returns:
            Cache name string, or None if no context files found or creation failed.
        """
        # Return existing if still valid (60s safety margin before expiry)
        if self._cache_name and time.time() < self._cache_expires - 60:
            return self._cache_name

        # Build context from project files
        context_parts: list[str] = []
        for filename in ["context.md", "CLAUDE.md"]:
            path = _PROJECT_ROOT / filename
            if path.exists():
                content = path.read_text(encoding="utf-8")
                context_parts.append(f"# {filename}\n\n{content}")

        if not context_parts:
            logger.warning(
                "[ContextCache] No project context files found (operation=ensure_project_context)"
            )
            return None

        full_context = "\n\n---\n\n".join(context_parts)

        # Gemini context cache requires minimum ~32K tokens worth of content.
        # If our core docs are too short, pad with additional architecture docs
        # so the cache creation doesn't get rejected by the API.
        if len(full_context) < 30000:
            for extra in ["docs/NEXUS_SYSTEM.md", "docs/ARCHITECTURE.md"]:
                path = _PROJECT_ROOT / extra
                if path.exists():
                    extra_content = path.read_text(encoding="utf-8")
                    full_context += f"\n\n---\n\n# {extra}\n\n{extra_content}"

        try:
            return self.create_cache(full_context, ttl_seconds)
        except Exception as exc:
            logger.warning(
                "[ContextCache] Failed to create project context cache "
                "(operation=ensure_project_context): %s", exc,
            )
            return None

    # ──── Generation with Cache ───────────────────────────────────────

    def generate_with_context(self, prompt: str, **kwargs: Any) -> str:
        """Generate content using the cached project context.

        If no cache exists or creation fails, falls back to direct generation
        without caching (still works, just uses more tokens).

        Args:
            prompt: The user query to send after the cached context.
            **kwargs: Additional keyword arguments (reserved for future use).

        Returns:
            Generated text response.

        CONNECTS: aistudio_client (API keys), project context files
        CALLED BY: Nexus query pipeline, CLI tools, any module needing
                   project-aware Gemini answers
        """
        from google.genai import types

        cache_name = self.ensure_project_context()

        if not cache_name:
            # Fallback: direct generation without cache
            result = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            return result.text or ""

        result = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                cached_content=cache_name,
            ),
        )
        return result.text or ""

    def generate_structured_with_context(
        self, prompt: str, schema: dict
    ) -> Any:
        """Generate structured (JSON) output using cached project context.

        Uses Gemini's controlled generation to enforce a JSON schema on
        the response. The cached context provides project knowledge, the
        prompt asks the question, and the schema shapes the answer.

        Args:
            prompt: The user query.
            schema: JSON Schema dict defining the expected response shape.

        Returns:
            Parsed JSON object matching the provided schema.
        """
        from google.genai import types

        cache_name = self.ensure_project_context()

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        if cache_name:
            config.cached_content = cache_name

        result = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        return json.loads(result.text)

    # ──── Status / Introspection ──────────────────────────────────────

    @property
    def is_cached(self) -> bool:
        """True if a valid (non-expired) cache exists."""
        return bool(self._cache_name and time.time() < self._cache_expires)

    def status(self) -> Dict[str, Any]:
        """Return cache status for diagnostics / Oracle."""
        return {
            "cached": self.is_cached,
            "cache_name": self._cache_name or "",
            "expires_in_s": max(0, self._cache_expires - time.time()) if self._cache_name else 0,
            "model": self._model,
        }


# ──── Singleton ───────────────────────────────────────────────────────

_cache: Optional[ContextCacheClient] = None


def get_context_cache() -> ContextCacheClient:
    """Return the singleton ContextCacheClient instance.

    Lazily creates the client on first call. Uses the default API key
    from aistudio_client and gemini-2.5-flash model.
    """
    global _cache
    if _cache is None:
        _cache = ContextCacheClient()
    return _cache
