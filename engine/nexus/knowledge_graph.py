"""
Knowledge Graph — Topic relationships, clustering, and gap detection.

Builds a lightweight topic graph from Nexus entries:
- Extracts key topics/entities from knowledge entries
- Clusters related entries by topic similarity
- Detects coverage gaps (topics with few entries)
- Generates research tasks for underrepresented areas

Uses simple keyword extraction and co-occurrence rather than
heavyweight NLP — keeps it fast and dependency-free.

Thread-safe singleton — call ``get_knowledge_graph()``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Stop words for topic extraction ─────────────────────────────────────

_STOP_WORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "but", "and", "or", "if", "because", "while", "although", "that",
    "which", "who", "whom", "this", "these", "those", "what", "it", "its",
    "i", "we", "you", "he", "she", "they", "me", "us", "him", "her",
    "them", "my", "our", "your", "his", "their", "use", "using", "used",
    "also", "get", "set", "new", "see", "like", "make", "well", "way",
}

# Minimum topic length and frequency
_MIN_TOPIC_LEN = 3
_MIN_FREQUENCY = 2


# ── Data Models ─────────────────────────────────────────────────────────


@dataclass
class TopicNode:
    """A topic in the knowledge graph."""

    name: str
    entry_count: int
    entry_ids: List[str] = field(default_factory=list)
    related_topics: Dict[str, int] = field(default_factory=dict)
    categories: List[str] = field(default_factory=list)


@dataclass
class KnowledgeGap:
    """A detected gap in knowledge coverage."""

    topic: str
    entry_count: int
    related_strong_topics: List[str]
    suggested_research: str
    priority: str  # "high", "medium", "low"


@dataclass
class GraphSnapshot:
    """Complete knowledge graph state."""

    topic_count: int
    edge_count: int
    gap_count: int
    top_topics: List[Dict[str, Any]]
    gaps: List[Dict[str, Any]]
    clusters: List[Dict[str, Any]]
    created_at: str


# ── Singleton ───────────────────────────────────────────────────────────

_instance: Optional[KnowledgeGraph] = None
_lock = threading.Lock()


def get_knowledge_graph() -> KnowledgeGraph:
    """Get or create the singleton KnowledgeGraph instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = KnowledgeGraph()
    return _instance


# ── Core Class ──────────────────────────────────────────────────────────


class KnowledgeGraph:
    """Lightweight topic graph built from Nexus entries.

    Extracts topics, builds co-occurrence edges, detects gaps,
    and generates research suggestions.
    """

    def __init__(self) -> None:
        self._topics: Dict[str, TopicNode] = {}
        self._last_build: Optional[str] = None

    # ── Public API ──────────────────────────────────────────────────

    def build(self, entries: Optional[List[Dict[str, Any]]] = None) -> GraphSnapshot:
        """Build the knowledge graph from Nexus entries.

        Args:
            entries: List of Nexus entries (dicts with 'title', 'content',
                     'id', 'category', 'tags'). If None, fetches from Nexus.

        Returns:
            GraphSnapshot with topics, edges, gaps, and clusters.
        """
        if entries is None:
            entries = self._fetch_entries()

        self._topics.clear()

        # Extract topics from each entry
        for entry in entries:
            entry_id = str(entry.get("id", ""))
            title = str(entry.get("title", ""))
            content = str(entry.get("content", ""))
            category = str(entry.get("category", ""))
            tags = entry.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]

            topics = self._extract_topics(title, content, tags)

            for topic in topics:
                if topic not in self._topics:
                    self._topics[topic] = TopicNode(name=topic, entry_count=0)
                node = self._topics[topic]
                node.entry_count += 1
                if entry_id and entry_id not in node.entry_ids:
                    node.entry_ids.append(entry_id)
                if category and category not in node.categories:
                    node.categories.append(category)

            # Build co-occurrence edges
            for i, t1 in enumerate(topics):
                for t2 in topics[i + 1:]:
                    if t1 in self._topics and t2 in self._topics:
                        self._topics[t1].related_topics[t2] = (
                            self._topics[t1].related_topics.get(t2, 0) + 1
                        )
                        self._topics[t2].related_topics[t1] = (
                            self._topics[t2].related_topics.get(t1, 0) + 1
                        )

        # Prune infrequent topics
        self._prune(min_count=_MIN_FREQUENCY)

        self._last_build = datetime.now(timezone.utc).isoformat()

        return self.snapshot()

    def snapshot(self) -> GraphSnapshot:
        """Return current graph state."""
        edges = sum(len(t.related_topics) for t in self._topics.values()) // 2
        gaps = self.detect_gaps()
        clusters = self.cluster_topics()

        top = sorted(
            self._topics.values(),
            key=lambda t: t.entry_count,
            reverse=True,
        )[:20]

        return GraphSnapshot(
            topic_count=len(self._topics),
            edge_count=edges,
            gap_count=len(gaps),
            top_topics=[
                {
                    "name": t.name,
                    "entry_count": t.entry_count,
                    "related": list(t.related_topics.keys())[:5],
                    "categories": t.categories[:3],
                }
                for t in top
            ],
            gaps=[asdict(g) for g in gaps],
            clusters=[
                {"topic": c["topic"], "members": c["members"][:10], "size": c["size"]}
                for c in clusters[:10]
            ],
            created_at=self._last_build or "",
        )

    def detect_gaps(self, threshold: int = 2) -> List[KnowledgeGap]:
        """Find topics with few entries that are related to strong topics.

        Args:
            threshold: Maximum entry count to consider a "gap".

        Returns:
            List of KnowledgeGap objects.
        """
        gaps: List[KnowledgeGap] = []

        for name, node in self._topics.items():
            if node.entry_count > threshold:
                continue

            strong_neighbors = [
                rel for rel, weight in node.related_topics.items()
                if rel in self._topics and self._topics[rel].entry_count > threshold * 2
            ]

            if not strong_neighbors:
                continue

            priority = "high" if node.entry_count <= 1 else "medium"
            gaps.append(
                KnowledgeGap(
                    topic=name,
                    entry_count=node.entry_count,
                    related_strong_topics=strong_neighbors[:5],
                    suggested_research=(
                        f"Research '{name}' in the context of "
                        f"{', '.join(strong_neighbors[:3])}. "
                        f"Only {node.entry_count} entries exist."
                    ),
                    priority=priority,
                )
            )

        return sorted(gaps, key=lambda g: g.entry_count)

    def cluster_topics(self, min_overlap: int = 2) -> List[Dict[str, Any]]:
        """Group topics into clusters by co-occurrence.

        Uses a simple connected-components approach: topics are in the
        same cluster if they co-occur in at least ``min_overlap`` entries.

        Returns:
            List of clusters with topic members and sizes.
        """
        visited: Set[str] = set()
        clusters: List[Dict[str, Any]] = []

        for name in sorted(self._topics, key=lambda n: self._topics[n].entry_count, reverse=True):
            if name in visited:
                continue

            cluster: List[str] = []
            stack = [name]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                cluster.append(current)

                if current in self._topics:
                    for neighbor, weight in self._topics[current].related_topics.items():
                        if weight >= min_overlap and neighbor not in visited:
                            stack.append(neighbor)

            if len(cluster) >= 2:
                clusters.append({
                    "topic": cluster[0],
                    "members": sorted(cluster),
                    "size": len(cluster),
                    "total_entries": sum(
                        self._topics[m].entry_count
                        for m in cluster
                        if m in self._topics
                    ),
                })

        return sorted(clusters, key=lambda c: c["total_entries"], reverse=True)

    def get_topic(self, name: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific topic."""
        node = self._topics.get(name.lower())
        if not node:
            return None
        return {
            "name": node.name,
            "entry_count": node.entry_count,
            "entry_ids": node.entry_ids,
            "related_topics": dict(sorted(
                node.related_topics.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]),
            "categories": node.categories,
        }

    def search_topics(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search topics by name substring."""
        query_lower = query.lower()
        matches = [
            {"name": n.name, "entry_count": n.entry_count}
            for n in self._topics.values()
            if query_lower in n.name
        ]
        return sorted(matches, key=lambda m: m["entry_count"], reverse=True)[:limit]

    def create_research_tasks(self) -> List[Dict[str, Any]]:
        """Create task scheduler entries for knowledge gaps.

        Returns:
            List of created task dicts.
        """
        gaps = self.detect_gaps()
        if not gaps:
            return []

        tasks: List[Dict[str, Any]] = []
        try:
            from engine.nexus.task_scheduler import get_task_scheduler
            scheduler = get_task_scheduler()

            for gap in gaps[:5]:
                task_id = f"gap-research-{gap.topic.replace(' ', '-')}"
                try:
                    scheduler.add_task(
                        task_id=task_id,
                        title=f"[Research Gap] {gap.topic}",
                        description=gap.suggested_research,
                        priority=gap.priority,
                        source="knowledge_graph",
                        tags=["auto-generated", "research", "gap"],
                    )
                    tasks.append({
                        "task_id": task_id,
                        "topic": gap.topic,
                        "priority": gap.priority,
                    })
                except Exception as exc:
                    logger.debug("Task creation failed: %s", exc)
        except Exception as exc:
            logger.warning("Task scheduler unavailable: %s", exc)

        return tasks

    # ── Topic Extraction ────────────────────────────────────────────

    def _extract_topics(
        self, title: str, content: str, tags: List[str]
    ) -> List[str]:
        """Extract topic keywords from an entry."""
        topics: List[str] = []

        # Tags are high-quality topics
        for tag in tags:
            clean = tag.strip().lower()
            if clean and len(clean) >= _MIN_TOPIC_LEN and clean not in _STOP_WORDS:
                topics.append(clean)

        # Extract from title — all significant words
        for word in self._tokenize(title):
            if word not in _STOP_WORDS and len(word) >= _MIN_TOPIC_LEN:
                topics.append(word)

        # Extract from content — top keywords by frequency
        content_words = [
            w for w in self._tokenize(content)
            if w not in _STOP_WORDS and len(w) >= _MIN_TOPIC_LEN
        ]
        word_freq = Counter(content_words)
        for word, count in word_freq.most_common(10):
            if count >= 2:
                topics.append(word)

        return list(set(topics))

    def _tokenize(self, text: str) -> List[str]:
        """Split text into lowercase word tokens."""
        return re.findall(r"[a-z][a-z0-9_]+", text.lower())

    def _prune(self, min_count: int = 2) -> None:
        """Remove topics that appear in fewer than min_count entries."""
        to_remove = [
            name for name, node in self._topics.items()
            if node.entry_count < min_count
        ]
        for name in to_remove:
            del self._topics[name]

        # Clean up stale references
        for node in self._topics.values():
            node.related_topics = {
                k: v for k, v in node.related_topics.items()
                if k in self._topics
            }

    # ── Nexus Fetch ─────────────────────────────────────────────────

    def _fetch_entries(self) -> List[Dict[str, Any]]:
        """Fetch all entries from Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            results = client.search("*", limit=500)
            return results if results else []
        except Exception as exc:
            logger.warning("Cannot fetch Nexus entries: %s", exc)
            return []

    # ── Storage ─────────────────────────────────────────────────────

    def store_snapshot(self) -> None:
        """Store current graph snapshot in Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()

            snap = self.snapshot()
            content = json.dumps(asdict(snap), indent=2, default=str)

            client.add_entry(
                title=f"Knowledge Graph Snapshot — {snap.created_at[:10]}",
                content=content,
                content_type="document",
                category="system",
                tags=["knowledge-graph", "snapshot", "auto-generated"],
            )
            logger.info(
                "Stored knowledge graph: %d topics, %d edges, %d gaps",
                snap.topic_count,
                snap.edge_count,
                snap.gap_count,
            )
        except Exception as exc:
            logger.warning("Failed to store graph snapshot: %s", exc)
