"""
Persistent character memory module for CosySim v0.68 'Dark Renaissance'.

Characters remember players across sessions via semantic search backed by
Nexus. When a player enters a scene the CharacterMemoryInterceptor injects
the most relevant memories into the system prompt before the LLM is called.

Example::

    from engine.characters.memory import get_character_memory

    mem = get_character_memory("luna")
    mem.remember(
        "The player asked Luna to wear the red dress",
        player_id="player",
        emotional_weight=0.8,
        scene="bedroom",
        tags=["wardrobe", "request"],
    )

    # later, before a response:
    memories = mem.recall("what is the player wearing", player_id="player")
    summary  = mem.get_memory_summary(player_id="player")
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from engine.nexus.client import get_nexus_client
from engine.mcp.comms_framework import InterceptorBase, ResponseContext

logger = logging.getLogger(__name__)

# ── Module-level singleton registry ──────────────────────────────────────────
_character_memory_registry: Dict[str, "CharacterMemory"] = {}

# ── Constants ────────────────────────────────────────────────────────────────
_CONTENT_TYPE = "memory"
_RECALL_LIMIT_DEFAULT = 5
_RECENT_LIMIT_DEFAULT = 10
_SUMMARY_LIMIT = 10


# ══════════════════════════════════════════════════════════════════════════════
#  MemoryEntry
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class MemoryEntry:
    """A single persistent memory belonging to a character.

    Attributes:
        id: Unique UUID for this memory entry.
        character_id: The character who holds this memory.
        player_id: The player this memory is about.
        content: Natural-language description of what happened.
        emotional_weight: Salience score from 0.0 (trivial) to 1.0 (vivid).
        scene: Scene in which the memory was formed.
        created_at: ISO-8601 timestamp of creation.
        accessed_at: ISO-8601 timestamp of last retrieval.
        access_count: How many times this memory has been recalled.
        tags: Free-form labels for filtering / categorisation.
    """

    id: str
    character_id: str
    player_id: str
    content: str
    emotional_weight: float
    scene: str
    created_at: str
    accessed_at: str
    access_count: int
    tags: List[str] = field(default_factory=list)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize this entry to a plain dictionary.

        Returns:
            All fields as a JSON-serialisable dict.
        """
        return {
            "id": self.id,
            "character_id": self.character_id,
            "player_id": self.player_id,
            "content": self.content,
            "emotional_weight": self.emotional_weight,
            "scene": self.scene,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        """Deserialise from a plain dictionary.

        Args:
            d: Dictionary with memory entry fields (missing fields get sane
               defaults so partial Nexus payloads are handled gracefully).

        Returns:
            A fully-populated MemoryEntry instance.
        """
        return cls(
            id=d.get("id", ""),
            character_id=d.get("character_id", ""),
            player_id=d.get("player_id", "player"),
            content=d.get("content", ""),
            emotional_weight=float(d.get("emotional_weight", 0.5)),
            scene=d.get("scene", ""),
            created_at=d.get("created_at", ""),
            accessed_at=d.get("accessed_at", ""),
            access_count=int(d.get("access_count", 0)),
            tags=list(d.get("tags", [])),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CharacterMemory
# ══════════════════════════════════════════════════════════════════════════════


class CharacterMemory:
    """Manages persistent memories for a single character, backed by Nexus.

    Memories are stored as Nexus knowledge entries with:

    * ``content_type = "memory"``
    * ``category    = "character_memory:{character_id}"``
    * ``title       = "memory:{character_id}:{entry_id}"``

    The Nexus entry's ``content`` field holds the full :class:`MemoryEntry`
    serialised as JSON, which enables both structured filtering and
    semantic search over the natural-language ``content`` field inside that
    JSON.

    Args:
        character_id: Identifier for the character owning these memories.
        nexus_client: Optional pre-built client (used in tests / DI).
    """

    def __init__(self, character_id: str, nexus_client=None) -> None:
        self._character_id = character_id
        self._nexus = nexus_client or get_nexus_client()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @property
    def _category(self) -> str:
        return f"character_memory:{self._character_id}"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _parse_nexus_entry(self, raw: dict) -> Optional[MemoryEntry]:
        """Parse a raw Nexus entry dict into a MemoryEntry.

        Args:
            raw: A single dict from ``nexus.search()`` or ``nexus.list_entries()``.

        Returns:
            Parsed MemoryEntry, or None if the content cannot be decoded.
        """
        try:
            data = json.loads(raw.get("content", "{}"))
            return MemoryEntry.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.debug(
                "CharacterMemory[%s]: could not parse Nexus entry %s — %s",
                self._character_id,
                raw.get("id"),
                exc,
            )
            return None

    def _bump_access(self, entry: MemoryEntry) -> MemoryEntry:
        """Update access tracking on an entry and persist the change.

        Args:
            entry: The memory entry that was just recalled.

        Returns:
            The updated entry (mutation is in-place as well).
        """
        entry.accessed_at = self._now_iso()
        entry.access_count += 1
        nexus_title = f"memory:{self._character_id}:{entry.id}"
        # Find the Nexus entry by title to get its Nexus id for update_entry
        results = self._nexus.search(nexus_title, limit=1)
        for r in results:
            if r.get("title") == nexus_title:
                self._nexus.update_entry(r["id"], content=json.dumps(entry.to_dict()))
                break
        return entry

    # ── Public API ────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        player_id: str = "player",
        emotional_weight: float = 0.5,
        scene: str = "",
        tags: List[str] = None,
    ) -> MemoryEntry:
        """Create and persist a new memory.

        Args:
            content: Natural-language description of what happened, e.g.
                ``"The player asked you to wear the red dress"``.
            player_id: Identifier of the player this memory concerns.
            emotional_weight: Salience from 0.0 (trivial) to 1.0 (unforgettable).
            scene: Scene name in which the memory was formed.
            tags: Optional list of string labels for later filtering.

        Returns:
            The newly created MemoryEntry (already persisted in Nexus).
        """
        now = self._now_iso()
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            character_id=self._character_id,
            player_id=player_id,
            content=content,
            emotional_weight=max(0.0, min(1.0, emotional_weight)),
            scene=scene,
            created_at=now,
            accessed_at=now,
            access_count=0,
            tags=list(tags or []),
        )

        nexus_id = self._nexus.add_entry(
            title=f"memory:{self._character_id}:{entry.id}",
            content=json.dumps(entry.to_dict()),
            content_type=_CONTENT_TYPE,
            category=self._category,
            tags=entry.tags + [f"player:{player_id}", f"character:{self._character_id}"],
            created_by="cosysim",
        )

        if nexus_id:
            logger.debug(
                "CharacterMemory[%s]: stored memory %s (weight=%.2f)",
                self._character_id,
                entry.id,
                emotional_weight,
            )
        else:
            logger.warning(
                "CharacterMemory[%s]: Nexus failed to persist memory (Nexus unavailable?)",
                self._character_id,
            )

        return entry

    def recall(
        self,
        context: str,
        player_id: str = "player",
        limit: int = _RECALL_LIMIT_DEFAULT,
    ) -> List[MemoryEntry]:
        """Retrieve memories semantically relevant to a context string.

        Performs a Nexus semantic search, filters to this character and player,
        then re-ranks by combining Nexus relevance order with emotional_weight.

        Args:
            context: The query text to search against (e.g. the player's last
                message, or a topic).
            player_id: Restrict results to this player.
            limit: Maximum number of memories to return.

        Returns:
            Up to ``limit`` MemoryEntry objects sorted by relevance ×
            emotional_weight (descending).
        """
        raw_results = self._nexus.search(context, limit=limit * 4)

        entries: List[tuple[float, MemoryEntry]] = []
        for rank, raw in enumerate(raw_results):
            entry = self._parse_nexus_entry(raw)
            if entry is None:
                continue
            if entry.character_id != self._character_id:
                continue
            if entry.player_id != player_id:
                continue
            # Combine positional relevance (inverse rank) with emotional_weight
            relevance_score = (1.0 / (rank + 1)) * (0.5 + 0.5 * entry.emotional_weight)
            entries.append((relevance_score, entry))

        entries.sort(key=lambda t: t[0], reverse=True)
        top = [e for _, e in entries[:limit]]

        for entry in top:
            self._bump_access(entry)

        return top

    def recall_recent(
        self,
        player_id: str = "player",
        limit: int = _RECENT_LIMIT_DEFAULT,
    ) -> List[MemoryEntry]:
        """Return the most recently created memories for a player.

        Args:
            player_id: Restrict results to this player.
            limit: Maximum number of entries to return.

        Returns:
            Up to ``limit`` MemoryEntry objects sorted by created_at descending.
        """
        raw_results = self._nexus.list_by_type(
            content_type=_CONTENT_TYPE,
            category=self._category,
            limit=limit * 4,
        )

        entries: List[MemoryEntry] = []
        for raw in raw_results:
            entry = self._parse_nexus_entry(raw)
            if entry is None:
                continue
            if entry.player_id != player_id:
                continue
            entries.append(entry)

        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def get_memory_summary(self, player_id: str = "player") -> str:
        """Build a system-prompt-ready memory block for the most vivid memories.

        Retrieves the top emotionally-weighted memories and formats them as a
        series of "You remember: …" lines.

        Args:
            player_id: The player whose memories to summarise.

        Returns:
            Multi-line string such as::

                You remember: The player asked you to wear the red dress.
                You remember: The player gave you a gift last Tuesday.
        """
        all_entries = self.get_all(player_id=player_id)
        if not all_entries:
            return ""

        top = sorted(all_entries, key=lambda e: e.emotional_weight, reverse=True)[
            :_SUMMARY_LIMIT
        ]
        lines = [f"You remember: {e.content}" for e in top]
        return "\n".join(lines)

    def summarize(self, player_id: str = "player") -> str:
        """Ask Nexus/NLM to synthesise a relationship summary from stored memories.

        Args:
            player_id: The player whose relationship history to summarise.

        Returns:
            A prose relationship summary generated by the NLM, or an empty
            string if Nexus is unavailable.
        """
        entries = self.get_all(player_id=player_id)
        if not entries:
            return ""

        memory_lines = "\n".join(
            f"- {e.content} (weight={e.emotional_weight:.2f})" for e in entries
        )
        question = (
            f"Summarize your relationship history with the player based on: {memory_lines}"
        )
        result = self._nexus.ask(question)
        # ask() returns a dict; extract the answer string from common keys
        return (
            result.get("answer")
            or result.get("response")
            or result.get("text")
            or ""
        )

    def forget_old(self, days: int = 30, player_id: str = "player") -> int:
        """Delete memories older than ``days`` for this character and player.

        Args:
            days: Age threshold in days; entries older than this are removed.
            player_id: Restrict deletion to this player's memories.

        Returns:
            Number of entries successfully deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        all_entries = self.get_all(player_id=player_id)

        deleted = 0
        for entry in all_entries:
            try:
                created = datetime.fromisoformat(entry.created_at)
                # Ensure timezone-aware comparison
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if created < cutoff:
                nexus_title = f"memory:{self._character_id}:{entry.id}"
                results = self._nexus.search(nexus_title, limit=1)
                for raw in results:
                    if raw.get("title") == nexus_title:
                        if self._nexus.delete_entry(raw["id"]):
                            deleted += 1
                            logger.debug(
                                "CharacterMemory[%s]: forgot old entry %s",
                                self._character_id,
                                entry.id,
                            )

        return deleted

    def forget_entry(self, entry_id: str) -> bool:
        """Delete a specific memory entry by its MemoryEntry id.

        Args:
            entry_id: The ``MemoryEntry.id`` (UUID) to delete.

        Returns:
            True if the entry was found and deleted, False otherwise.
        """
        nexus_title = f"memory:{self._character_id}:{entry_id}"
        results = self._nexus.search(nexus_title, limit=1)
        for raw in results:
            if raw.get("title") == nexus_title:
                success = self._nexus.delete_entry(raw["id"])
                if success:
                    logger.debug(
                        "CharacterMemory[%s]: deleted entry %s",
                        self._character_id,
                        entry_id,
                    )
                return success
        logger.debug(
            "CharacterMemory[%s]: forget_entry(%s) — not found in Nexus",
            self._character_id,
            entry_id,
        )
        return False

    def get_all(self, player_id: str = "player") -> List[MemoryEntry]:
        """Return all stored memories for this character and player.

        Args:
            player_id: Restrict results to this player.

        Returns:
            All matching MemoryEntry objects, unsorted.
        """
        raw_results = self._nexus.list_by_type(
            content_type=_CONTENT_TYPE,
            category=self._category,
            limit=1000,
        )

        entries: List[MemoryEntry] = []
        for raw in raw_results:
            entry = self._parse_nexus_entry(raw)
            if entry is None:
                continue
            if entry.player_id != player_id:
                continue
            entries.append(entry)

        return entries


# ══════════════════════════════════════════════════════════════════════════════
#  CharacterMemoryInterceptor
# ══════════════════════════════════════════════════════════════════════════════


class CharacterMemoryInterceptor(InterceptorBase):
    """Pre-call interceptor that injects relevant memories into the system prompt.

    Reads ``character_id``, ``player_id``, and ``user_message`` from the
    :class:`~engine.mcp.comms_framework.ResponseContext` and prepends a
    ``[CHARACTER MEMORY]`` block to ``ctx["system_prompt"]`` when matching
    memories are found.

    Priority 7 places this between NaturalMoodDriftInterceptor (5) and
    CharacterRegistryInterceptor (8), so character identity is injected
    *after* memories have been added.

    Args:
        character_registry: Optional pre-built dict of ``{character_id:
            CharacterMemory}``.  Missing characters are lazily initialised.

    Example::

        from engine.characters.memory import CharacterMemoryInterceptor
        interceptor = CharacterMemoryInterceptor()
        governor.pipeline.add(interceptor)
    """

    name = "character_memory"
    priority = 7

    def __init__(self, character_registry: Optional[Dict[str, CharacterMemory]] = None) -> None:
        self._registry: Dict[str, CharacterMemory] = dict(character_registry or {})

    def get_memory(self, character_id: str) -> CharacterMemory:
        """Return (lazily creating) the CharacterMemory for ``character_id``.

        Args:
            character_id: Identifier of the character.

        Returns:
            The :class:`CharacterMemory` instance for that character.
        """
        if character_id not in self._registry:
            self._registry[character_id] = CharacterMemory(character_id)
        return self._registry[character_id]

    def pre_call(self, ctx: ResponseContext) -> None:
        """Inject relevant memories into the system prompt before LLM call.

        Reads character context from the ResponseContext, performs a semantic
        recall, and prepends a ``[CHARACTER MEMORY] … [/CHARACTER MEMORY]``
        block to ``ctx["system_prompt"]``.

        Args:
            ctx: Mutable interaction context bag.
        """
        character_id: str = ctx.get("character_id") or ctx.get("agent_id", "")
        if not character_id:
            return

        player_id: str = ctx.get("player_id", "player")
        last_message: str = ctx.get("last_message") or ctx.get("user_message", "")

        memory = self.get_memory(character_id)
        try:
            entries = memory.recall(last_message, player_id=player_id, limit=5)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "CharacterMemoryInterceptor: recall failed for %s — %s",
                character_id,
                exc,
            )
            return

        if not entries:
            return

        summary = memory.get_memory_summary(player_id=player_id)
        if not summary:
            return

        memory_block = f"[CHARACTER MEMORY]\n{summary}\n[/CHARACTER MEMORY]"
        existing: str = ctx.get("system_prompt", "")
        ctx["system_prompt"] = f"{memory_block}\n\n{existing}" if existing else memory_block

        logger.debug(
            "CharacterMemoryInterceptor: injected %d memories for %s",
            len(entries),
            character_id,
        )

    def post_call(self, ctx: ResponseContext) -> None:
        """Pass-through — no post-call processing required.

        Args:
            ctx: Mutable interaction context bag.
        """


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level singleton factory
# ══════════════════════════════════════════════════════════════════════════════


def get_character_memory(character_id: str) -> CharacterMemory:
    """Return the per-character singleton :class:`CharacterMemory`.

    Creates a new instance on first access; subsequent calls return the same
    object for the lifetime of the process.

    Args:
        character_id: Identifier of the character whose memory to retrieve.

    Returns:
        The :class:`CharacterMemory` singleton for ``character_id``.
    """
    if character_id not in _character_memory_registry:
        _character_memory_registry[character_id] = CharacterMemory(character_id)
        logger.debug("CharacterMemory: created singleton for %s", character_id)
    return _character_memory_registry[character_id]
