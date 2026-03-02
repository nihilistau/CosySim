"""
nexus_memory.py — Unified memory system using Nexus KMS.

Provides long-term memory storage and retrieval for both Copilot CLI sessions
and CosySim virtual characters. Memories are namespace-separated, searchable,
and automatically managed (compaction, decay, importance scoring).

Usage:
    from engine.nexus.nexus_memory import NexusMemory

    mem = NexusMemory(namespace="agent", agent_id="lola")
    mem.remember("User prefers casual conversation", importance=0.8)
    mem.remember("User mentioned they like coffee", importance=0.5, memory_type="preference")

    relevant = mem.recall("what does the user like?", top_k=5)
    context = mem.get_context_window(max_tokens=500)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from engine.nexus.nexus_namespaces import enforce_namespace

logger = logging.getLogger(__name__)

# Memory types with default importance weights
MEMORY_TYPES = {
    "observation": 0.5,  # What happened
    "preference": 0.7,  # What user/character likes
    "fact": 0.8,  # Established facts
    "emotion": 0.6,  # Emotional states observed
    "event": 0.4,  # Events that occurred
    "decision": 0.9,  # Decisions made
    "summary": 0.7,  # Compacted summaries
    "interaction": 0.3,  # Routine interactions
    "session": 0.5,  # Session-level memories
}


class NexusMemory:
    """Nexus-backed memory system for agents and Copilot.

    Stores memories as Nexus entries with proper namespace tagging,
    importance scoring, and time decay. Provides semantic recall
    via Nexus FTS5 search.

    Args:
        namespace: Knowledge namespace ('agent', 'copilot', 'scene').
        agent_id: Identifier for the memory owner (character name, 'copilot', etc).
        nexus_url: Nexus API base URL.
    """

    def __init__(
        self,
        namespace: str = "agent",
        agent_id: str = "system",
        nexus_url: str = "http://127.0.0.1:8700",
    ) -> None:
        self._namespace = namespace
        self._agent_id = agent_id
        self._url = nexus_url
        self._session_memories: List[Dict[str, Any]] = []

    def remember(
        self,
        content: str,
        importance: float = 0.5,
        memory_type: str = "observation",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Store a memory in Nexus.

        Args:
            content: The memory content.
            importance: Importance score 0.0-1.0.
            memory_type: Type of memory (observation, preference, fact, etc).
            tags: Additional tags.
            metadata: Extra metadata dict.

        Returns:
            Entry ID if stored successfully, None otherwise.
        """
        from engine.nexus.client import get_nexus_client

        base_tags = tags or []
        all_tags = [
            self._namespace,
            "memory",
            f"agent:{self._agent_id}",
            f"type:{memory_type}",
            f"importance:{int(importance * 10)}",
        ] + base_tags

        entry = enforce_namespace(
            title=f"Memory [{self._agent_id}]: {content[:60]}",
            content=content,
            content_type="memory",
            category="memory",
            tags=all_tags,
            namespace=self._namespace,
        )

        try:
            nx = get_nexus_client(self._url)
            entry_id = nx.add_entry(
                title=entry["title"],
                content=entry["content"],
                content_type="memory",
                category="memory",
                tags=entry["tags"],
                created_by=self._agent_id,
            )

            if entry_id:
                self._session_memories.append(
                    {
                        "id": entry_id,
                        "content": content,
                        "type": memory_type,
                        "importance": importance,
                        "timestamp": time.time(),
                    }
                )
                logger.debug(
                    "NexusMemory: stored for %s: %s", self._agent_id, content[:50]
                )
                return entry_id
        except Exception as exc:
            logger.warning("NexusMemory: store failed: %s", exc)
        return None

    def recall(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Recall relevant memories via semantic search.

        Args:
            query: Search query.
            top_k: Maximum results.
            memory_type: Filter by memory type.
            min_importance: Minimum importance score.

        Returns:
            List of memory dicts with content, type, importance, timestamp.
        """
        from engine.nexus.client import get_nexus_client

        try:
            # Search Nexus for memories tagged to this agent
            search_query = f"{query} agent:{self._agent_id}"
            nx = get_nexus_client(self._url)

            results = nx.search(search_query, limit=top_k * 2)

            # Filter to this agent's memories
            memories = []
            for entry in results:
                # `entry` is a NexusEntry model. Access properties directly.
                tags = getattr(entry, "tags", [])
                tag_str = str(tags)

                if f"agent:{self._agent_id}" not in tag_str:
                    continue
                if "memory" not in tag_str:
                    continue

                # Extract importance from tags
                imp = 0.5
                for t in tags:
                    if str(t).startswith("importance:"):
                        try:
                            imp = int(str(t).split(":")[1]) / 10.0
                        except (ValueError, IndexError):
                            logger.debug("Suppressed exception", exc_info=True)

                if imp < min_importance:
                    continue

                # Extract memory type from tags
                m_type = "observation"
                for t in tags:
                    if str(t).startswith("type:"):
                        m_type = str(t).split(":")[1]

                if memory_type and m_type != memory_type:
                    continue

                memories.append(
                    {
                        "id": getattr(entry, "id", ""),
                        "content": getattr(entry, "content", ""),
                        "type": m_type,
                        "importance": imp,
                        "timestamp": time.time(),  # Real timestamp would come from entry.created_at
                    }
                )

            # Sort by importance and return top_k
            memories.sort(key=lambda x: x["importance"], reverse=True)
            return memories[:top_k]
        except Exception as exc:
            logger.debug("NexusMemory recall failed: %s", exc)
        return []

    def get_context_window(
        self,
        max_chars: int = 2000,
        include_session: bool = True,
    ) -> str:
        """Build a context string from recent and important memories.

        Args:
            max_chars: Maximum characters in the context.
            include_session: Include current session memories.

        Returns:
            Formatted memory context string.
        """
        parts: List[str] = []

        # Include current session memories (most recent first)
        if include_session and self._session_memories:
            session_mems = sorted(
                self._session_memories,
                key=lambda m: m["importance"],
                reverse=True,
            )[:5]
            parts.append("RECENT MEMORIES:")
            for m in session_mems:
                parts.append(f"  [{m['type']}] {m['content']}")

        # Get high-importance stored memories
        from engine.nexus.client import get_nexus_client

        try:
            nx = get_nexus_client(self._url)
            results = nx.search(f"agent:{self._agent_id} memory", limit=20)

            stored = [
                getattr(e, "content", "")
                for e in results
                if f"agent:{self._agent_id}" in str(getattr(e, "tags", ""))
            ]
            if stored:
                parts.append("STORED MEMORIES:")
                for mem in stored[:5]:
                    parts.append(f"  {mem[:200]}")
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        context = "\n".join(parts)
        if len(context) > max_chars:
            context = context[: max_chars - 3] + "..."
        return context

    def forget(self, entry_id: str) -> bool:
        """Remove a specific memory.

        Args:
            entry_id: The Nexus entry ID to remove.

        Returns:
            True if deleted successfully.
        """
        from engine.nexus.client import get_nexus_client

        try:
            nx = get_nexus_client(self._url)
            return nx.delete_entry(entry_id)
        except Exception:
            return False

    def compact(self, max_memories: int = 50) -> int:
        """Compact old, low-importance memories into summaries.

        Finds memories older than the most recent `max_memories` and
        summarizes them into a single compacted entry.

        Args:
            max_memories: Keep this many individual memories.

        Returns:
            Number of memories compacted.
        """
        from engine.nexus.client import get_nexus_client

        try:
            nx = get_nexus_client(self._url)
            results = nx.search(f"agent:{self._agent_id} memory", limit=200)

            # Filter to this agent's memories
            agent_memories = [
                e
                for e in results
                if f"agent:{self._agent_id}" in str(getattr(e, "tags", ""))
                and "memory" in str(getattr(e, "tags", ""))
            ]

            if len(agent_memories) <= max_memories:
                return 0

            # Sort by created_at (oldest first)
            # `created_at` in NexusEntry is a datetime object, fallback safely
            agent_memories.sort(key=lambda e: getattr(e, "created_at", None) or "")

            # Compact the oldest entries
            to_compact = agent_memories[:-max_memories]
            contents = [getattr(e, "content", "") for e in to_compact]
            summary = f"Compacted {len(to_compact)} memories: " + " | ".join(
                c[:100] for c in contents[:20] if c
            )

            # Store summary
            self.remember(summary, importance=0.6, memory_type="summary")

            # Delete compacted entries
            deleted = 0
            for e in to_compact:
                e_id = getattr(e, "id", "")
                if e_id and self.forget(e_id):
                    deleted += 1

            return deleted
        except Exception as exc:
            logger.debug("Suppressed exception during compact", exc_info=True)
            return 0

            results = r.json()
            if isinstance(results, dict):
                results = results.get("data", [])

            # Filter to this agent's memories
            agent_memories = [
                e
                for e in results
                if f"agent:{self._agent_id}" in str(e.get("tags", ""))
                and "memory" in str(e.get("tags", ""))
            ]

            if len(agent_memories) <= max_memories:
                return 0

            # Sort by created_at (oldest first)
            agent_memories.sort(key=lambda e: e.get("created_at", ""))

            # Compact the oldest entries
            to_compact = agent_memories[:-max_memories]
            contents = [e.get("content", "") for e in to_compact]
            summary = f"Compacted {len(to_compact)} memories: " + " | ".join(
                c[:100] for c in contents[:20]
            )

            # Store summary
            self.remember(summary, importance=0.6, memory_type="summary")

            # Delete compacted entries
            deleted = 0
            for e in to_compact:
                if self.forget(e.get("id", "")):
                    deleted += 1

            logger.info(
                "NexusMemory: compacted %d memories for %s",
                deleted,
                self._agent_id,
            )
            return deleted

        except Exception as exc:
            logger.warning("NexusMemory: compact failed: %s", exc)
            return 0

    @property
    def session_count(self) -> int:
        """Number of memories stored in current session."""
        return len(self._session_memories)


# ══════════════════════════════════════════════════════════════════════
#  Convenience factories
# ══════════════════════════════════════════════════════════════════════


def get_copilot_memory() -> NexusMemory:
    """Get a NexusMemory instance for Copilot CLI sessions."""
    return NexusMemory(namespace="copilot", agent_id="copilot")


def get_character_memory(character_id: str) -> NexusMemory:
    """Get a NexusMemory instance for a CosySim character.

    Args:
        character_id: The character's ID (e.g., 'lola', 'viktor').

    Returns:
        NexusMemory configured for that character.
    """
    return NexusMemory(namespace="agent", agent_id=character_id)
