"""Consequence engine for CosySim v0.68 "Dark Renaissance".

Actions in one scene can produce delayed consequences that surface in another.
A casino debt might mean Mira calls the next evening; a heist payout sees the
fence's cut arrive the next morning.

Consequences are scheduled by source-scene code, persisted in Nexus, and
polled by the ``consequence-poll`` scheduler task (or any scene's tick loop).
The poller retrieves due consequences and hands them to scene-specific
execution logic.

Usage::

    from engine.mechanics.consequences import get_consequence_store, ConsequenceType

    store = get_consequence_store()

    # Casino scene — player owes Mira 5000cr
    c = store.build_debt_consequence(
        scene="casino",
        amount=5000,
        debtor="player",
        creditor_char="mira",
    )

    # Later — polling from the lounge scene tick
    due = store.poll(scene="lounge", player_id="player")
    for consequence in due:
        execute_consequence(consequence)
        store.mark_fired(consequence.id)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nexus storage constants
# ---------------------------------------------------------------------------

_CONTENT_TYPE = "history"
_CATEGORY = "consequences"
_LIST_LIMIT = 200  # max entries fetched from Nexus per poll


# ============================================================================
#  ConsequenceType
# ============================================================================


class ConsequenceType(str, Enum):
    """Semantic category of a cross-scene consequence.

    Using the ``str`` mixin keeps values JSON-serialisable without extra work.
    """

    CONTACT = "CONTACT"
    """An NPC contacts or visits the player."""

    ITEM_DELIVERY = "ITEM_DELIVERY"
    """An item arrives for the player."""

    REPUTATION_SHIFT = "REPUTATION_SHIFT"
    """A scheduled reputation adjustment fires."""

    ECONOMY_TRANSACTION = "ECONOMY_TRANSACTION"
    """A monetary credit or debit is applied."""

    WORLD_EVENT = "WORLD_EVENT"
    """A change to global world state."""

    CHARACTER_MESSAGE = "CHARACTER_MESSAGE"
    """A character sends the player a message."""

    THREAT = "THREAT"
    """A threat manifests (ambush, debt collector, bounty hunter…)."""


# ============================================================================
#  Consequence
# ============================================================================


@dataclass
class Consequence:
    """A single scheduled cross-scene consequence.

    Attributes:
        id: Unique UUID string for this consequence.
        consequence_type: Semantic category from :class:`ConsequenceType`.
        source_scene: Scene that created this consequence.
        target_scene: Scene where the consequence should fire.  Empty string
            means *any* scene.
        player_id: Player this consequence applies to.
        description: Human-readable summary for logging / UI.
        payload: Type-specific data dict (e.g. ``{"amount": 500, "from": "mira"}``).
        scheduled_at: UNIX timestamp at which the consequence becomes due.
        fired: ``True`` once the consequence has been executed.
        fired_at: UNIX timestamp when it was marked fired, or ``None``.
        created_at: UNIX timestamp of creation.
    """

    id: str
    consequence_type: ConsequenceType
    source_scene: str
    target_scene: str
    player_id: str
    description: str
    payload: Dict
    scheduled_at: float
    fired: bool = False
    fired_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    # ── Status helpers ────────────────────────────────────────────────────────

    def is_due(self) -> bool:
        """Return ``True`` if this consequence should fire now.

        A consequence is due when the current time has passed
        :attr:`scheduled_at` and it has not yet been fired.

        Returns:
            Boolean indicating whether execution should proceed.
        """
        return time.time() >= self.scheduled_at and not self.fired

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dictionary.

        Returns:
            Plain dict of all fields; :attr:`consequence_type` is stored as
            its string value.
        """
        return {
            "id": self.id,
            "consequence_type": self.consequence_type.value,
            "source_scene": self.source_scene,
            "target_scene": self.target_scene,
            "player_id": self.player_id,
            "description": self.description,
            "payload": dict(self.payload),
            "scheduled_at": self.scheduled_at,
            "fired": self.fired,
            "fired_at": self.fired_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Consequence":
        """Deserialise from a plain dictionary.

        Args:
            data: Raw dict; missing optional fields receive safe defaults.

        Returns:
            A fully populated :class:`Consequence`.
        """
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            consequence_type=ConsequenceType(data.get("consequence_type", ConsequenceType.WORLD_EVENT)),
            source_scene=data.get("source_scene", ""),
            target_scene=data.get("target_scene", ""),
            player_id=data.get("player_id", "player"),
            description=data.get("description", ""),
            payload=dict(data.get("payload", {})),
            scheduled_at=float(data.get("scheduled_at", time.time())),
            fired=bool(data.get("fired", False)),
            fired_at=data.get("fired_at"),
            created_at=float(data.get("created_at", time.time())),
        )


# ============================================================================
#  ConsequenceStore
# ============================================================================


class ConsequenceStore:
    """Schedules, persists, polls, and fires cross-scene consequences.

    All consequences are persisted in Nexus under:

    * ``content_type = "history"``
    * ``category     = "consequences"``
    * ``title        = "consequence:{id}"``

    The store does **not** execute consequences — it returns due items and
    expects the caller (scene tick, scheduler, CLI) to execute and then call
    :meth:`mark_fired`.

    Args:
        nexus_client: Optional pre-built Nexus client (useful in tests).
    """

    def __init__(self, nexus_client=None) -> None:
        self._nexus = nexus_client or get_nexus_client()
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _nexus_title(consequence_id: str) -> str:
        return f"consequence:{consequence_id}"

    def _parse(self, raw: dict) -> Optional[Consequence]:
        """Parse a Nexus entry dict into a :class:`Consequence`.

        Args:
            raw: Raw dict from ``list_by_type`` / ``search``.

        Returns:
            Parsed :class:`Consequence`, or ``None`` on failure.
        """
        try:
            data = json.loads(raw.get("content", "{}"))
            return Consequence.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            logger.debug(
                "ConsequenceStore: could not parse Nexus entry %s — %s",
                raw.get("id"),
                exc,
            )
            return None

    def _save(self, consequence: Consequence) -> Optional[str]:
        """Persist *consequence* to Nexus.

        Args:
            consequence: The consequence to persist.

        Returns:
            Nexus entry ID, or ``None`` on failure.
        """
        try:
            return self._nexus.add_entry(
                title=self._nexus_title(consequence.id),
                content=json.dumps(consequence.to_dict()),
                content_type=_CONTENT_TYPE,
                category=_CATEGORY,
            )
        except Exception as exc:
            logger.warning("ConsequenceStore: Nexus save failed — %s", exc)
            return None

    def _find_nexus_id(self, consequence_id: str) -> Optional[str]:
        """Search Nexus for the entry ID of a consequence by its CosySim ID.

        Args:
            consequence_id: Consequence's own ``id`` field.

        Returns:
            Nexus entry ID string, or ``None`` if not found.
        """
        title = self._nexus_title(consequence_id)
        try:
            results = self._nexus.search(title, limit=3)
            for r in results:
                if r.get("title") == title:
                    return r.get("id")
        except Exception as exc:
            logger.warning("ConsequenceStore: Nexus search failed — %s", exc)
        return None

    def _list_all(self) -> List[Consequence]:
        """Fetch all consequence entries from Nexus.

        Returns:
            List of :class:`Consequence` objects (may be empty).
        """
        try:
            raw_entries = self._nexus.list_by_type(
                _CONTENT_TYPE, category=_CATEGORY, limit=_LIST_LIMIT
            )
        except Exception as exc:
            logger.warning("ConsequenceStore: Nexus list failed — %s", exc)
            return []
        consequences = []
        for raw in raw_entries:
            c = self._parse(raw)
            if c is not None:
                consequences.append(c)
        return consequences

    # ── Public API ─────────────────────────────────────────────────────────────

    def schedule(
        self,
        consequence_type: ConsequenceType,
        source_scene: str,
        target_scene: str,
        description: str,
        payload: dict,
        delay_hours: float = 24.0,
        player_id: str = "player",
    ) -> Consequence:
        """Create and persist a new consequence scheduled for the future.

        Args:
            consequence_type: Semantic category.
            source_scene: Scene originating the consequence.
            target_scene: Scene where it should fire.
            description: Human-readable summary.
            payload: Type-specific data dict.
            delay_hours: Hours from now until the consequence fires; default 24.
            player_id: Player this applies to; default ``"player"``.

        Returns:
            The newly scheduled :class:`Consequence`.
        """
        now = time.time()
        consequence = Consequence(
            id=str(uuid.uuid4()),
            consequence_type=consequence_type,
            source_scene=source_scene,
            target_scene=target_scene,
            player_id=player_id,
            description=description,
            payload=dict(payload),
            scheduled_at=now + delay_hours * 3600,
            created_at=now,
        )
        self._save(consequence)
        logger.debug(
            "Scheduled consequence %s (%s) for %s in %.1fh.",
            consequence.id,
            consequence_type.value,
            target_scene or "any scene",
            delay_hours,
        )
        return consequence

    def poll(
        self, scene: str = "", player_id: str = "player"
    ) -> List[Consequence]:
        """Return all due, unfired consequences for *scene* and *player_id*.

        Does **not** mark them as fired — the caller must call
        :meth:`mark_fired` after execution.

        Args:
            scene: Restrict to consequences targeting this scene.  Empty
                string matches all scenes.
            player_id: Player filter; defaults to ``"player"``.

        Returns:
            List of due :class:`Consequence` objects, unsorted.
        """
        all_consequences = self._list_all()
        due = []
        for c in all_consequences:
            if c.player_id != player_id:
                continue
            if scene and c.target_scene and c.target_scene != scene:
                continue
            if c.is_due():
                due.append(c)
        logger.debug(
            "poll(scene=%r, player=%r): %d due of %d total.",
            scene,
            player_id,
            len(due),
            len(all_consequences),
        )
        return due

    def mark_fired(self, consequence_id: str) -> None:
        """Mark a consequence as fired and persist the update to Nexus.

        Args:
            consequence_id: The ``id`` of the :class:`Consequence` to mark.
        """
        nexus_id = self._find_nexus_id(consequence_id)
        if not nexus_id:
            logger.warning(
                "ConsequenceStore.mark_fired: no Nexus entry found for %r.",
                consequence_id,
            )
            return
        try:
            # Fetch current content, update fired fields, write back.
            results = self._nexus.search(
                self._nexus_title(consequence_id), limit=2
            )
            for r in results:
                if r.get("id") == nexus_id:
                    try:
                        data = json.loads(r.get("content", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    data["fired"] = True
                    data["fired_at"] = time.time()
                    self._nexus.update_entry(nexus_id, content=json.dumps(data))
                    logger.debug("Marked consequence %s as fired.", consequence_id)
                    return
        except Exception as exc:
            logger.warning(
                "ConsequenceStore.mark_fired: Nexus update failed — %s", exc
            )

    def get_pending(
        self, scene: str = "", player_id: str = "player"
    ) -> List[Consequence]:
        """Return consequences that are scheduled but not yet due.

        These are upcoming consequences the player may still be unaware of.

        Args:
            scene: Optional scene filter (empty = all scenes).
            player_id: Player filter; defaults to ``"player"``.

        Returns:
            List of pending :class:`Consequence` objects.
        """
        now = time.time()
        all_consequences = self._list_all()
        pending = []
        for c in all_consequences:
            if c.player_id != player_id:
                continue
            if scene and c.target_scene and c.target_scene != scene:
                continue
            if not c.fired and c.scheduled_at > now:
                pending.append(c)
        return pending

    def get_history(
        self, player_id: str = "player", limit: int = 20
    ) -> List[Consequence]:
        """Return fired consequences for *player_id*, newest first.

        Args:
            player_id: Player filter; defaults to ``"player"``.
            limit: Maximum number of entries to return; defaults to 20.

        Returns:
            List of fired :class:`Consequence` objects sorted by
            :attr:`~Consequence.fired_at` descending.
        """
        all_consequences = self._list_all()
        fired = [c for c in all_consequences if c.player_id == player_id and c.fired]
        fired.sort(key=lambda c: c.fired_at or 0.0, reverse=True)
        return fired[:limit]

    def cancel(self, consequence_id: str) -> bool:
        """Cancel and delete a pending consequence from Nexus.

        Args:
            consequence_id: The ``id`` of the :class:`Consequence` to cancel.

        Returns:
            ``True`` if the entry was found and deleted, ``False`` otherwise.
        """
        nexus_id = self._find_nexus_id(consequence_id)
        if not nexus_id:
            logger.debug(
                "ConsequenceStore.cancel: no entry found for %r.", consequence_id
            )
            return False
        try:
            result = self._nexus.delete_entry(nexus_id)
            if result:
                logger.debug("Cancelled consequence %s.", consequence_id)
            return bool(result)
        except Exception as exc:
            logger.warning(
                "ConsequenceStore.cancel: Nexus delete failed — %s", exc
            )
            return False

    # ── Domain helpers ─────────────────────────────────────────────────────────

    def build_debt_consequence(
        self,
        scene: str,
        amount: int,
        debtor: str,
        creditor_char: str,
    ) -> Consequence:
        """Schedule a CONTACT consequence for a debt call-in (24 h delay).

        The creditor character will contact the player in the lounge the
        following day to collect.

        Args:
            scene: Source scene where the debt was incurred.
            amount: Debt amount in credits.
            debtor: Player or character ID who owes the debt.
            creditor_char: Character ID of the creditor (e.g. ``"mira"``).

        Returns:
            The newly scheduled :class:`Consequence`.
        """
        return self.schedule(
            consequence_type=ConsequenceType.CONTACT,
            source_scene=scene,
            target_scene="lounge",
            description=(
                f"{creditor_char} calls in {debtor}'s debt of {amount} cr."
            ),
            payload={
                "creditor": creditor_char,
                "debtor": debtor,
                "amount": amount,
                "action": "collect_debt",
            },
            delay_hours=24.0,
        )

    def build_heist_payout(self, scene: str, amount: int) -> Consequence:
        """Schedule an ECONOMY_TRANSACTION consequence for a fence cut (8 h delay).

        The player's cut of the heist payout arrives via the fence within
        8 hours.

        Args:
            scene: Source scene where the heist completed.
            amount: Total payout in credits (player receives their share).

        Returns:
            The newly scheduled :class:`Consequence`.
        """
        return self.schedule(
            consequence_type=ConsequenceType.ECONOMY_TRANSACTION,
            source_scene=scene,
            target_scene="",
            description=f"Fence cut of {amount} cr arrives from {scene} heist.",
            payload={
                "amount": amount,
                "source": "fence",
                "origin_scene": scene,
                "action": "credit",
            },
            delay_hours=8.0,
        )


# ============================================================================
#  Singleton
# ============================================================================

_store_instance: Optional[ConsequenceStore] = None
_store_lock = threading.Lock()


def get_consequence_store() -> ConsequenceStore:
    """Return the process-global :class:`ConsequenceStore` singleton.

    Thread-safe via double-checked locking.

    Returns:
        The shared :class:`ConsequenceStore` instance.
    """
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = ConsequenceStore()
                logger.info("ConsequenceStore singleton created.")
    return _store_instance
