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
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

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
    "relationship", "attraction", "trust",
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
        self._char_locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.Lock()  # protects _char_locks dict
        self._listeners: list = []
        self._buffs: Dict[str, Dict[str, RelationshipBuff]] = {}  # char_id → {buff_id → Buff}
        self._tags: Dict[str, Dict[str, Dict]] = {}  # char_id → {tag → info}

    def _get_char_lock(self, character_id: str) -> threading.RLock:
        """Get or create a per-character reentrant lock."""
        if character_id not in self._char_locks:
            with self._global_lock:
                if character_id not in self._char_locks:
                    self._char_locks[character_id] = threading.RLock()
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
            logger.debug("Suppressed exception", exc_info=True)

        # SSM stats
        try:
            from engine.mcp.scene_state import get_scene_state_manager
            ssm = get_scene_state_manager()
            stats = ssm.get_stats(character_id)
            result.update(stats.to_dict())
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

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
            logger.debug("ActivityBus is optional", exc_info=True)

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

    # ── Relationship Buff/Debuff System ──────────────────────────────

    def add_buff(
        self,
        character_id: str,
        buff_id: str,
        stat_deltas: Dict[str, float],
        duration_secs: float = 300.0,
        source: str = "",
    ) -> None:
        """
        Apply a temporary buff/debuff to a character.

        Buffs modify stats for a limited time, then automatically expire.
        Use negative values for debuffs.
        """
        lock = self._get_char_lock(character_id)
        with lock:
            if character_id not in self._buffs:
                self._buffs[character_id] = {}
            self._buffs[character_id][buff_id] = RelationshipBuff(
                buff_id=buff_id,
                stat_deltas=stat_deltas,
                expires_at=time.time() + duration_secs,
                source=source,
            )
            # Apply the buff immediately
            self.update(character_id, source=f"buff:{buff_id}", **stat_deltas)

    def remove_expired_buffs(self, character_id: str) -> List[str]:
        """Remove expired buffs and reverse their stat effects. Returns removed buff IDs."""
        lock = self._get_char_lock(character_id)
        now = time.time()
        removed = []
        with lock:
            buffs = self._buffs.get(character_id, {})
            expired = {bid: b for bid, b in buffs.items() if b.expires_at <= now}
            for bid, buff in expired.items():
                # Reverse the buff effects
                reverse = {k: -v for k, v in buff.stat_deltas.items()}
                self.update(character_id, source=f"buff_expire:{bid}", **reverse)
                del buffs[bid]
                removed.append(bid)
        return removed

    def get_active_buffs(self, character_id: str) -> Dict[str, Dict]:
        """Get all active buffs for a character."""
        now = time.time()
        buffs = self._buffs.get(character_id, {})
        return {
            bid: {"deltas": b.stat_deltas, "remaining_secs": max(0, b.expires_at - now),
                  "source": b.source}
            for bid, b in buffs.items() if b.expires_at > now
        }

    def sweep_all_expired_buffs(self) -> int:
        """Sweep expired buffs for ALL characters. Returns total removed count."""
        total = 0
        for char_id in list(self._buffs.keys()):
            removed = self.remove_expired_buffs(char_id)
            total += len(removed)
        return total

    # ── Attraction Model ─────────────────────────────────────────────

    def calculate_attraction(
        self,
        char_a: str,
        char_b: str,
    ) -> float:
        """
        Calculate attraction score (0-100) between two characters.

        Factors: personality compatibility, relationship level, mood alignment,
        affection, shared interactions (trust).
        """
        state_a = self.get_full_state(char_a)
        state_b = self.get_full_state(char_b)

        score = 50.0  # baseline

        # Affection component (direct — up to ±20)
        affection_a = state_a.get("affection", 50)
        score += (affection_a - 50) * 0.4  # ±20

        # Trust component (up to ±15)
        trust = state_a.get("trust", 50)
        score += (trust - 50) * 0.3  # ±15

        # Mood alignment bonus (same mood → +5, opposite → -5)
        mood_a = state_a.get("mood", "neutral")
        mood_b = state_b.get("mood", "neutral")
        if mood_a == mood_b and mood_a != "neutral":
            score += 5
        elif mood_a in ("angry", "fearful") and mood_b in ("happy", "playful"):
            score -= 5

        # Relationship level (up to ±10)
        rel = state_a.get("relationship", 50)
        score += (rel - 50) * 0.2  # ±10

        return max(0, min(100, score))

    # ── Character Tags System ────────────────────────────────────────

    def add_tag(
        self,
        character_id: str,
        tag: str,
        strength: float = 1.0,
        decay_rate: float = 0.01,
    ) -> None:
        """
        Add or reinforce a character tag.

        Tags are soft labels that reflect accumulated behavior patterns.
        They decay slowly over time — if not reinforced, they fade.
        Tags reinforced to max strength 5+ times become permanent (zero decay).

        Parameters
        ----------
        tag : str
            Short label, e.g. "flirtatious", "daring", "loyal".
        strength : float
            Initial or added strength (0.0-1.0). Reinforcing adds to existing.
        decay_rate : float
            How much strength is lost per sweep (default 0.01 per drift tick).
        """
        lock = self._get_char_lock(character_id)
        with lock:
            if character_id not in self._tags:
                self._tags[character_id] = {}
            existing = self._tags[character_id].get(tag)
            if existing:
                new_strength = min(1.0, existing["strength"] + strength * 0.5)
                # Track reinforcements at max strength → permanent trait
                if new_strength >= 1.0:
                    existing["max_hits"] = existing.get("max_hits", 0) + 1
                    if existing["max_hits"] >= 5 and existing["decay_rate"] > 0:
                        existing["decay_rate"] = 0.0
                        existing["permanent"] = True
                existing["strength"] = new_strength
                existing["reinforced"] = time.time()
            else:
                self._tags[character_id][tag] = {
                    "strength": min(1.0, strength),
                    "decay_rate": decay_rate,
                    "created": time.time(),
                    "reinforced": time.time(),
                    "max_hits": 0,
                    "permanent": False,
                }

    def get_tags(self, character_id: str, min_strength: float = 0.1) -> Dict[str, float]:
        """Get active tags for a character, filtered by minimum strength."""
        tags = self._tags.get(character_id, {})
        return {
            tag: info["strength"]
            for tag, info in tags.items()
            if info["strength"] >= min_strength
        }

    def get_top_tags(self, character_id: str, n: int = 5) -> List[str]:
        """Get the N strongest tags for a character."""
        tags = self.get_tags(character_id, min_strength=0.05)
        sorted_tags = sorted(tags.items(), key=lambda x: -x[1])
        return [tag for tag, _ in sorted_tags[:n]]

    def get_permanent_tags(self, character_id: str) -> List[str]:
        """Get tags that have become permanent traits for a character."""
        tags = self._tags.get(character_id, {})
        return [tag for tag, info in tags.items() if info.get("permanent", False)]

    def decay_tags(self, character_id: str) -> int:
        """Decay all tags for a character. Called by drift interceptor. Returns removed count."""
        lock = self._get_char_lock(character_id)
        removed = 0
        with lock:
            tags = self._tags.get(character_id, {})
            expired = []
            for tag, info in tags.items():
                info["strength"] -= info["decay_rate"]
                if info["strength"] <= 0:
                    expired.append(tag)
            for tag in expired:
                del tags[tag]
                removed += 1
        return removed

    def sweep_all_tags(self) -> int:
        """Decay tags for ALL characters. Returns total removed count."""
        total = 0
        for char_id in list(self._tags.keys()):
            total += self.decay_tags(char_id)
        return total


@dataclass
class RelationshipBuff:
    """A temporary stat modifier applied to a character."""
    buff_id: str
    stat_deltas: Dict[str, float]
    expires_at: float
    source: str = ""


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
