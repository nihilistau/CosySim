"""Shared interceptor TTL cache and scene-routing constants."""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Set, Tuple


class _InterceptorCache:
    """Thread-safe TTL cache for interceptor pre-computed outputs.

    Keyed by ``(agent_id, interceptor_name)``.  Interceptors that produce
    the same output across multiple calls (e.g. character identity, skill
    list, personality reminders) can cache here to avoid re-computation.
    """

    def __init__(self, default_ttl: float = 60.0) -> None:
        self._lock = threading.Lock()
        self._store: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._default_ttl = default_ttl

    def get(self, agent_id: str, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get((agent_id, key))
            if entry is None:
                return None
            expiry, value = entry
            if time.time() > expiry:
                del self._store[(agent_id, key)]
                return None
            return value

    def set(self, agent_id: str, key: str, value: str, ttl: Optional[float] = None) -> None:
        with self._lock:
            self._store[(agent_id, key)] = (
                time.time() + (ttl or self._default_ttl),
                value,
            )

    def invalidate(self, agent_id: str, key: Optional[str] = None) -> None:
        """Invalidate cache for an agent. If key is None, invalidate all."""
        with self._lock:
            if key:
                self._store.pop((agent_id, key), None)
            else:
                self._store = {
                    k: v for k, v in self._store.items() if k[0] != agent_id
                }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


INTERCEPTOR_CACHE = _InterceptorCache(default_ttl=60.0)

# Scenes that have their own dedicated interceptors; UniversalSceneInterceptor skips these.
SCENES_WITH_DEDICATED_INTERCEPTOR: Set[str] = {"bedroom", "phone", "lounge", "gallery"}
