"""User Profile Store — structured user knowledge extracted from conversations.

Maintains a persistent, structured profile of the user (Knack) derived from
conversation analysis, explicit preferences, and observed behaviour patterns.

The profile lives in the Nexus under the ``copilot/user_profile`` namespace
and is also cached locally for fast synchronous access.  All write operations
call ``merge()`` which merges new facts with existing data rather than
replacing it, so the profile accumulates over time.

Profile structure::

    {
        "name": "Knack",
        "technical_background": ["Python", "AI/ML", "Windows"],
        "projects": {"CosySim": {...}, ...},
        "preferences": {"coding_style": "surgical", ...},
        "facts": ["Has RTX 2060", "i9 NUC Beast Canyon", ...],
        "topics_of_interest": ["fine-tuning", "NLM", ...],
        "conversation_count": 42,
        "last_updated": "2026-03-01T10:14:47Z"
    }

Usage::

    from engine.nexus.user_profile import get_user_profile_store
    store = get_user_profile_store()

    # Read
    profile = store.get_profile()
    print(profile["name"])

    # Merge new observations
    store.merge({
        "technical_background": ["Rust"],
        "facts": ["Uses VS Code as primary editor"],
    })

    # Quick fact lookup
    store.add_fact("Prefers dark mode")
    store.add_preference("output_verbosity", "concise")

MCP tools::

    user_profile_get()       — return full profile
    user_profile_update(data) — merge new data into profile
    user_profile_facts()     — list all known facts
"""
from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_PROFILE_NEXUS_KEY = "copilot/user_profile"
_PROFILE_CATEGORY = "copilot"
_CACHE_PATH = Path("data") / "user_profile.json"

_EMPTY_PROFILE: Dict[str, Any] = {
    "name": "Knack",
    "technical_background": [],
    "projects": {},
    "preferences": {},
    "facts": [],
    "topics_of_interest": [],
    "conversation_count": 0,
    "last_updated": "",
}


# ──── UserProfileStore ────────────────────────────────────────────────────────


class UserProfileStore:
    """Persistent structured user profile with Nexus-backed storage.

    Reads/writes the user profile to a local JSON cache AND syncs to the
    Nexus knowledge base for agent visibility.

    Args:
        cache_path: Local JSON cache path (fast synchronous access).
    """

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self._cache_path = Path(cache_path or _CACHE_PATH)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._profile: Optional[Dict[str, Any]] = None  # loaded lazily

    # ── Public API ────────────────────────────────────────────────────────────

    def get_profile(self) -> Dict[str, Any]:
        """Return the full user profile dict (deep copy)."""
        with self._lock:
            return deepcopy(self._load())

    def merge(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``updates`` into the existing profile.

        - Lists are extended (unique values only).
        - Dicts are recursively merged.
        - Scalars are overwritten only if the new value is non-empty.

        Args:
            updates: Partial profile data to merge in.

        Returns:
            The updated full profile.
        """
        with self._lock:
            profile = self._load()
            _deep_merge(profile, updates)
            profile["last_updated"] = _now()
            self._save(profile)
            self._sync_to_nexus(profile)
            return deepcopy(profile)

    def add_fact(self, fact: str) -> None:
        """Add a single string fact to the profile facts list.

        Args:
            fact: A fact about the user, e.g. "Has RTX 2060 12GB".
        """
        fact = fact.strip()
        if not fact:
            return
        with self._lock:
            profile = self._load()
            if fact not in profile["facts"]:
                profile["facts"].append(fact)
                profile["last_updated"] = _now()
                self._save(profile)

    def add_preference(self, key: str, value: Any) -> None:
        """Set a named preference in the profile.

        Args:
            key: Preference key, e.g. "output_verbosity".
            value: Preference value.
        """
        with self._lock:
            profile = self._load()
            profile["preferences"][key] = value
            profile["last_updated"] = _now()
            self._save(profile)

    def add_project(self, name: str, details: Dict[str, Any]) -> None:
        """Add or update a tracked project.

        Args:
            name: Project name, e.g. "CosySim".
            details: Arbitrary project metadata dict.
        """
        with self._lock:
            profile = self._load()
            existing = profile["projects"].get(name, {})
            _deep_merge(existing, details)
            profile["projects"][name] = existing
            profile["last_updated"] = _now()
            self._save(profile)

    def increment_conversation_count(self) -> int:
        """Increment the conversation counter and return the new value."""
        with self._lock:
            profile = self._load()
            profile["conversation_count"] = profile.get("conversation_count", 0) + 1
            profile["last_updated"] = _now()
            self._save(profile)
            return profile["conversation_count"]

    def get_context_summary(self) -> str:
        """Return a compact markdown summary suitable for LLM context injection.

        Returns:
            Markdown string with key profile facts.
        """
        profile = self.get_profile()
        lines = [f"## User Profile: {profile.get('name', 'User')}"]
        if profile.get("technical_background"):
            lines.append(f"**Tech Background:** {', '.join(profile['technical_background'])}")
        if profile.get("projects"):
            proj_names = ", ".join(profile["projects"].keys())
            lines.append(f"**Projects:** {proj_names}")
        if profile.get("preferences"):
            prefs = "; ".join(f"{k}={v}" for k, v in profile["preferences"].items())
            lines.append(f"**Preferences:** {prefs}")
        if profile.get("facts"):
            lines.append(f"**Key Facts:**")
            for fact in profile["facts"][-20:]:  # Most recent 20
                lines.append(f"  - {fact}")
        if profile.get("topics_of_interest"):
            lines.append(f"**Topics:** {', '.join(profile['topics_of_interest'][:10])}")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        """Load profile from cache file (or return default)."""
        if self._profile is not None:
            return self._profile
        if self._cache_path.exists():
            try:
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    self._profile = json.load(f)
                # Ensure all keys exist (profile may be from older version)
                for k, v in _EMPTY_PROFILE.items():
                    self._profile.setdefault(k, deepcopy(v))
                return self._profile
            except Exception as exc:
                logger.warning("Failed to load user profile: %s", exc)
        self._profile = deepcopy(_EMPTY_PROFILE)
        return self._profile

    def _save(self, profile: Dict[str, Any]) -> None:
        """Persist profile to local cache."""
        self._profile = profile
        try:
            tmp = self._cache_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
            tmp.rename(self._cache_path)
        except Exception as exc:
            logger.error("Failed to save user profile: %s", exc)

    def _sync_to_nexus(self, profile: Dict[str, Any]) -> None:
        """Sync profile to Nexus knowledge base (non-blocking, best-effort)."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if not client.is_available():
                return
            content = json.dumps(profile, indent=2)
            summary = self.get_context_summary()
            client.add_entry(
                title="User Profile — Knack",
                content=f"{summary}\n\n```json\n{content}\n```",
                content_type="memory",
                category=_PROFILE_CATEGORY,
                tags=["user-profile", "preferences", "facts"],
            )
        except Exception as exc:
            logger.debug("Profile Nexus sync skipped: %s", exc)


# ──── Deep Merge Utility ──────────────────────────────────────────────────────


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """Recursively merge ``updates`` into ``base`` (mutates base).

    - Lists: extend with unique values
    - Dicts: recurse
    - Scalars: overwrite if update value is non-None and non-empty
    """
    for key, value in updates.items():
        if key not in base:
            base[key] = deepcopy(value)
        elif isinstance(value, list) and isinstance(base[key], list):
            existing = set(base[key]) if all(isinstance(i, str) for i in base[key]) else None
            for item in value:
                if existing is not None:
                    if item not in existing:
                        base[key].append(item)
                        existing.add(item)
                elif item not in base[key]:
                    base[key].append(item)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            _deep_merge(base[key], value)
        elif value is not None and value != "":
            base[key] = value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──── Singleton ───────────────────────────────────────────────────────────────

_store_instance: Optional[UserProfileStore] = None
_store_lock = threading.Lock()


def get_user_profile_store() -> UserProfileStore:
    """Get the singleton UserProfileStore instance."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = UserProfileStore()
    return _store_instance
