"""
CosySim Character State Coordinator
=====================================

**The single write-through API for all character state mutations.**

Problem
-------
Before this module, character state was scattered across three stores
that didn't sync:

- **CharacterRegistry** — mood, energy, inhibition, focus, restrictions
- **SceneStateManager** — arousal, happiness, clothing, narrative, stats
- **Database** — persistent name/age/personality (never written back to)

Scenes and interceptors would write to one store while others read from
another, causing contradictions (e.g., Registry says ``mood=bored`` while
SSM says ``arousal=80``).

Solution
--------
The ``CharacterStateCoordinator`` provides a single ``update()`` method
that writes through to **all** relevant stores atomically:

- Known CharacterState fields (mood, energy, inhibition, focus) → Registry
- Known StatsSnapshot fields (arousal, happiness, etc.) → SSM
- All changes → ActivityBus event ("state_changed")
- Optionally → Database persistence (configurable)

Every scene, interceptor, and MCP tool should go through the coordinator
instead of calling ``set_state()`` / ``update_stats()`` directly.

Quick start::

    from engine.mcp.state_coordinator import get_coordinator

    coord = get_coordinator()

    # Unified update — routes fields to the right store automatically
    coord.update("lola", mood="flirty", arousal=+10, energy=-5)

    # Get a unified snapshot of all state
    state = coord.get_full_state("lola")
    # {"mood": "flirty", "mood_intensity": 0.5, "energy": 75.0,
    #  "arousal": 30.0, "happiness": 60.0, ...}

    # Delta-only mode (default) vs absolute mode
    coord.update("lola", arousal=+15)           # delta: arousal += 15
    coord.update("lola", arousal=50, mode="set") # absolute: arousal = 50

Architecture
------------
::

    coord.update(char_id, **fields)
        ├── Registry fields → CharacterRegistry.set_state()
        ├── Stats fields    → SceneStateManager.update_stats() or set_stats()
        ├── ActivityBus     → emit("state_changed", {char_id, deltas, snapshot})
        └── DB persist      → Database.update_character() (if persist=True)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# Fields that belong to CharacterRegistry.set_state()
REGISTRY_FIELDS: Set[str] = {
    "mood", "mood_intensity", "focus", "current_role",
    "energy", "inhibition",
}

# Fields that belong to SceneStateManager stats (StatsSnapshot)
STATS_FIELDS: Set[str] = {
    "arousal", "horniness", "pleasure", "happiness",
    "anger", "fear", "drunkenness", "tiredness",
    "explicitness", "openness", "affection", "dominance",
}

# Fields that are restriction operations (special handling)
RESTRICTION_OPS: Set[str] = {"add_restriction", "remove_restriction"}


class CharacterStateCoordinator:
    """
    Single write-through API for all character state mutations.

    Thread-safe. Uses per-character locks to allow concurrent updates
    to different characters without blocking.
    """

    def __init__(self) -> None:
        self._char_locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()  # protects _char_locks dict
        self._listeners: list = []

    def _get_char_lock(self, character_id: str) -> threading.Lock:
        """Get or create a per-character lock."""
        if character_id not in self._char_locks:
            with self._global_lock:
                if character_id not in self._char_locks:
                    self._char_locks[character_id] = threading.Lock()
        return self._char_locks[character_id]

    # ── Main API ──────────────────────────────────────────────────────

    def update(
        self,
        character_id: str,
        *,
        mode: str = "delta",
        persist: bool = False,
        scene: str = "",
        source: str = "",
        **fields,
    ) -> Dict[str, Any]:
        """
        Update character state, routing each field to the correct store.

        Parameters
        ----------
        character_id : str
            The character to update.
        mode : str
            "delta" (default) — numeric fields are added to current value.
            "set" — numeric fields are set to absolute value.
        persist : bool
            If True, also write state to the database for persistence.
        scene : str
            Scene context for logging/events.
        source : str
            Who triggered this update (for audit trail).
        **fields
            Any combination of Registry fields and Stats fields.

        Returns
        -------
        dict
            Snapshot of the character's full state after the update.
        """
        if not fields:
            return self.get_full_state(character_id)

        lock = self._get_char_lock(character_id)
        with lock:
            registry_updates = {}
            stats_updates = {}
            restriction_adds = set()
            restriction_removes = set()
            flag_updates = {}

            for key, value in fields.items():
                if key in REGISTRY_FIELDS:
                    registry_updates[key] = value
                elif key in STATS_FIELDS:
                    stats_updates[key] = value
                elif key == "add_restriction":
                    if isinstance(value, (list, set, tuple)):
                        restriction_adds.update(value)
                    else:
                        restriction_adds.add(value)
                elif key == "remove_restriction":
                    if isinstance(value, (list, set, tuple)):
                        restriction_removes.update(value)
                    else:
                        restriction_removes.add(value)
                else:
                    # Unknown fields go to registry flags
                    flag_updates[key] = value

            # ── Write to CharacterRegistry ────────────────────────
            if registry_updates or flag_updates:
                try:
                    from engine.mcp.character_registry import get_character_registry
                    reg = get_character_registry()
                    combined = {**registry_updates}
                    if flag_updates:
                        combined["flags"] = flag_updates
                    reg.set_state(character_id, **combined)
                except Exception as exc:
                    logger.warning(
                        "StateCoordinator: Registry write failed for %s: %s",
                        character_id, exc,
                    )

            # ── Write to SceneStateManager ────────────────────────
            if stats_updates:
                try:
                    from engine.mcp.scene_state import get_scene_state_manager
                    ssm = get_scene_state_manager()
                    if mode == "set":
                        ssm.set_stats(character_id, **stats_updates)
                    else:
                        ssm.update_stats(character_id, **stats_updates)
                except Exception as exc:
                    logger.warning(
                        "StateCoordinator: SSM write failed for %s: %s",
                        character_id, exc,
                    )

            # ── Handle restrictions ───────────────────────────────
            if restriction_adds or restriction_removes:
                try:
                    from engine.mcp.character_registry import get_character_registry
                    reg = get_character_registry()
                    for r in restriction_adds:
                        reg.add_restriction(character_id, r)
                    for r in restriction_removes:
                        reg.remove_restriction(character_id, r)
                except Exception as exc:
                    logger.warning(
                        "StateCoordinator: Restriction update failed for %s: %s",
                        character_id, exc,
                    )

            # ── Persist to database (optional) ────────────────────
            if persist:
                self._persist_to_db(character_id)

        # ── Emit state_changed event ──────────────────────────────
        snapshot = self.get_full_state(character_id)
        self._emit_event(character_id, fields, snapshot, scene, source)

        return snapshot

    def get_full_state(self, character_id: str) -> Dict[str, Any]:
        """
        Get a unified snapshot of all state for a character.

        Merges CharacterRegistry state + SceneStateManager stats into
        a single flat dict.
        """
        result: Dict[str, Any] = {"character_id": character_id}

        # Registry state
        try:
            from engine.mcp.character_registry import get_character_registry
            reg = get_character_registry()
            state = reg.get_state(character_id)
            result.update(state)
        except Exception:
            pass

        # SSM stats
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            stats = ssm.get_stats(character_id)
            result.update(stats.to_dict())
        except Exception:
            pass

        return result

    def get_field(
        self, character_id: str, field: str, default: Any = None,
    ) -> Any:
        """Get a single field from the unified state."""
        state = self.get_full_state(character_id)
        return state.get(field, default)

    # ── Event emission ────────────────────────────────────────────────

    def on_state_changed(self, callback) -> None:
        """Register a listener for state change events."""
        self._listeners.append(callback)

    def _emit_event(
        self,
        character_id: str,
        changes: Dict,
        snapshot: Dict,
        scene: str,
        source: str,
    ) -> None:
        """Emit state_changed event to ActivityBus and registered listeners."""
        event = {
            "type": "state_changed",
            "character_id": character_id,
            "changes": changes,
            "scene": scene,
            "source": source,
            "timestamp": time.time(),
        }

        # Notify registered listeners
        for listener in self._listeners:
            try:
                listener(event, snapshot)
            except Exception as exc:
                logger.debug("StateCoordinator: listener error: %s", exc)

        # Emit to ActivityBus
        try:
            from engine.services.activity_bus import get_activity_bus, Activity
            bus = get_activity_bus()
            bus.push(Activity(
                activity_type="state_changed",
                description=(
                    f"{character_id}: {', '.join(f'{k}={v}' for k, v in changes.items())}"
                ),
                metadata={
                    "character_id": character_id,
                    "changes": {k: v for k, v in changes.items()
                                if isinstance(v, (int, float, str, bool))},
                    "scene": scene,
                    "source": source,
                },
            ))
        except Exception:
            pass  # ActivityBus is optional

    # ── Persistence ───────────────────────────────────────────────────

    def _persist_to_db(self, character_id: str) -> None:
        """Write current state to the database for cross-session persistence."""
        try:
            from content.simulation.database.db import Database
            db = Database()
            full = self.get_full_state(character_id)

            # Persist personality-level attributes that map to DB columns
            updates = {}
            for key in ("mood", "energy"):
                if key in full:
                    updates[key] = full[key]

            if updates:
                db.update_character(character_id, **updates)
                logger.debug(
                    "StateCoordinator: persisted %s to DB: %s",
                    character_id, updates,
                )
        except Exception as exc:
            logger.debug("StateCoordinator: DB persist failed for %s: %s",
                         character_id, exc)


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON
# ══════════════════════════════════════════════════════════════════════

_COORDINATOR: Optional[CharacterStateCoordinator] = None
_COORD_LOCK = threading.Lock()


def get_coordinator() -> CharacterStateCoordinator:
    """
    Return the global CharacterStateCoordinator singleton.
    Thread-safe, safe to call from any context.
    """
    global _COORDINATOR
    if _COORDINATOR is None:
        with _COORD_LOCK:
            if _COORDINATOR is None:
                _COORDINATOR = CharacterStateCoordinator()
    return _COORDINATOR
