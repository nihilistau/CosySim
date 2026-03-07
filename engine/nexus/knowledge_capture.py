"""Reusable Nexus capture helpers for durable knowledge backfill.

These helpers standardize the user-mandated workflow:

1. If Nexus is missing needed information and we find it elsewhere,
2. store that discovery back into Nexus as reusable knowledge,
3. and add a direct Q&A pair so the answer is easier to retrieve later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class KnowledgeCaptureResult:
    """Result of storing reusable knowledge into Nexus."""

    title: str
    question: str
    category: str
    entry_id: Optional[str] = None
    qa_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the capture result."""
        return {
            "title": self.title,
            "question": self.question,
            "category": self.category,
            "entry_id": self.entry_id,
            "qa_id": self.qa_id,
            "stored": bool(self.entry_id or self.qa_id),
        }


def _merge_tags(*tag_sets: Optional[List[str]]) -> List[str]:
    """Return tags without duplicates while preserving order."""
    merged: List[str] = []
    for tag_set in tag_sets:
        for tag in tag_set or []:
            if tag and tag not in merged:
                merged.append(tag)
    return merged


def _build_external_discovery_content(
    question: str,
    answer: str,
    source: str,
    details: str = "",
) -> str:
    """Build readable note content for an external discovery backfill."""
    lines = [
        f"Question: {question}",
        f"Source: {source}",
        "",
        "Answer:",
        answer,
    ]
    if details:
        lines.extend(["", "Details:", details])
    return "\n".join(lines)


def capture_entry_and_qa(
    title: str,
    content: str,
    *,
    question: str = "",
    answer: str = "",
    category: str = "development",
    content_type: str = "note",
    tags: Optional[List[str]] = None,
    client: Any = None,
) -> KnowledgeCaptureResult:
    """Store a Nexus entry and, when provided, an associated Q&A pair."""
    if client is None:
        from engine.nexus.client import get_nexus_client

        client = get_nexus_client()

    merged_tags = _merge_tags(tags)
    entry_id = client.add_entry(
        title=title,
        content=content,
        content_type=content_type,
        category=category,
        tags=merged_tags,
    )
    qa_id = None
    if question and answer:
        qa_id = client.add_qa(
            question=question,
            answer=answer,
            category=category,
            tags=merged_tags,
        )
    return KnowledgeCaptureResult(
        title=title,
        question=question,
        category=category,
        entry_id=entry_id,
        qa_id=qa_id,
    )


def capture_external_discovery(
    *,
    question: str,
    answer: str,
    source: str,
    title: str = "",
    category: str = "research",
    tags: Optional[List[str]] = None,
    details: str = "",
    client: Any = None,
) -> KnowledgeCaptureResult:
    """Backfill an externally discovered answer into Nexus."""
    resolved_title = title or f"Discovery: {question[:72]}"
    content = _build_external_discovery_content(question, answer, source, details)
    merged_tags = _merge_tags(["nexus-backfill", "external-discovery"], tags)
    return capture_entry_and_qa(
        resolved_title,
        content,
        question=question,
        answer=answer,
        category=category,
        content_type="note",
        tags=merged_tags,
        client=client,
    )
