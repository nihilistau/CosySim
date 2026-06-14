"""
NexusSceneMixin — Nexus knowledge integration for CosySim scenes.

Provides automatic knowledge storage, retrieval, and memory management
for any scene that mixes it in.  Thread-safe, non-blocking, gracefully
degrades when Nexus is offline.

Usage:
    from engine.scenes.nexus_mixin import NexusSceneMixin

    class MyScene(BaseScene, NexusSceneMixin):
        def start(self):
            self.nexus_init("my_scene")
            ...

        def stop(self):
            self.nexus_flush()
            ...
"""
from __future__ import annotations

import logging
import time
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class NexusSceneMixin:
    """Mixin that adds Nexus knowledge integration to any BaseScene subclass."""

    # ── Initialisation ──────────────────────────────────────────────────

    def nexus_init(self, scene_id: str) -> None:
        """Initialise Nexus integration for this scene.

        Args:
            scene_id: Unique scene identifier (e.g. "penthouse", "tavern").
        """
        self._nexus_scene_id: str = scene_id
        self._nexus_client = None
        self._nexus_available: bool = False
        self._nexus_event_buffer: List[Dict] = []
        self._nexus_buffer_lock = threading.Lock()
        self._nexus_last_flush: float = 0.0
        self._nexus_flush_interval: float = 60.0  # seconds between auto-flushes

        # v1.50.1 [2026-03-22] — Non-blocking Nexus availability check.
        # Old code called is_available() synchronously (30s timeout × 2 retries = 60s)
        # which blocked scene __init__ and prevented socketio.run() from starting.
        try:
            from engine.nexus.client import get_nexus_client
            self._nexus_client = get_nexus_client()
            # Quick 2s probe instead of the default 30s health check
            import urllib.request
            try:
                base = self._nexus_client._base_url
                req = urllib.request.Request(f"{base}/api/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    import json as _json
                    data = _json.loads(resp.read().decode())
                    self._nexus_available = data.get("ok", False)
            except Exception:
                self._nexus_available = False
        except Exception:
            self._nexus_available = False

        if self._nexus_available:
            logger.info("Nexus integration active for scene '%s'", scene_id)
        else:
            logger.debug("Nexus offline — scene '%s' runs without knowledge layer", scene_id)

    # ── Knowledge Retrieval ─────────────────────────────────────────────

    def nexus_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search Nexus knowledge base for scene-relevant information.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of matching knowledge entries (empty if Nexus offline).
        """
        if not self._nexus_available or not self._nexus_client:
            return []
        try:
            return self._nexus_client.search(query, limit=limit)
        except Exception as exc:
            logger.debug("nexus_search failed: %s", exc)
            return []

    def nexus_ask(self, question: str, depth: str = "shallow") -> Optional[str]:
        """Ask Nexus a question via the NexusQueryRouter (cache → FTS → ask → LLM).

        Uses the smart query router to check all tiers before falling back
        to LLM.  Answers are auto-cached for future reuse.

        Args:
            question: The question to ask.
            depth: "shallow" (cache+FTS only) or "deep" (includes NLM).

        Returns:
            Answer string, or None if unavailable.
        """
        try:
            from engine.nexus.query_router import get_query_router
            router = get_query_router()
            use_llm = depth != "shallow"
            result = router.query(
                question,
                use_llm=use_llm,
                category=getattr(self, "_nexus_scene_id", "scene"),
                source_hint=f"scene:{getattr(self, '_nexus_scene_id', 'unknown')}",
                depth=depth,
            )
            return result.answer if result.answer else None
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        # Fallback to direct client call if router unavailable
        if not self._nexus_available or not self._nexus_client:
            return None
        try:
            result = self._nexus_client.ask(question, depth=depth)
            return result.get("answer") if result else None
        except Exception as exc:
            logger.debug("nexus_ask failed: %s", exc)
            return None

    def nexus_get_character_knowledge(self, character_id: str) -> str:
        """Retrieve stored knowledge about a character for prompt enrichment.

        Args:
            character_id: Character identifier.

        Returns:
            Formatted knowledge string for system prompt injection.
        """
        if not self._nexus_available:
            return ""
        try:
            results = self._nexus_client.search(
                f"character {character_id} {self._nexus_scene_id}",
                limit=3,
            )
            if not results:
                return ""
            snippets = []
            for r in results:
                title = r.get("title", "")
                content = r.get("content", "")
                if content:
                    snippets.append(f"[{title}] {content[:200]}")
            return "\n".join(snippets)
        except Exception:
            return ""

    # ── Knowledge Storage ───────────────────────────────────────────────

    def nexus_store_event(
        self,
        event_type: str,
        description: str,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Buffer a scene event for batch storage in Nexus.

        Events are stored in a local buffer and flushed periodically or
        on scene stop.  This avoids per-event HTTP overhead.

        Args:
            event_type: Event category (e.g. "interaction", "milestone").
            description: Human-readable event description.
            tags: Optional list of tags for categorisation.
        """
        # v1.62.0 [2026-06-15] — Guard against an uninitialised Nexus layer.
        # nexus_store_event is called from per-action callbacks (e.g. the
        # penthouse agent-action callback). When _connect_nexus() has not run
        # (manual tick path, tests, scenes constructed without serving), the
        # buffer attributes are unset; accessing self._nexus_scene_id then
        # raised AttributeError, which AgentLoop.tick() caught and turned into
        # a duplicate idle/error action per character. Fail safe (no-op) here.
        if not hasattr(self, "_nexus_event_buffer"):
            # v1.62.0 [2026-06-15] — review: fail-loud nexus breadcrumb +
            # behavioral cap test. Leave a trace instead of silently dropping.
            logger.debug(
                "[nexus] store_event before init — dropping event "
                "(operation=store_event, type=%s)",
                event_type,
            )
            return
        event = {
            "type": event_type,
            "description": description,
            "scene": getattr(self, "_nexus_scene_id", "unknown"),
            "timestamp": time.time(),
            "tags": tags or [],
        }
        with self._nexus_buffer_lock:
            self._nexus_event_buffer.append(event)

        # Auto-flush if interval exceeded
        if time.time() - self._nexus_last_flush > self._nexus_flush_interval:
            self._nexus_auto_flush()

    def nexus_store_memory(
        self,
        character_id: str,
        memory: str,
        importance: str = "normal",
    ) -> None:
        """Store a character memory in Nexus.

        Args:
            character_id: Who remembers this.
            memory: The memory content.
            importance: "low", "normal", or "high".
        """
        if not self._nexus_available or not self._nexus_client:
            return
        title = f"Memory: {character_id} in {self._nexus_scene_id}"
        tags = [self._nexus_scene_id, character_id, "memory", importance]
        try:
            self._nexus_client.add_entry(
                title=title,
                content=memory,
                content_type="memory",
                category=self._nexus_scene_id,
                tags=tags,
                created_by=f"scene:{self._nexus_scene_id}",
            )
        except Exception as exc:
            logger.debug("nexus_store_memory failed: %s", exc)

    def nexus_store_qa(self, question: str, answer: str) -> None:
        """Store a Q&A pair discovered during scene gameplay.

        Args:
            question: The question.
            answer: The answer.
        """
        if not self._nexus_available or not self._nexus_client:
            return
        try:
            self._nexus_client.add_qa(
                question=question,
                answer=answer,
                category=self._nexus_scene_id,
                tags=[self._nexus_scene_id],
            )
        except Exception as exc:
            logger.debug("nexus_store_qa failed: %s", exc)

    # ── Prompt Enrichment ───────────────────────────────────────────────

    def nexus_enrich_prompt(
        self,
        character_id: str,
        base_prompt: str,
        context_query: Optional[str] = None,
    ) -> str:
        """Enrich a character's system prompt with Nexus knowledge.

        Appends relevant knowledge snippets to the base prompt without
        modifying it destructively.

        Args:
            character_id: Character for which to retrieve context.
            base_prompt: The original system prompt.
            context_query: Optional query to find relevant knowledge.

        Returns:
            Enriched prompt string.
        """
        if not self._nexus_available:
            return base_prompt

        knowledge = self.nexus_get_character_knowledge(character_id)
        if not knowledge:
            return base_prompt

        return (
            base_prompt
            + "\n\n[NEXUS KNOWLEDGE]\n"
            + knowledge
            + "\n[/NEXUS KNOWLEDGE]"
        )

    # ── Flush & Lifecycle ───────────────────────────────────────────────

    def _nexus_auto_flush(self) -> None:
        """Flush buffered events to Nexus in a background thread."""
        if not self._nexus_available or not self._nexus_client:
            return
        with self._nexus_buffer_lock:
            if not self._nexus_event_buffer:
                return
            events = self._nexus_event_buffer.copy()
            self._nexus_event_buffer.clear()
            self._nexus_last_flush = time.time()

        def _do_flush():
            try:
                content = "\n".join(
                    f"[{e['type']}] {e['description']}" for e in events
                )
                self._nexus_client.add_entry(
                    title=f"Scene events: {self._nexus_scene_id} ({len(events)} events)",
                    content=content,
                    content_type="history",
                    category=self._nexus_scene_id,
                    tags=[self._nexus_scene_id, "events", "auto"],
                    created_by=f"scene:{self._nexus_scene_id}",
                )
            except Exception as exc:
                logger.debug("nexus auto-flush failed: %s", exc)

        threading.Thread(target=_do_flush, daemon=True).start()

    def nexus_flush(self) -> None:
        """Flush all buffered events to Nexus synchronously.

        Call this in the scene's ``stop()`` method.
        """
        if not self._nexus_available or not self._nexus_client:
            return
        with self._nexus_buffer_lock:
            if not self._nexus_event_buffer:
                return
            events = self._nexus_event_buffer.copy()
            self._nexus_event_buffer.clear()
        try:
            content = "\n".join(
                f"[{e['type']}] {e['description']}" for e in events
            )
            self._nexus_client.add_entry(
                title=f"Scene events: {self._nexus_scene_id} ({len(events)} events)",
                content=content,
                content_type="history",
                category=self._nexus_scene_id,
                tags=[self._nexus_scene_id, "events", "auto"],
                created_by=f"scene:{self._nexus_scene_id}",
            )
            logger.info("Flushed %d events to Nexus for scene '%s'", len(events), self._nexus_scene_id)
        except Exception as exc:
            logger.warning("nexus_flush failed: %s", exc)

    def nexus_log_scene_session(self, summary: str = "") -> None:
        """Log this scene session to Nexus for tracking.

        Args:
            summary: Optional session summary text.
        """
        if not self._nexus_available or not self._nexus_client:
            return
        try:
            self._nexus_client.log_session(
                project="CosySim",
                agent_id=f"scene:{self._nexus_scene_id}",
            )
        except Exception as exc:
            logger.debug("nexus_log_scene_session failed: %s", exc)
