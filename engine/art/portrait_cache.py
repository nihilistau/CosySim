"""portrait_cache.py — In-process portrait URL cache for instant lookups.

The :class:`PortraitCache` singleton holds a mapping of
``(char_id, mood)`` → image URL that is populated at scene start by
:func:`~engine.skills.builtin.art_skills.batch_generate_portraits` and
updated any time a portrait is successfully generated.

The cache is used by the ``character_speaking`` socket event emitter so that
portrait images can be included in the real-time payload without triggering
a synchronous ComfyUI round-trip on every line of dialogue.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PortraitCache:
    """Thread-safe in-memory map of ``(char_id, mood)`` → image URL.

    URLs survive only for the life of the process; they are repopulated from
    ComfyUI / Nexus on the next scene start.
    """

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], str] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_url(self, char_id: str, mood: str, url: str) -> None:
        """Store *url* for ``(char_id, mood)``.

        Args:
            char_id: Character identifier.
            mood: Mood key (e.g. ``"neutral"``, ``"happy"``).
            url: Absolute URL or path to the portrait image.
        """
        if not url or url == "/static/img/placeholder.png":
            return  # Don't cache placeholder — keeps cache clean.
        with self._lock:
            self._store[(char_id.lower(), mood.lower())] = url
        logger.debug("PortraitCache: stored %s/%s → %s", char_id, mood, url[:60])

    def get_url(self, char_id: str, mood: str = "neutral") -> Optional[str]:
        """Return the portrait URL for ``(char_id, mood)``, or *None* if absent.

        Falls back to ``neutral`` mood if an exact mood match is not cached.

        Args:
            char_id: Character identifier.
            mood: Desired mood key.

        Returns:
            URL string, or ``None`` if no entry exists (not even neutral).
        """
        with self._lock:
            url = self._store.get((char_id.lower(), mood.lower()))
            if url is None:
                url = self._store.get((char_id.lower(), "neutral"))
            return url

    def get_all(self) -> Dict[str, str]:
        """Return a snapshot of all cached entries as ``"char_id:mood"`` → URL.

        Returns:
            Plain dictionary copy suitable for JSON serialisation.
        """
        with self._lock:
            return {f"{k[0]}:{k[1]}": v for k, v in self._store.items()}

    def clear(self) -> None:
        """Remove all cached entries (e.g. on scene teardown)."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── Singleton ─────────────────────────────────────────────────────────────────

_cache_instance: Optional[PortraitCache] = None
_cache_lock = threading.Lock()


def get_portrait_cache() -> PortraitCache:
    """Return the process-wide :class:`PortraitCache` singleton.

    Thread-safe; creates the instance on first call.

    Returns:
        The shared :class:`PortraitCache` instance.
    """
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = PortraitCache()
                logger.debug("PortraitCache singleton created")
    return _cache_instance
