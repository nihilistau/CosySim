"""Source Pyramid — builds and uploads the structured meta-document set that
shapes all NLM generation tile output (flashcards, quiz, data tables, report).

The pyramid is a set of 6 named source documents uploaded as the FIRST sources
into any cache-generation notebook.  Because Gemini reads ALL sources before
generating, these meta-documents act as a persistent "prompt injection" for
quota-free tiles — without consuming any chat quota.

Layer 0: Consumer Briefing    — who queries, exact phrasing patterns per class
Layer 1: Output Schema        — exact CSV column / Python dict key schema
Layer 2: Good Examples        — 10 ideal Q&A pairs at the quality bar
Layer 3: Bad Examples         — 5 pairs to avoid with explanations
Layer 4: Existing Coverage    — questions already cached (avoid duplicates)
Layer 5: Priority Rubric      — how to score 1–5

Usage::

    from engine.nexus.source_pyramid import get_source_pyramid
    pyramid = get_source_pyramid()

    # Build all 6 meta-documents
    docs = pyramid.build_all(existing_questions=["How do I run tests?", ...])

    # Upload pyramid to a notebook (returns count of sources added)
    nb_id = "311f2b2e-..."
    added = pyramid.upload_pyramid(nb_id)

    # Then upload content-layer sources (history chunks, docs)
    from engine.nexus.history_miner import get_history_miner
    content_docs = get_history_miner().mine_all_themes()
    added += pyramid.upload_content(nb_id, content_docs)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from engine.nexus.consumer_briefing import get_consumer_briefing
from engine.nexus.history_miner import SourceDocument

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

# Source document names (prefixed so they sort first alphabetically in NLM)
_LAYER_NAMES = {
    0: "_00_CONSUMER_BRIEFING",
    1: "_01_OUTPUT_SCHEMA",
    2: "_02_GOOD_EXAMPLES",
    3: "_03_BAD_EXAMPLES",
    4: "_04_EXISTING_COVERAGE",
    5: "_05_PRIORITY_RUBRIC",
}

# Public alias for tests and external imports
LAYER_NAMES = _LAYER_NAMES

# Delay between batchexecute add_source calls (rate limiting)
_SOURCE_UPLOAD_DELAY_S = 1.0

# Maximum existing questions to include in layer 4 (too many slows NLM reading)
_MAX_COVERAGE_QUESTIONS = 500


# ──── Source Pyramid ──────────────────────────────────────────────────────────

class SourcePyramid:
    """Builds and uploads the structured source pyramid for NLM cache notebooks.

    The pyramid shapes ALL generation tile output by providing Gemini with
    structured meta-documents before any content sources.  These documents
    guide flashcards, quiz, data tables, and report generation without
    consuming chat quota.

    Args:
        upload_delay_s: Seconds to wait between source uploads (rate limiting).
    """

    def __init__(self, upload_delay_s: float = _SOURCE_UPLOAD_DELAY_S) -> None:
        self._upload_delay_s = upload_delay_s
        self._briefing = get_consumer_briefing()

    # ── Build ───────────────────────────────────────────────────────────────

    def build_all(
        self,
        existing_questions: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Build all 6 pyramid meta-documents.

        Args:
            existing_questions: Questions already in the Nexus cache (for
                layer 4 coverage document).  Pass None to omit layer 4.

        Returns:
            Dict mapping layer name (e.g. "_00_CONSUMER_BRIEFING") to content.
        """
        docs: Dict[str, str] = {}

        # Layer 0: Consumer Briefing
        docs[_LAYER_NAMES[0]] = self._briefing.build_briefing()

        # Layer 1: Output Schema
        docs[_LAYER_NAMES[1]] = self._briefing.get_schema_doc()

        # Layer 2: Good Examples
        docs[_LAYER_NAMES[2]] = self._briefing.get_good_examples()

        # Layer 3: Bad Examples
        docs[_LAYER_NAMES[3]] = self._briefing.get_bad_examples()

        # Layer 4: Existing Coverage (optional)
        if existing_questions is not None:
            docs[_LAYER_NAMES[4]] = self._build_coverage_doc(existing_questions)

        # Layer 5: Priority Rubric
        docs[_LAYER_NAMES[5]] = self._briefing.build_priority_rubric()

        logger.info("Built %d pyramid source documents", len(docs))
        return docs

    def build_layer(self, layer: int, existing_questions: Optional[List[str]] = None) -> str:
        """Build a single pyramid layer document.

        Args:
            layer: Layer number 0–5.
            existing_questions: Required for layer 4.

        Returns:
            Document content string.

        Raises:
            ValueError: If layer is out of range.
        """
        if layer == 0:
            return self._briefing.build_briefing()
        if layer == 1:
            return self._briefing.get_schema_doc()
        if layer == 2:
            return self._briefing.get_good_examples()
        if layer == 3:
            return self._briefing.get_bad_examples()
        if layer == 4:
            return self._build_coverage_doc(existing_questions or [])
        if layer == 5:
            return self._briefing.build_priority_rubric()
        raise ValueError(f"Layer must be 0–5, got {layer}")

    # ── Upload ──────────────────────────────────────────────────────────────

    def upload_pyramid(
        self,
        notebook_id: str,
        skip_layer_4: bool = False,
        existing_questions: Optional[List[str]] = None,
    ) -> int:
        """Upload pyramid layers 0–5 as sources to an NLM notebook.

        Args:
            notebook_id: NLM notebook ID to upload to.
            skip_layer_4: If True, skip the coverage layer (faster upload
                if no existing questions are available yet).
            existing_questions: Questions for layer 4.  Ignored if
                skip_layer_4 is True.

        Returns:
            Number of sources successfully uploaded.
        """
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
        except Exception as exc:
            logger.error("Failed to load NLM hybrid router: %s", exc)
            return 0

        docs = self.build_all(
            existing_questions=None if skip_layer_4 else existing_questions,
        )
        uploaded = 0
        for name, content in sorted(docs.items()):  # sort = layers in order
            try:
                result = hybrid.add_text_source(
                    notebook_id=notebook_id,
                    title=name,
                    content=content,
                )
                if result and not result.get("error"):
                    uploaded += 1
                    logger.debug("Uploaded pyramid layer: %s", name)
                else:
                    logger.warning("Failed to upload layer %s: %s", name, result)
                if self._upload_delay_s > 0:
                    time.sleep(self._upload_delay_s)
            except Exception as exc:
                logger.error("Error uploading layer %s: %s", name, exc)

        logger.info("Uploaded %d/%d pyramid layers to notebook %s",
                    uploaded, len(docs), notebook_id[:8])
        return uploaded

    def upload_content(
        self,
        notebook_id: str,
        docs: List[SourceDocument],
    ) -> int:
        """Upload content-layer source documents (history themes, docs).

        Args:
            notebook_id: NLM notebook ID to upload to.
            docs: List of SourceDocument objects (e.g. from HistoryMiner).

        Returns:
            Number of sources successfully uploaded.
        """
        try:
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
        except Exception as exc:
            logger.error("Failed to load NLM hybrid router: %s", exc)
            return 0

        uploaded = 0
        for doc in docs:
            if not doc.content.strip():
                continue
            try:
                result = hybrid.add_text_source(
                    notebook_id=notebook_id,
                    title=doc.title,
                    content=doc.content,
                )
                if result and not result.get("error"):
                    uploaded += 1
                    logger.debug("Uploaded content source: %s (%d chars)",
                                 doc.title, doc.char_count)
                else:
                    logger.warning("Failed to upload source '%s': %s", doc.title, result)
                if self._upload_delay_s > 0:
                    time.sleep(self._upload_delay_s)
            except Exception as exc:
                logger.error("Error uploading source '%s': %s", doc.title, exc)

        logger.info("Uploaded %d/%d content sources to notebook %s",
                    uploaded, len(docs), notebook_id[:8])
        return uploaded

    def refresh_coverage(
        self,
        notebook_id: str,
        client: Any,
    ) -> int:
        """Re-upload layer 4 with the current question list from Nexus.

        Call this at the start of each generation cycle to ensure Gemini
        has an up-to-date coverage map and avoids generating duplicates.

        Args:
            notebook_id: NLM notebook ID to update.
            client: NexusClient instance for fetching current questions.

        Returns:
            Number of sources uploaded (0 or 1).
        """
        try:
            if not client.is_available():
                logger.info("Nexus client unavailable — skipping coverage refresh")
                return 0
            from engine.mcp.nlm_hybrid import get_nlm_hybrid
            hybrid = get_nlm_hybrid()
            questions = self._fetch_current_questions(client)
            content = self._build_coverage_doc(questions)
            result = hybrid.add_text_source(
                notebook_id=notebook_id,
                title=_LAYER_NAMES[4],
                content=content,
            )
            if result and not result.get("error"):
                logger.info("Coverage layer refreshed with %d questions", len(questions))
                return 1
            logger.warning("Failed to refresh coverage layer: %s", result)
            return 0
        except Exception as exc:
            logger.error("Error refreshing coverage layer: %s", exc)
            return 0

    # ── Internal ────────────────────────────────────────────────────────────

    def _build_coverage_doc(self, existing_questions: List[str]) -> str:
        """Build the existing coverage document (layer 4)."""
        sample = existing_questions[:_MAX_COVERAGE_QUESTIONS]
        lines = "\n".join(f"- {q}" for q in sample)
        omitted = len(existing_questions) - len(sample)
        footer = f"\n\n... and {omitted} more questions already cached." if omitted > 0 else ""
        return (
            "# Existing Q&A Cache Coverage — CosySim Nexus\n\n"
            "The following questions are ALREADY answered in the Nexus cache.\n"
            "Do NOT generate Q&A pairs for these topics — they are already covered.\n"
            "Generate pairs for DIFFERENT topics not in this list.\n\n"
            f"{lines}{footer}"
        )

    def _fetch_current_questions(self, client: Any) -> List[str]:
        """Fetch existing questions from Nexus Q&A cache."""
        try:
            results = client.find_qa("", limit=1000) or []
            questions = []
            for item in results:
                if isinstance(item, dict):
                    q = item.get("question", item.get("q", ""))
                    if q:
                        questions.append(str(q)[:200])
            return questions
        except Exception as exc:
            logger.warning("Could not fetch existing questions: %s", exc)
            return []


# ──── Singleton ───────────────────────────────────────────────────────────────

_pyramid_instance: Optional[SourcePyramid] = None
_pyramid_lock = threading.Lock()


def get_source_pyramid() -> SourcePyramid:
    """Get the singleton SourcePyramid instance."""
    global _pyramid_instance
    if _pyramid_instance is None:
        with _pyramid_lock:
            if _pyramid_instance is None:
                _pyramid_instance = SourcePyramid()
    return _pyramid_instance
