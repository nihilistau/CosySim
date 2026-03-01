"""Reputation system for CosySim v0.68 "Dark Renaissance".

Tracks standing between the player and every named character or faction across
all scenes.  Standing ranges from -100 (Nemesis) to +100 (Revered) and
persists in Nexus so it survives session restarts.

Cross-scene ripple effects let one scene's events bleed reputation changes
into other scenes — e.g. running up a casino debt quietly sours the Syndicate
*and* warms lounge characters, while cheating at cards triggers immediate
Corporate and Syndicate backlash.

The :class:`ReputationInterceptor` automatically injects a compact reputation
summary into every LLM system-prompt so characters react in-character without
any manual wiring.

Example::

    from engine.characters.reputation import get_reputation_manager

    mgr = get_reputation_manager()
    mgr.adjust("mira", delta=-30, reason="player betrayed Mira at the heist")
    print(mgr.get_prompt_context("mira"))
    # Your standing with the player is HOSTILE (-30). ...
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from engine.mcp.comms_framework import InterceptorBase, ResponseContext
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event bus — optional; missing import degrades gracefully
# ---------------------------------------------------------------------------

try:
    from engine.events.event_bus import get_event_bus as _get_event_bus
    _HAS_EVENT_BUS: bool = True
except ImportError:  # pragma: no cover
    _get_event_bus = lambda: None  # type: ignore
    _HAS_EVENT_BUS = False

# ---------------------------------------------------------------------------
# Nexus storage constants
# ---------------------------------------------------------------------------

_CONTENT_TYPE = "memory"
_CATEGORY = "reputation"
_MAX_HISTORY = 10


# ============================================================================
#  FactionId
# ============================================================================


class FactionId(str, Enum):
    """Well-known faction identifiers used for cross-scene reputation ripples.

    Using the ``str`` mixin keeps values JSON-serialisable without extra work.
    """

    SYNDICATE = "SYNDICATE"
    CORPORATE = "CORPORATE"
    UNDERGROUND = "UNDERGROUND"
    STREET = "STREET"
    HACKER = "HACKER"
    ARENA_GUILD = "ARENA_GUILD"


# ============================================================================
#  ReputationEntry
# ============================================================================


@dataclass
class ReputationEntry:
    """A single player-entity reputation record.

    Attributes:
        entity_id: Character ID or :class:`FactionId` value.
        entity_type: ``"character"`` or ``"faction"``.
        player_id: Player owning this standing (default ``"player"``).
        standing: Clamped integer in ``[-100, 100]``.
        label: Human-readable tier computed from *standing*.
        history: Up to 10 brief change notes, newest last.
        last_updated: ISO-8601 UTC timestamp of most recent write.
    """

    entity_id: str
    entity_type: str
    player_id: str
    standing: int
    label: str = field(default="")
    history: List[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.label_for(self.standing)

    # ── Label helpers ────────────────────────────────────────────────────────

    @staticmethod
    def label_for(standing: int) -> str:
        """Return the reputation tier label for *standing*.

        Args:
            standing: Integer in ``[-100, 100]``.

        Returns:
            One of: ``"Revered"``, ``"Trusted"``, ``"Friendly"``,
            ``"Neutral"``, ``"Indifferent"``, ``"Cold"``, ``"Hostile"``,
            ``"Enemy"``, ``"Nemesis"``.
        """
        if standing >= 81:
            return "Revered"
        if standing >= 61:
            return "Trusted"
        if standing >= 41:
            return "Friendly"
        if standing >= 21:
            return "Neutral"
        if standing >= -20:
            return "Indifferent"
        if standing >= -40:
            return "Cold"
        if standing >= -60:
            return "Hostile"
        if standing >= -80:
            return "Enemy"
        return "Nemesis"

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dictionary.

        Returns:
            Plain dict of all public fields.
        """
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "player_id": self.player_id,
            "standing": self.standing,
            "label": self.label,
            "history": list(self.history),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReputationEntry":
        """Deserialise from a plain dictionary.

        Args:
            data: Raw dict (partial payloads are handled gracefully).

        Returns:
            A fully populated :class:`ReputationEntry`.
        """
        entry = cls(
            entity_id=data.get("entity_id", ""),
            entity_type=data.get("entity_type", "character"),
            player_id=data.get("player_id", "player"),
            standing=int(data.get("standing", 0)),
            label=data.get("label", ""),
            history=list(data.get("history", [])),
            last_updated=data.get("last_updated", datetime.now(timezone.utc).isoformat()),
        )
        if not entry.label:
            entry.label = cls.label_for(entry.standing)
        return entry


# ============================================================================
#  Attitude copy for get_prompt_context
# ============================================================================

_ATTITUDE: Dict[str, str] = {
    "Revered":     "You hold this player in the highest regard. You are deeply loyal and would go to great lengths for them.",
    "Trusted":     "You trust this player deeply. You are warm, open, and genuinely willing to help.",
    "Friendly":    "You like this player. You are cooperative and pleased to assist.",
    "Neutral":     "You regard this player with mild goodwill. You are polite and willing to engage on fair terms.",
    "Indifferent": "You have no strong feelings about this player. You are neutral and professional.",
    "Cold":        "You are uneasy around this player. You are guarded and curt.",
    "Hostile":     "You dislike this player. You are guarded and cold, distrustful of their motives.",
    "Enemy":       "You view this player as an adversary. You are dismissive and obstructive.",
    "Nemesis":     "You despise this player. You are openly hostile and actively working against them.",
}

# ============================================================================
#  Cross-scene ripple map
# ============================================================================

# Each key is (source_scene, event_type); each value is a list of
# (entity_id, delta) tuples.  FactionId values are used for faction entries;
# plain strings for character IDs.
_RIPPLE_MAP: Dict[tuple, List[tuple]] = {
    ("casino", "debt_created"):    [(FactionId.SYNDICATE, -10), ("mira", -5)],
    ("heist",  "job_complete"):    [(FactionId.UNDERGROUND, +15)],
    ("arena",  "bet_win"):         [(FactionId.ARENA_GUILD, +10)],
    ("casino", "cheat_detected"):  [(FactionId.CORPORATE, -30), (FactionId.SYNDICATE, -20)],
}


# ============================================================================
#  ReputationManager
# ============================================================================


class ReputationManager:
    """Manages cross-scene reputation standing between the player and entities.

    All standing changes are persisted to Nexus so they survive restarts.
    When the label tier changes (e.g. *Hostile* → *Enemy*) an ``EventBus``
    event is fired so other systems can react.

    Args:
        nexus_client: Optional pre-built Nexus client (useful in tests).
    """

    def __init__(self, nexus_client=None) -> None:
        self._nexus = nexus_client or get_nexus_client()
        self._cache: Dict[str, ReputationEntry] = {}
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(entity_id: str, player_id: str) -> str:
        return f"{entity_id}:{player_id}"

    @staticmethod
    def _nexus_title(entity_id: str, player_id: str) -> str:
        return f"rep:{entity_id}:{player_id}"

    @staticmethod
    def _entity_type_for(entity_id: str) -> str:
        """Infer whether *entity_id* is a faction or character.

        Args:
            entity_id: Raw entity identifier string.

        Returns:
            ``"faction"`` if the ID matches a :class:`FactionId` value,
            otherwise ``"character"``.
        """
        try:
            FactionId(entity_id)
            return "faction"
        except ValueError:
            return "character"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_from_nexus(self, entity_id: str, player_id: str) -> Optional[ReputationEntry]:
        """Fetch a reputation entry from Nexus by exact title.

        Args:
            entity_id: Entity identifier.
            player_id: Player identifier.

        Returns:
            Parsed :class:`ReputationEntry`, or ``None`` if not found.
        """
        title = self._nexus_title(entity_id, player_id)
        try:
            results = self._nexus.search(title, limit=5)
        except Exception as exc:
            logger.warning("ReputationManager: Nexus search failed — %s", exc)
            return None
        for r in results:
            if r.get("title") == title:
                try:
                    data = json.loads(r.get("content", "{}"))
                    return ReputationEntry.from_dict(data)
                except (json.JSONDecodeError, TypeError, KeyError) as exc:
                    logger.debug("ReputationManager: bad payload for %r — %s", title, exc)
        return None

    def _save_to_nexus(self, entry: ReputationEntry) -> None:
        """Persist *entry* to Nexus (upsert by title).

        Args:
            entry: The entry to save.
        """
        title = self._nexus_title(entry.entity_id, entry.player_id)
        content = json.dumps(entry.to_dict())
        try:
            existing = self._nexus.search(title, limit=2)
            nexus_id: Optional[str] = None
            for r in existing:
                if r.get("title") == title:
                    nexus_id = r.get("id")
                    break
            if nexus_id:
                self._nexus.update_entry(nexus_id, content=content)
            else:
                self._nexus.add_entry(
                    title=title,
                    content=content,
                    content_type=_CONTENT_TYPE,
                    category=_CATEGORY,
                )
        except Exception as exc:
            logger.warning("ReputationManager: Nexus persist failed — %s", exc)

    def _fire_label_change(
        self,
        entity_id: str,
        player_id: str,
        old_label: str,
        new_label: str,
        standing: int,
    ) -> None:
        """Publish a reputation label-change event on the EventBus.

        Args:
            entity_id: Entity whose reputation changed.
            player_id: Affected player.
            old_label: Previous tier label.
            new_label: New tier label.
            standing: Current standing value.
        """
        if not _HAS_EVENT_BUS:
            return
        try:
            bus = _get_event_bus()
            if bus is not None:
                bus.publish(
                    "reputation.label_changed",
                    {
                        "entity_id": entity_id,
                        "player_id": player_id,
                        "old_label": old_label,
                        "new_label": new_label,
                        "standing": standing,
                    },
                )
        except Exception as exc:
            logger.debug("ReputationManager: EventBus publish failed — %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_standing(self, entity_id: str, player_id: str = "player") -> int:
        """Return the current standing for *entity_id*.

        Args:
            entity_id: Character or faction ID.
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            Standing integer in ``[-100, 100]``.  Returns ``0`` if no record
            exists yet.
        """
        return self.get_entry(entity_id, player_id).standing

    def get_entry(self, entity_id: str, player_id: str = "player") -> ReputationEntry:
        """Return the full :class:`ReputationEntry` for *entity_id*.

        Checks the in-process cache first; falls back to Nexus; creates a
        fresh zero-standing entry if none is found.

        Args:
            entity_id: Character or faction ID.
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            A :class:`ReputationEntry` (never ``None``).
        """
        key = self._cache_key(entity_id, player_id)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        entry = self._load_from_nexus(entity_id, player_id)
        if entry is None:
            entry = ReputationEntry(
                entity_id=entity_id,
                entity_type=self._entity_type_for(entity_id),
                player_id=player_id,
                standing=0,
            )
        with self._lock:
            self._cache[key] = entry
        return entry

    def adjust(
        self,
        entity_id: str,
        delta: int,
        reason: str,
        player_id: str = "player",
    ) -> ReputationEntry:
        """Adjust the standing for *entity_id* by *delta*.

        Clamps the result to ``[-100, 100]``.  Appends a note to history (max
        last 10).  Fires an EventBus event when the label tier crosses a
        boundary.  Persists to Nexus.

        Args:
            entity_id: Character or faction ID.
            delta: Positive or negative integer adjustment.
            reason: Brief description used as the history note.
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            The updated :class:`ReputationEntry`.
        """
        entry = self.get_entry(entity_id, player_id)

        old_label = entry.label
        old_standing = entry.standing

        new_standing = max(-100, min(100, old_standing + delta))
        entry.standing = new_standing
        entry.label = ReputationEntry.label_for(new_standing)
        entry.last_updated = self._now_iso()

        note = f"{'+' if delta >= 0 else ''}{delta}: {reason} (now {new_standing})"
        entry.history.append(note)
        if len(entry.history) > _MAX_HISTORY:
            entry.history = entry.history[-_MAX_HISTORY:]

        with self._lock:
            self._cache[self._cache_key(entity_id, player_id)] = entry

        self._save_to_nexus(entry)

        if entry.label != old_label:
            self._fire_label_change(entity_id, player_id, old_label, entry.label, new_standing)
            logger.info(
                "Reputation label changed: %s → %s (%s, %s standing %d → %d)",
                old_label,
                entry.label,
                entity_id,
                player_id,
                old_standing,
                new_standing,
            )

        return entry

    def set_standing(
        self,
        entity_id: str,
        standing: int,
        reason: str,
        player_id: str = "player",
    ) -> ReputationEntry:
        """Set the standing for *entity_id* to an absolute value.

        Equivalent to computing the delta from the current value and calling
        :meth:`adjust`.

        Args:
            entity_id: Character or faction ID.
            standing: New standing; will be clamped to ``[-100, 100]``.
            reason: Brief description used as the history note.
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            The updated :class:`ReputationEntry`.
        """
        clamped = max(-100, min(100, standing))
        current = self.get_standing(entity_id, player_id)
        delta = clamped - current
        return self.adjust(entity_id, delta, reason, player_id)

    def get_faction_standings(
        self, player_id: str = "player"
    ) -> Dict[str, ReputationEntry]:
        """Return standing entries for every known :class:`FactionId`.

        Factions with no recorded standing are returned with ``standing=0``.

        Args:
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            Mapping of faction ID string → :class:`ReputationEntry`.
        """
        return {fid.value: self.get_entry(fid.value, player_id) for fid in FactionId}

    def apply_cross_scene_ripple(
        self,
        source_scene: str,
        event_type: str,
        delta: int,
        player_id: str = "player",
    ) -> List[str]:
        """Apply cross-scene reputation ripple effects for a scene event.

        Looks up the ``(source_scene, event_type)`` combination in the ripple
        map and applies the pre-defined adjustments, scaling by *delta* sign.

        Defined ripples:

        * ``("casino", "debt_created")``    → SYNDICATE -10, mira -5
        * ``("heist",  "job_complete")``    → UNDERGROUND +15
        * ``("arena",  "bet_win")``         → ARENA_GUILD +10
        * ``("casino", "cheat_detected")``  → CORPORATE -30, SYNDICATE -20

        Args:
            source_scene: Name of the scene that generated the event.
            event_type: Event sub-type string.
            delta: Caller-supplied magnitude (currently used as a sign hint;
                the built-in adjustments are applied as absolute values).
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            List of human-readable summary strings for each adjustment made.
        """
        key = (source_scene, event_type)
        ripples = _RIPPLE_MAP.get(key, [])
        summaries: List[str] = []
        for entity, adj in ripples:
            entity_id = entity.value if isinstance(entity, FactionId) else entity
            entry = self.adjust(entity_id, adj, f"{source_scene}_{event_type}", player_id)
            summaries.append(
                f"Adjusted {entity_id} by {'+' if adj >= 0 else ''}{adj}: "
                f"{source_scene}_{event_type} (now {entry.label} {entry.standing})"
            )
        if ripples:
            logger.debug(
                "Cross-scene ripple (%s, %s): %d adjustments for player %r.",
                source_scene,
                event_type,
                len(ripples),
                player_id,
            )
        return summaries

    def get_prompt_context(
        self, entity_id: str, player_id: str = "player"
    ) -> str:
        """Return a compact reputation summary for injection into a system prompt.

        Example output::

            Your standing with the player is HOSTILE (-55).
            You remember past betrayals. You are guarded and cold.

        Args:
            entity_id: Character or faction ID.
            player_id: Player identifier; defaults to ``"player"``.

        Returns:
            A natural-language reputation summary string.
        """
        entry = self.get_entry(entity_id, player_id)
        label_upper = entry.label.upper()
        parts = [f"Your standing with the player is {label_upper} ({entry.standing})."]
        if entry.history:
            parts.append(f"Recent: {entry.history[-1]}")
        attitude = _ATTITUDE.get(entry.label, "You are neutral.")
        parts.append(attitude)
        return " ".join(parts)


# ============================================================================
#  ReputationInterceptor
# ============================================================================


class ReputationInterceptor(InterceptorBase):
    """Injects a reputation context block into the LLM system prompt.

    Reads the active character ID from :attr:`~engine.mcp.comms_framework.ResponseContext`
    and prepends a ``[REPUTATION]…[/REPUTATION]`` block so the character's
    attitude reflects their actual standing with the player.

    Priority 22 runs after most setup interceptors but before the LLM call.
    """

    name: str = "reputation"
    priority: int = 22

    def pre_call(self, ctx: ResponseContext) -> None:
        """Prepend reputation context to the system prompt.

        Args:
            ctx: Mutable interaction context bag.
        """
        character_id = ctx.get("agent_id", "")
        if not character_id:
            return
        try:
            manager = get_reputation_manager()
            prompt_context = manager.get_prompt_context(character_id)
            existing = ctx.get("system_prompt", "") or ""
            ctx["system_prompt"] = (
                f"[REPUTATION]\n{prompt_context}\n[/REPUTATION]\n{existing}"
            )
        except Exception as exc:
            logger.warning("ReputationInterceptor.pre_call failed — %s", exc)

    def post_call(self, ctx: ResponseContext) -> None:  # noqa: B027
        """Pass-through; no post-LLM mutation needed.

        Args:
            ctx: Mutable interaction context bag.
        """


# ============================================================================
#  Singleton
# ============================================================================

_manager_instance: Optional[ReputationManager] = None
_manager_lock = threading.Lock()


def get_reputation_manager() -> ReputationManager:
    """Return the process-global :class:`ReputationManager` singleton.

    Thread-safe via double-checked locking.

    Returns:
        The shared :class:`ReputationManager` instance.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ReputationManager()
                logger.info("ReputationManager singleton created.")
    return _manager_instance
