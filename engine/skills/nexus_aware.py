"""NexusAwareSkillMixin — Nexus-first lookup pattern for skills.

Skills that use this mixin check the Nexus knowledge cache before making
expensive LLM calls.  Over time, accumulated answers reduce LLM usage.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)


class NexusAwareSkillMixin:
    """Mixin that adds Nexus-first lookup to skill classes.

    Usage::

        class MySkillSet(NexusAwareSkillMixin):
            def answer_question(self, question: str) -> str:
                cached = self.nexus_lookup(question)
                if cached:
                    return cached
                result = lms_call(question)
                self.nexus_store(question, result)
                return result
    """

    def nexus_lookup(self, query: str, min_confidence: float = 0.6) -> Optional[str]:
        """Search Nexus for a cached answer.

        Args:
            query: The question or lookup key.
            min_confidence: Minimum confidence threshold (0–1).

        Returns:
            Cached answer string, or None on miss / Nexus offline.
        """
        try:
            client = get_nexus_client()
            result = client.ask(query)
            if result and result.get("confidence", 0) >= min_confidence:
                logger.debug(
                    "Nexus cache hit: %s (%.2f)", query[:50], result.get("confidence", 0)
                )
                return result.get("answer")
        except Exception as exc:
            logger.debug("Nexus lookup failed (non-fatal): %s", exc)
        return None

    def nexus_store(self, question: str, answer: str, category: str = "skills") -> None:
        """Store a Q&A pair in Nexus for future cache hits.

        Args:
            question: The question / lookup key.
            answer: The answer to cache.
            category: Nexus category tag.
        """
        try:
            client = get_nexus_client()
            client.add_qa(question, answer, category=category)
            logger.debug("Nexus stored Q&A: %s", question[:50])
        except Exception as exc:
            logger.debug("Nexus store failed (non-fatal): %s", exc)


def nexus_aware(func: Callable) -> Callable:
    """Decorator that wraps a skill function with Nexus-first lookup.

    On each call the decorator builds a cache key from the function name and
    positional arguments, queries Nexus, and returns the cached answer when
    the confidence is sufficient — skipping the inner function entirely.
    Results from cache misses are stored back to Nexus automatically.

    Usage::

        @nexus_aware
        @skill(pack="lore", description="...")
        def explain_faction(faction_id: str) -> str:
            # Only reached on cache miss
            return expensive_lms_call(faction_id)
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = f"{getattr(func, '__name__', repr(func))}:{':'.join(str(a) for a in args)}"

        # ── Tier 1: Nexus cache lookup ───────────────────────────────────
        try:
            client = get_nexus_client()
            cached = client.ask(key)
            if cached and cached.get("confidence", 0) >= 0.6:
                logger.debug("@nexus_aware cache hit: %s", key[:60])
                return cached["answer"]
        except Exception:
            pass

        # ── Tier 2: actual function call ─────────────────────────────────
        result = func(*args, **kwargs)

        # ── Store result for future hits ─────────────────────────────────
        try:
            client = get_nexus_client()
            client.add_qa(key, str(result))
        except Exception:
            pass

        return result

    return wrapper
