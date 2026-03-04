"""Nexus→Dataset curation pipeline.

Extracts knowledge from the Nexus KMS, applies quality filtering and
format conversion, and outputs curated training datasets in JSONL,
chat-ML, or instruction-tuning format.

Usage::

    from engine.nexus.dataset_curator import DatasetCurator
    curator = DatasetCurator()
    curator.export_qa_dataset("training/datasets/nexus_qa.jsonl")
    curator.export_instruction_dataset("training/datasets/nexus_instruct.jsonl")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

FormatType = Literal["instruction", "chat_ml", "sharegpt", "raw"]


@dataclass
class CurationStats:
    """Statistics from a curation run."""

    total_fetched: int = 0
    after_quality_filter: int = 0
    after_dedup: int = 0
    exported: int = 0
    format: str = "instruction"
    output_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_fetched": self.total_fetched,
            "after_quality_filter": self.after_quality_filter,
            "after_dedup": self.after_dedup,
            "exported": self.exported,
            "format": self.format,
            "output_path": self.output_path,
        }


@dataclass
class QualityFilter:
    """Configurable quality thresholds for dataset curation."""

    min_content_length: int = 50
    max_content_length: int = 10000
    min_answer_length: int = 20
    min_question_length: int = 10
    exclude_categories: List[str] = field(default_factory=list)
    require_categories: List[str] = field(default_factory=list)
    exclude_tags: List[str] = field(default_factory=list)
    require_tags: List[str] = field(default_factory=list)


class DatasetCurator:
    """Curates training datasets from Nexus knowledge entries.

    Supports multiple output formats and quality filtering.
    """

    def __init__(self, nexus_url: str = "http://127.0.0.1:8700") -> None:
        self._url = nexus_url.rstrip("/")

    # ── Public API ───────────────────────────────────────────────

    def export_qa_dataset(
        self,
        output_path: str,
        fmt: FormatType = "instruction",
        quality: Optional[QualityFilter] = None,
        limit: int = 5000,
    ) -> CurationStats:
        """Export Q&A pairs from Nexus as a training dataset.

        Args:
            output_path: JSONL file to write.
            fmt: Output format (instruction, chat_ml, sharegpt, raw).
            quality: Quality filter config. Uses defaults if None.
            limit: Max entries to fetch.

        Returns:
            CurationStats with counts at each pipeline stage.
        """
        qf = quality or QualityFilter()
        stats = CurationStats(format=fmt, output_path=output_path)

        raw = self._fetch_qa(limit=limit)
        stats.total_fetched = len(raw)

        filtered = self._apply_qa_filter(raw, qf)
        stats.after_quality_filter = len(filtered)

        deduped = self._dedup_qa(filtered)
        stats.after_dedup = len(deduped)

        formatted = [self._format_qa(item, fmt) for item in deduped]
        self._write_jsonl(formatted, output_path)
        stats.exported = len(formatted)

        logger.info(
            "QA dataset exported: %d → %d → %d → %s",
            stats.total_fetched, stats.after_quality_filter,
            stats.exported, output_path,
        )
        return stats

    def export_instruction_dataset(
        self,
        output_path: str,
        content_types: Optional[List[str]] = None,
        fmt: FormatType = "instruction",
        quality: Optional[QualityFilter] = None,
        limit: int = 5000,
    ) -> CurationStats:
        """Export knowledge entries as instruction-tuning data.

        Args:
            output_path: JSONL file to write.
            content_types: Filter by content type (note, document, code, etc.).
            fmt: Output format.
            quality: Quality filter config.
            limit: Max entries to fetch.

        Returns:
            CurationStats with pipeline counts.
        """
        qf = quality or QualityFilter()
        stats = CurationStats(format=fmt, output_path=output_path)
        types = content_types or ["note", "document", "code", "decision"]

        raw = self._fetch_entries(content_types=types, limit=limit)
        stats.total_fetched = len(raw)

        filtered = self._apply_entry_filter(raw, qf)
        stats.after_quality_filter = len(filtered)

        deduped = self._dedup_entries(filtered)
        stats.after_dedup = len(deduped)

        formatted = [self._format_entry(item, fmt) for item in deduped]
        self._write_jsonl(formatted, output_path)
        stats.exported = len(formatted)

        logger.info(
            "Instruction dataset exported: %d → %d → %d → %s",
            stats.total_fetched, stats.after_quality_filter,
            stats.exported, output_path,
        )
        return stats

    def export_combined_dataset(
        self,
        output_path: str,
        fmt: FormatType = "instruction",
        quality: Optional[QualityFilter] = None,
        limit: int = 5000,
    ) -> CurationStats:
        """Export both Q&A pairs and knowledge entries as a combined dataset.

        Args:
            output_path: JSONL file to write.
            fmt: Output format.
            quality: Quality filter config.
            limit: Max entries per source.

        Returns:
            CurationStats with combined pipeline counts.
        """
        qf = quality or QualityFilter()
        stats = CurationStats(format=fmt, output_path=output_path)

        qa_raw = self._fetch_qa(limit=limit)
        entry_raw = self._fetch_entries(limit=limit)
        stats.total_fetched = len(qa_raw) + len(entry_raw)

        qa_filtered = self._apply_qa_filter(qa_raw, qf)
        entry_filtered = self._apply_entry_filter(entry_raw, qf)
        stats.after_quality_filter = len(qa_filtered) + len(entry_filtered)

        qa_deduped = self._dedup_qa(qa_filtered)
        entry_deduped = self._dedup_entries(entry_filtered)
        stats.after_dedup = len(qa_deduped) + len(entry_deduped)

        formatted = (
            [self._format_qa(item, fmt) for item in qa_deduped]
            + [self._format_entry(item, fmt) for item in entry_deduped]
        )
        self._write_jsonl(formatted, output_path)
        stats.exported = len(formatted)
        return stats

    def preview(
        self,
        source: str = "qa",
        fmt: FormatType = "instruction",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Preview curated examples without writing to file.

        Args:
            source: "qa" or "entries".
            fmt: Output format.
            limit: Number of examples to preview.

        Returns:
            List of formatted examples.
        """
        if source == "qa":
            raw = self._fetch_qa(limit=limit)
            return [self._format_qa(item, fmt) for item in raw[:limit]]
        raw = self._fetch_entries(limit=limit)
        return [self._format_entry(item, fmt) for item in raw[:limit]]

    # ── Nexus API ────────────────────────────────────────────────

    def _fetch_qa(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """Fetch Q&A pairs from Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client().find_qa("", limit=limit)
        except Exception as e:
            logger.warning("Failed to fetch Q&A from Nexus: %s", e)
        return []

    def _fetch_entries(
        self,
        content_types: Optional[List[str]] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """Fetch knowledge entries from Nexus."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if content_types:
                entries = []
                for ct in content_types:
                    entries.extend(client.list_by_type(ct, limit=limit))
                return entries
            return client.list_entries(limit=limit)
        except Exception as e:
            logger.warning("Failed to fetch entries from Nexus: %s", e)
        return []

    # ── Filtering ────────────────────────────────────────────────

    def _apply_qa_filter(
        self, items: List[Dict], qf: QualityFilter
    ) -> List[Dict]:
        """Apply quality filters to Q&A pairs."""
        result = []
        for item in items:
            q = item.get("question", "")
            a = item.get("answer", "")
            if len(q) < qf.min_question_length:
                continue
            if len(a) < qf.min_answer_length:
                continue
            if len(a) > qf.max_content_length:
                continue
            cat = item.get("category", "")
            if qf.exclude_categories and cat in qf.exclude_categories:
                continue
            if qf.require_categories and cat not in qf.require_categories:
                continue
            tags = item.get("tags", [])
            if qf.exclude_tags and any(t in qf.exclude_tags for t in tags):
                continue
            if qf.require_tags and not any(t in qf.require_tags for t in tags):
                continue
            result.append(item)
        return result

    def _apply_entry_filter(
        self, items: List[Dict], qf: QualityFilter
    ) -> List[Dict]:
        """Apply quality filters to knowledge entries."""
        result = []
        for item in items:
            content = item.get("content", "")
            if len(content) < qf.min_content_length:
                continue
            if len(content) > qf.max_content_length:
                continue
            cat = item.get("category", "")
            if qf.exclude_categories and cat in qf.exclude_categories:
                continue
            if qf.require_categories and cat not in qf.require_categories:
                continue
            tags = item.get("tags", [])
            if qf.exclude_tags and any(t in qf.exclude_tags for t in tags):
                continue
            if qf.require_tags and not any(t in qf.require_tags for t in tags):
                continue
            result.append(item)
        return result

    # ── Deduplication ────────────────────────────────────────────

    def _dedup_qa(self, items: List[Dict]) -> List[Dict]:
        """Remove duplicate Q&A pairs by normalised question."""
        seen: set = set()
        result = []
        for item in items:
            key = item.get("question", "").strip().lower()
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _dedup_entries(self, items: List[Dict]) -> List[Dict]:
        """Remove duplicate entries by title."""
        seen: set = set()
        result = []
        for item in items:
            key = item.get("title", "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    # ── Formatting ───────────────────────────────────────────────

    def _format_qa(self, item: Dict, fmt: FormatType) -> Dict[str, Any]:
        """Format a Q&A pair for training."""
        q = item.get("question", "").strip()
        a = item.get("answer", "").strip()

        if fmt == "instruction":
            return {
                "instruction": "Answer the following question about CosySim.",
                "input": q,
                "output": a,
            }
        elif fmt == "chat_ml":
            return {
                "messages": [
                    {"role": "system", "content": "You are a CosySim expert assistant."},
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": a},
                ],
            }
        elif fmt == "sharegpt":
            return {
                "conversations": [
                    {"from": "human", "value": q},
                    {"from": "gpt", "value": a},
                ],
            }
        return {"question": q, "answer": a, **{k: v for k, v in item.items()
                                                 if k not in ("question", "answer")}}

    def _format_entry(self, item: Dict, fmt: FormatType) -> Dict[str, Any]:
        """Format a knowledge entry for training."""
        title = item.get("title", "").strip()
        content = item.get("content", "").strip()
        ct = item.get("content_type", "note")

        prompt_map = {
            "note": f"Explain: {title}",
            "document": f"Summarise the following: {title}",
            "code": f"Explain this code pattern: {title}",
            "decision": f"What was decided about: {title}",
        }
        instruction = prompt_map.get(ct, f"Describe: {title}")

        if fmt == "instruction":
            return {
                "instruction": instruction,
                "input": "",
                "output": content,
            }
        elif fmt == "chat_ml":
            return {
                "messages": [
                    {"role": "system", "content": "You are a CosySim expert assistant."},
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": content},
                ],
            }
        elif fmt == "sharegpt":
            return {
                "conversations": [
                    {"from": "human", "value": instruction},
                    {"from": "gpt", "value": content},
                ],
            }
        return {"title": title, "content": content, "content_type": ct}

    # ── I/O ──────────────────────────────────────────────────────

    @staticmethod
    def _write_jsonl(items: List[Dict], path: str) -> None:
        """Write items as JSONL."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        logger.info("Wrote %d examples to %s", len(items), path)


# ── Singleton ────────────────────────────────────────────────────────

_curator: Optional[DatasetCurator] = None


def get_dataset_curator() -> DatasetCurator:
    """Return the singleton DatasetCurator."""
    global _curator
    if _curator is None:
        try:
            from engine.config import get_config
            cfg = get_config()
            url = cfg.get("nexus.url", "http://127.0.0.1:8700")
        except Exception:
            url = "http://127.0.0.1:8700"
        _curator = DatasetCurator(nexus_url=url)
    return _curator
