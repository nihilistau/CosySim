"""Investigation board mechanic for CosySim v0.68 "Dark Renaissance".

Maintains a graph of clues and connections persisted in Nexus.  The NLM
(via ``nexus_client.ask``) can reason over all revealed clues to produce
deductions.

The frontend renders the board as a glass-canvas pinboard: draggable cards
connected by CSS strings whose colour and opacity reflect connection strength.

Board IDs
---------
BOARD_HACKER  = "hacker_trail"   — Phone scene: 0xGH0ST story arc
BOARD_HEIST   = "heist_plan"     — Heist scene: crew-planning board
BOARD_MYSTERY = "mystery"        — Games scene: mystery investigation
BOARD_ARENA   = "arena_analysis" — Arena scene: bet-strategy analysis

Usage::

    from engine.mechanics.investigation import (
        get_investigation_board, ClueType, BOARD_MYSTERY
    )

    board = get_investigation_board(BOARD_MYSTERY, scene="games")
    clue  = board.add_clue("Bloody Knife", "Found near the victim.", ClueType.EVIDENCE)
    board.add_connection(clue.id, other_clue.id, label="links to", strength=0.9)
    deduction = board.reason()
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from engine.events.event_bus import get_event_bus
from engine.nexus.client import get_nexus_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Board-ID constants
# ---------------------------------------------------------------------------

BOARD_HACKER: str = "hacker_trail"    # Phone: 0xGH0ST story arc
BOARD_HEIST: str = "heist_plan"       # Heist: crew-planning board
BOARD_MYSTERY: str = "mystery"        # Games: mystery investigation
BOARD_ARENA: str = "arena_analysis"   # Arena: bet-strategy analysis


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ClueType(str, Enum):
    """Semantic category of a clue card on the investigation board.

    Using ``str`` mixin keeps values JSON-serialisable without extra steps.
    """

    EVIDENCE = "EVIDENCE"
    WITNESS = "WITNESS"
    LOCATION = "LOCATION"
    PERSON = "PERSON"
    ITEM = "ITEM"
    MESSAGE = "MESSAGE"
    TIMELINE = "TIMELINE"
    THEORY = "THEORY"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Clue:
    """A single card on the investigation board.

    Attributes:
        id: Unique identifier for this clue (auto-generated).
        board_id: The board this clue belongs to.
        clue_type: Semantic category (see :class:`ClueType`).
        title: Short label shown on the card header.
        content: Full body text of the clue.
        scene: CosySim scene that owns this board.
        importance: Salience weight from 0.0 (trivial) to 1.0 (critical).
            Used by the frontend to scale the card and by ``reason()`` to
            emphasise key evidence.
        revealed: When ``False`` the card is hidden until unlocked.
        tags: Free-form metadata tags for filtering.
        position: ``{"x": int, "y": int}`` canvas co-ordinates.
        created_at: ISO-8601 UTC timestamp.
    """

    id: str
    board_id: str
    clue_type: ClueType
    title: str
    content: str
    scene: str
    importance: float
    revealed: bool = True
    tags: List[str] = field(default_factory=list)
    position: dict = field(default_factory=lambda: {"x": 100, "y": 100})
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe ``dict``.

        Returns:
            Dictionary with ``clue_type`` stored as its string value.
        """
        d = asdict(self)
        d["clue_type"] = self.clue_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Clue":
        """Deserialise from a ``dict`` produced by :meth:`to_dict`.

        Args:
            data: Raw dictionary (e.g. decoded from JSON).

        Returns:
            A reconstructed :class:`Clue` instance.
        """
        data = dict(data)
        data["clue_type"] = ClueType(data["clue_type"])
        return cls(**data)


@dataclass
class Connection:
    """A directed edge between two clues on the investigation board.

    The frontend renders this as a coloured string:
    * ``strength >= 0.7`` → bright red
    * ``strength  < 0.7`` → dim grey

    Attributes:
        id: Unique identifier for this connection.
        board_id: The board this connection belongs to.
        from_clue_id: Source clue ID.
        to_clue_id: Target clue ID.
        label: Human-readable relationship description, e.g. ``"leads to"``,
            ``"contradicts"``, ``"same person"``.
        strength: Confidence/salience weight from 0.0 to 1.0.
        created_at: ISO-8601 UTC timestamp.
    """

    id: str
    board_id: str
    from_clue_id: str
    to_clue_id: str
    label: str
    strength: float
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe ``dict``.

        Returns:
            Plain dictionary of all fields.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Connection":
        """Deserialise from a ``dict`` produced by :meth:`to_dict`.

        Args:
            data: Raw dictionary.

        Returns:
            A reconstructed :class:`Connection` instance.
        """
        return cls(**data)


# ---------------------------------------------------------------------------
# InvestigationBoard
# ---------------------------------------------------------------------------

class InvestigationBoard:
    """Visual investigation board: clues + connections, backed by Nexus.

    Each board has a unique ``board_id`` and is scoped to a ``scene``.
    Clues and connections are stored in-memory and mirrored to Nexus as
    ``note`` entries under ``category="investigation:{board_id}"``.

    The NLM reasoning pipeline is accessed through ``nexus_client.ask``.

    Args:
        board_id: Unique identifier for this board (use the ``BOARD_*``
            constants when possible).
        scene: CosySim scene that owns this board (e.g. ``"games"``).
        nexus_client: Optional pre-constructed client; defaults to the
            process singleton from :func:`engine.nexus.client.get_nexus_client`.

    Example::

        board = InvestigationBoard("mystery", scene="games")
        c1 = board.add_clue("Victim", "Found unconscious", ClueType.PERSON)
        c2 = board.add_clue("Knife", "Bloody, monogrammed 'V'", ClueType.ITEM)
        board.add_connection(c1.id, c2.id, label="linked by", strength=0.85)
        print(board.reason())
    """

    def __init__(
        self,
        board_id: str,
        scene: str = "",
        nexus_client=None,
    ) -> None:
        self.board_id = board_id
        self.scene = scene
        self._nexus = nexus_client or get_nexus_client()

        self._clues: Dict[str, Clue] = {}
        self._connections: Dict[str, Connection] = {}
        self._deduction_count: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Clue management                                                      #
    # ------------------------------------------------------------------ #

    def add_clue(
        self,
        title: str,
        content: str,
        clue_type: ClueType = ClueType.EVIDENCE,
        importance: float = 0.5,
        tags: List[str] = None,
        position: dict = None,
        revealed: bool = True,
    ) -> Clue:
        """Create and persist a new clue card.

        Args:
            title: Short label shown on the card header.
            content: Full body text of the clue.
            clue_type: Semantic category; defaults to
                :attr:`ClueType.EVIDENCE`.
            importance: Salience weight 0.0–1.0; defaults to ``0.5``.
            tags: Optional list of tag strings for filtering.
            position: ``{"x": int, "y": int}`` canvas position; defaults to
                ``{"x": 100, "y": 100}``.
            revealed: Whether the card is immediately visible; defaults to
                ``True``.

        Returns:
            The newly created :class:`Clue` instance.
        """
        clue_id = f"clue_{uuid.uuid4().hex[:12]}"
        clue = Clue(
            id=clue_id,
            board_id=self.board_id,
            clue_type=clue_type,
            title=title,
            content=content,
            scene=self.scene,
            importance=float(importance),
            revealed=revealed,
            tags=list(tags) if tags else [],
            position=dict(position) if position else {"x": 100, "y": 100},
        )

        with self._lock:
            self._clues[clue_id] = clue

        self._persist_clue(clue)
        logger.debug("Added clue %r (%s) to board %r.", title, clue_type.value, self.board_id)
        return clue

    def reveal_clue(self, clue_id: str) -> Optional[Clue]:
        """Reveal a hidden clue and fire an EventBus notification.

        Args:
            clue_id: The :attr:`Clue.id` to reveal.

        Returns:
            The updated :class:`Clue`, or ``None`` if *clue_id* was not found.
        """
        with self._lock:
            clue = self._clues.get(clue_id)
            if clue is None:
                logger.warning(
                    "reveal_clue: clue %r not found on board %r.", clue_id, self.board_id
                )
                return None
            clue.revealed = True

        self._persist_clue(clue)

        try:
            bus = get_event_bus()
            bus.publish(
                "investigation.clue_revealed",
                {
                    "board_id": self.board_id,
                    "clue_id": clue_id,
                    "title": clue.title,
                    "clue_type": clue.clue_type.value,
                },
                scene=self.scene,
            )
        except Exception:
            logger.exception("Failed to publish investigation.clue_revealed for %r.", clue_id)

        logger.debug("Revealed clue %r on board %r.", clue_id, self.board_id)
        return clue

    def add_theory(self, theory: str) -> Clue:
        """Convenience wrapper: add a :attr:`ClueType.THEORY` clue.

        Args:
            theory: The theory text (used as both title prefix and content).

        Returns:
            The newly created :class:`Clue`.
        """
        short_title = theory[:60].rstrip() + ("…" if len(theory) > 60 else "")
        return self.add_clue(
            title=f"Theory: {short_title}",
            content=theory,
            clue_type=ClueType.THEORY,
            importance=0.6,
            tags=["theory"],
        )

    # ------------------------------------------------------------------ #
    # Connection management                                                #
    # ------------------------------------------------------------------ #

    def add_connection(
        self,
        from_id: str,
        to_id: str,
        label: str = "",
        strength: float = 0.7,
    ) -> Connection:
        """Create and persist a directed connection between two clues.

        Args:
            from_id: Source :attr:`Clue.id`.
            to_id: Target :attr:`Clue.id`.
            label: Human-readable relationship (e.g. ``"leads to"``).
            strength: Confidence weight 0.0–1.0; defaults to ``0.7``.

        Returns:
            The newly created :class:`Connection`.
        """
        conn_id = f"conn_{uuid.uuid4().hex[:12]}"
        connection = Connection(
            id=conn_id,
            board_id=self.board_id,
            from_clue_id=from_id,
            to_clue_id=to_id,
            label=label,
            strength=float(strength),
        )

        with self._lock:
            self._connections[conn_id] = connection

        self._persist_connection(connection)
        logger.debug(
            "Added connection %r→%r (%r) on board %r.",
            from_id, to_id, label, self.board_id,
        )
        return connection

    # ------------------------------------------------------------------ #
    # Query helpers                                                        #
    # ------------------------------------------------------------------ #

    def get_clues(self, revealed_only: bool = True) -> List[Clue]:
        """Return clues on this board.

        Args:
            revealed_only: When ``True`` (default) only revealed clues are
                returned.  Pass ``False`` to include hidden cards.

        Returns:
            Sorted list of :class:`Clue` objects (descending importance).
        """
        with self._lock:
            clues = list(self._clues.values())

        if revealed_only:
            clues = [c for c in clues if c.revealed]

        return sorted(clues, key=lambda c: c.importance, reverse=True)

    def get_connections(self) -> List[Connection]:
        """Return all connections on this board.

        Returns:
            List of :class:`Connection` objects in insertion order.
        """
        with self._lock:
            return list(self._connections.values())

    def get_board_state(self) -> dict:
        """Snapshot of the full board state, ready for Socket.IO emission.

        Returns:
            Dictionary with keys:
            ``board_id``, ``scene``, ``clues``, ``connections``,
            ``deduction_count``.

        Example::

            state = board.get_board_state()
            socketio.emit("investigation_update", state, room=session_id)
        """
        return {
            "board_id": self.board_id,
            "scene": self.scene,
            "clues": [c.to_dict() for c in self.get_clues(revealed_only=False)],
            "connections": [cn.to_dict() for cn in self.get_connections()],
            "deduction_count": self._deduction_count,
        }

    # ------------------------------------------------------------------ #
    # NLM reasoning                                                        #
    # ------------------------------------------------------------------ #

    def reason(self) -> str:
        """Invoke NLM reasoning over all revealed clues and connections.

        Constructs a structured prompt from the current board state and
        passes it to :meth:`engine.nexus.client.NexusClient.ask`.  The
        response is returned as a plain string.

        Returns:
            Deduction string from the NLM (may be empty if Nexus is
            unavailable).

        Raises:
            No exceptions — failures are caught, logged, and an empty string
            is returned so the game loop never crashes.
        """
        revealed_clues = self.get_clues(revealed_only=True)
        connections = self.get_connections()

        if not revealed_clues:
            logger.debug("reason() called on board %r with no revealed clues.", self.board_id)
            return ""

        clue_list = "\n".join(
            f"  [{c.clue_type.value}] {c.title} (importance={c.importance:.1f}): {c.content}"
            for c in revealed_clues
        )
        connection_list = "\n".join(
            f"  {c.from_clue_id} --[{c.label}]--> {c.to_clue_id} (strength={c.strength:.2f})"
            for c in connections
        ) or "  (none)"

        prompt = (
            f"Analyse these clues and connections from the {self.scene} investigation board.\n"
            "What can be deduced? What patterns emerge? What is most suspicious?\n"
            f"Clues:\n{clue_list}\n"
            f"Connections:\n{connection_list}\n"
            "Provide a detailed deduction in 2-3 paragraphs."
        )

        try:
            response = self._nexus.ask(prompt, category=f"investigation:{self.board_id}")
            deduction: str = response.get("answer", "") or str(response)
        except Exception:
            logger.exception("NLM reasoning failed for board %r.", self.board_id)
            return ""

        self._deduction_count += 1
        logger.debug(
            "Reasoning complete for board %r (deduction #%d).",
            self.board_id,
            self._deduction_count,
        )
        return deduction

    # ------------------------------------------------------------------ #
    # Export / clear                                                       #
    # ------------------------------------------------------------------ #

    def export(self) -> dict:
        """Full export: board state plus raw clue/connection dicts.

        Returns:
            Dictionary containing the full board state and individual
            serialised records, suitable for saving to disk or sending to a
            remote client.
        """
        return {
            "board_state": self.get_board_state(),
            "clues": [c.to_dict() for c in self.get_clues(revealed_only=False)],
            "connections": [cn.to_dict() for cn in self.get_connections()],
        }

    def clear(self) -> None:
        """Delete all clues and connections from both memory and Nexus.

        Uses ``list_entries`` to find all Nexus entries under
        ``category="investigation:{board_id}"`` and deletes them
        individually.  Local in-memory state is then wiped.

        Returns:
            None
        """
        category = f"investigation:{self.board_id}"
        try:
            entries = self._nexus.list_entries(category=category, limit=500)
            for entry in entries:
                entry_id = entry.get("id") or entry.get("_id", "")
                if entry_id:
                    self._nexus.delete_entry(entry_id)
            logger.debug(
                "Cleared %d Nexus entries for board %r.", len(entries), self.board_id
            )
        except Exception:
            logger.exception("Failed to clear Nexus entries for board %r.", self.board_id)

        with self._lock:
            self._clues.clear()
            self._connections.clear()
            self._deduction_count = 0

    # ------------------------------------------------------------------ #
    # Private persistence helpers                                          #
    # ------------------------------------------------------------------ #

    def _persist_clue(self, clue: Clue) -> None:
        """Save (or update) a clue as a Nexus entry (best-effort).

        Args:
            clue: The :class:`Clue` to persist.
        """
        try:
            self._nexus.add_entry(
                title=f"clue:{clue.id}",
                content=_clue_to_nexus_content(clue),
                content_type="note",
                category=f"investigation:{self.board_id}",
                tags=["investigation", "clue", clue.clue_type.value.lower()] + clue.tags,
                created_by="investigation",
            )
        except Exception:
            logger.exception("Failed to persist clue %r to Nexus.", clue.id)

    def _persist_connection(self, connection: Connection) -> None:
        """Save a connection as a Nexus entry (best-effort).

        Args:
            connection: The :class:`Connection` to persist.
        """
        try:
            self._nexus.add_entry(
                title=f"connection:{connection.id}",
                content=_connection_to_nexus_content(connection),
                content_type="note",
                category=f"investigation:{self.board_id}",
                tags=["investigation", "connection"],
                created_by="investigation",
            )
        except Exception:
            logger.exception("Failed to persist connection %r to Nexus.", connection.id)


# ---------------------------------------------------------------------------
# Private formatting helpers
# ---------------------------------------------------------------------------

def _clue_to_nexus_content(clue: Clue) -> str:
    """Format a :class:`Clue` as a human-readable Nexus note body.

    Args:
        clue: The clue to format.

    Returns:
        Multi-line string suitable for ``NexusClient.add_entry`` content.
    """
    return (
        f"board_id: {clue.board_id}\n"
        f"clue_type: {clue.clue_type.value}\n"
        f"title: {clue.title}\n"
        f"scene: {clue.scene}\n"
        f"importance: {clue.importance}\n"
        f"revealed: {clue.revealed}\n"
        f"tags: {clue.tags}\n"
        f"position: {clue.position}\n"
        f"created_at: {clue.created_at}\n"
        f"content: {clue.content}"
    )


def _connection_to_nexus_content(connection: Connection) -> str:
    """Format a :class:`Connection` as a human-readable Nexus note body.

    Args:
        connection: The connection to format.

    Returns:
        Multi-line string suitable for ``NexusClient.add_entry`` content.
    """
    return (
        f"board_id: {connection.board_id}\n"
        f"from_clue_id: {connection.from_clue_id}\n"
        f"to_clue_id: {connection.to_clue_id}\n"
        f"label: {connection.label}\n"
        f"strength: {connection.strength}\n"
        f"created_at: {connection.created_at}"
    )


# ---------------------------------------------------------------------------
# Per-board singleton factory
# ---------------------------------------------------------------------------

_boards: Dict[str, "InvestigationBoard"] = {}
_boards_lock = threading.Lock()


def get_investigation_board(board_id: str, scene: str = "") -> InvestigationBoard:
    """Return (or create) the per-board :class:`InvestigationBoard` singleton.

    Each unique *board_id* maps to exactly one ``InvestigationBoard``
    instance for the lifetime of the process.  Calling this function a second
    time with the same *board_id* returns the cached instance even if *scene*
    differs.

    Args:
        board_id: Unique board identifier (use the ``BOARD_*`` constants).
        scene: CosySim scene; only used when creating a fresh board.

    Returns:
        The shared :class:`InvestigationBoard` for *board_id*.

    Example::

        board = get_investigation_board(BOARD_MYSTERY, scene="games")
    """
    if board_id in _boards:
        return _boards[board_id]

    with _boards_lock:
        if board_id not in _boards:
            _boards[board_id] = InvestigationBoard(board_id=board_id, scene=scene)
            logger.info("Created InvestigationBoard singleton for board_id=%r.", board_id)
    return _boards[board_id]
