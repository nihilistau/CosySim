"""
Knowledge Pipeline — Unified ingestion for all Nexus knowledge
================================================================

Single entry point: ingest -> validate -> dedup -> store -> embed -> Q&A -> notify.

Every knowledge source (sessions, URLs, agents, NLM distillation, manual)
routes through this pipeline to ensure consistent quality, deduplication,
embedding, and downstream notification.

Version: v1.56.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.56.0 [2026-03-26] — Initial creation: unified ingest pipeline with
        validation, content-hash dedup, auto-embed, rule-based Q&A generation,
        subscriber notification stub, and training flywheel integration.

CONNECTS: NexusClient, EmbeddingService, NexusVectorStore, DataCollector
CALLED BY: scheduler tasks, agent_submit, url_ingest, session_logger, MCP skills
EMITS: Nexus entries, Q&A pairs, vector embeddings, training examples
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Data Model ──────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    """Result of a knowledge ingestion operation."""

    success: bool = False
    entry_id: str = ""
    qa_pairs_generated: int = 0
    was_duplicate: bool = False
    quality_score: float = 0.0
    embedded: bool = False
    subscribers_notified: int = 0
    error: str = ""
    duration_ms: float = 0.0


# ──── Pipeline ────────────────────────────────────────────────────────────


class KnowledgePipeline:
    """Unified pipeline: validate -> dedup -> store -> embed -> Q&A -> notify.

    All knowledge ingestion—whether from Copilot sessions, URL crawls,
    agent submissions, NLM distillation, or manual entry—MUST route
    through :meth:`ingest` to guarantee consistent quality, dedup,
    embedding, Q&A generation, and training flywheel integration.
    """

    def __init__(self) -> None:
        self._client = None

    # ── Lazy Nexus client accessor ────────────────────────────────────

    @property
    def client(self):
        """Lazy-load the Nexus client singleton."""
        if self._client is None:
            from engine.nexus.client import get_nexus_client

            self._client = get_nexus_client()
        return self._client

    # ── Public API ────────────────────────────────────────────────────

    # v1.56.0 [2026-03-26] — Unified ingest entry point
    def ingest(
        self,
        title: str,
        content: str,
        content_type: str = "note",
        category: str = "general",
        tags: Optional[List[str]] = None,
        agent_id: str = "system",
        auto_qa: bool = True,
        auto_embed: bool = True,
        source: str = "",
    ) -> PipelineResult:
        """Single entry point for ALL knowledge ingestion.

        Args:
            title: Human-readable title for the entry.
            content: The knowledge content body.
            content_type: Nexus content type (note, document, research, code, etc.).
            category: Nexus category for routing/filtering.
            tags: Optional list of string tags.
            agent_id: ID of the agent/system originating the knowledge.
            auto_qa: Whether to auto-generate Q&A pairs from the entry.
            auto_embed: Whether to auto-embed into the vector store.
            source: Free-text source identifier (e.g. "session_logger", "url_ingest").

        Returns:
            PipelineResult with success status, entry_id, and pipeline metrics.
        """
        t0 = time.time()
        result = PipelineResult()

        try:
            # ── Step 1: Validate ──────────────────────────────────────
            if not title or not content:
                result.error = "Title and content required"
                logger.debug("[KnowledgePipeline] Validation failed: %s", result.error)
                return result
            if len(content) < 20:
                result.error = "Content too short (min 20 chars)"
                logger.debug("[KnowledgePipeline] Validation failed: %s", result.error)
                return result

            # ── Step 2: Deduplicate (content hash) ────────────────────
            # Hash title + first 500 chars of content to catch near-dupes
            content_hash = hashlib.sha256(
                f"{title}:{content[:500]}".encode()
            ).hexdigest()[:16]

            existing = self.client.search(content_hash, limit=1)
            if existing and any(content_hash in str(e) for e in existing):
                result.was_duplicate = True
                result.success = True
                logger.info(
                    "[KnowledgePipeline] Duplicate skipped (operation=ingest, hash=%s)",
                    content_hash,
                )
                return result

            # ── Step 3: Quality score (heuristic) ─────────────────────
            result.quality_score = self._score_quality(title, content, content_type)

            # ── Step 4: Store in Nexus ────────────────────────────────
            entry_tags = list(tags or [])
            entry_tags.append(f"hash:{content_hash}")
            if source:
                entry_tags.append(f"source:{source}")

            # NexusClient.add_entry uses created_by for the actor identity
            entry_id = self.client.add_entry(
                title=title,
                content=content,
                content_type=content_type,
                category=category,
                tags=entry_tags,
                created_by=agent_id,
                agent_id=agent_id,
            )
            if not entry_id:
                result.error = "Nexus add_entry failed"
                logger.warning(
                    "[KnowledgePipeline] Store failed (operation=ingest, title=%s)",
                    title[:50],
                )
                return result
            result.entry_id = entry_id
            result.success = True

            # ── Step 5: Auto-embed in vector store ────────────────────
            # NexusClient.add_entry already calls auto_embed_entry via
            # embedding_hooks, but we also explicitly push to the vector
            # store here so the pipeline is self-contained even if the
            # client hook is disabled.
            if auto_embed:
                result.embedded = self._auto_embed(entry_id, title, content, category)

            # ── Step 6: Auto-generate Q&A pairs ──────────────────────
            if auto_qa and result.quality_score >= 0.5:
                result.qa_pairs_generated = self._auto_qa(
                    title, content, category, agent_id
                )

            # ── Step 7: Notify subscribers ────────────────────────────
            result.subscribers_notified = self._notify_subscribers(
                entry_id, content_type, category, entry_tags
            )

            # ── Step 8: Feed training flywheel ────────────────────────
            self._feed_training(title, content, content_type, result.quality_score)

            logger.info(
                "[KnowledgePipeline] Ingested: %s (operation=ingest, type=%s, "
                "qa=%d, embedded=%s, quality=%.2f)",
                title[:50],
                content_type,
                result.qa_pairs_generated,
                result.embedded,
                result.quality_score,
            )

        except Exception as exc:
            result.error = str(exc)
            logger.error(
                "[KnowledgePipeline] Ingest failed (operation=ingest): %s", exc
            )

        result.duration_ms = (time.time() - t0) * 1000
        return result

    # ── Private Helpers ───────────────────────────────────────────────

    # v1.56.0 [2026-03-26] — Simple quality heuristic
    def _score_quality(
        self, title: str, content: str, content_type: str
    ) -> float:
        """Simple quality heuristic (0.0-1.0).

        Scores based on content length, title quality, content type,
        and structural indicators (newlines = structured content).
        """
        score = 0.3  # base score for any valid entry
        if len(content) > 200:
            score += 0.2
        if len(content) > 1000:
            score += 0.1
        if len(title) > 10:
            score += 0.1
        if content_type in ("document", "research", "code"):
            score += 0.2
        if "\n" in content:
            score += 0.1  # structured content with line breaks
        return min(score, 1.0)

    # v1.56.0 [2026-03-26] — Vector store embedding via NexusVectorStore
    def _auto_embed(
        self, entry_id: str, title: str, content: str, category: str
    ) -> bool:
        """Embed entry in ChromaDB for vector search.

        Uses NexusVectorStore.add() which handles embedding internally
        via the EmbeddingService.
        """
        try:
            from engine.nexus.vector_store import get_vector_store

            vs = get_vector_store()
            text = f"{title}\n{content[:2000]}"
            vs.add(
                entry_id=entry_id,
                text=text,
                metadata={"title": title, "category": category},
                collection="knowledge",
            )
            return True
        except Exception as exc:
            logger.debug(
                "[KnowledgePipeline] Auto-embed failed (entry_id=%s): %s",
                entry_id,
                exc,
            )
        return False

    # v1.56.0 [2026-03-26] — Rule-based Q&A generation
    def _auto_qa(
        self, title: str, content: str, category: str, agent_id: str
    ) -> int:
        """Generate Q&A pairs from entry using rule-based templates.

        Generates a "What is X?" pair for every entry, plus an
        "Explain X in detail" pair for longer content.
        """
        pairs: List[Dict[str, str]] = []

        # If the title is already a question, use it directly
        if "?" in title:
            pairs.append({"question": title, "answer": content[:500]})
        else:
            pairs.append({
                "question": f"What is {title}?",
                "answer": content[:500],
            })
            if len(content) > 200:
                pairs.append({
                    "question": f"Explain {title} in detail.",
                    "answer": content[:800],
                })

        stored = 0
        for pair in pairs:
            try:
                qa_id = self.client.add_qa(
                    question=pair["question"],
                    answer=pair["answer"],
                    category=category,
                    agent_id=agent_id,
                )
                if qa_id:
                    stored += 1
            except Exception:
                pass
        return stored

    # v1.56.0 [2026-03-26] — Subscriber notification (stub for future)
    def _notify_subscribers(
        self,
        entry_id: str,
        content_type: str,
        category: str,
        tags: List[str],
    ) -> int:
        """Notify agents subscribed to this content type/category.

        Future: query knowledge_subscriptions table and fire webhooks
        or Socket.IO events to listening agents.
        """
        # Stub — subscriber system not yet implemented
        return 0

    # v1.56.0 [2026-03-26] — Training flywheel integration
    def _feed_training(
        self,
        title: str,
        content: str,
        content_type: str,
        quality: float,
    ) -> None:
        """Feed training flywheel with the new knowledge.

        Sends a knowledge_synthesizer example to the DataCollector
        so that ingested knowledge contributes to micro-model training.
        """
        try:
            from training.data_collector import get_data_collector

            dc = get_data_collector()
            dc.collect(
                model_type="knowledge_synthesizer",
                input_text=f"Store knowledge: {title}",
                output_text=content[:500],
                quality=quality,
                metadata={"content_type": content_type, "source": "knowledge_pipeline"},
            )
        except Exception:
            pass  # Training flywheel is best-effort, never block ingestion


# ──── Singleton ───────────────────────────────────────────────────────────

_pipeline: Optional[KnowledgePipeline] = None


def get_knowledge_pipeline() -> KnowledgePipeline:
    """Get or create the singleton KnowledgePipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = KnowledgePipeline()
    return _pipeline
