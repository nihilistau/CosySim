"""
Training Data Flywheel — Automatic training data collection from system interactions.

Captures training examples from task completions, Nexus Q&A, NLM conversations,
routing decisions, and preference feedback. Exports in JSONL, ShareGPT, and DPO
formats suitable for fine-tuning local LMStudio models.

Sources:
    1. Task completions  — AgentTask result → instruction-tuning pair
    2. Q&A pairs         — Nexus cache → instruction-tuning pair
    3. NLM conversations — Multi-turn research → distilled Q&A
    4. Routing decisions  — Model selection → router training
    5. Preference data    — Chosen/rejected → DPO training

Usage::

    from engine.nexus.training_flywheel import get_training_flywheel

    fw = get_training_flywheel()
    fw.collect_from_qa("How does X work?", "X works by...", source="cache")
    fw.export_jsonl(min_quality=0.7)
    print(fw.stats())
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Data Model ────


@dataclass
class TrainingExample:
    """A single training example captured from system interactions."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""  # "task", "qa", "nlm", "routing", "preference"
    input_text: str = ""
    output_text: str = ""
    model: str = ""
    quality_score: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exported: bool = False

    def content_hash(self) -> str:
        """Generate hash for deduplication."""
        raw = f"{self.source}:{self.input_text}:{self.output_text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "source": self.source,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "model": self.model,
            "quality_score": self.quality_score,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "exported": self.exported,
        }


# ──── Flywheel Core ────


class TrainingFlywheel:
    """Collects, stores, and exports training data from system interactions.

    Stores examples in SQLite and exports to JSONL, ShareGPT, and DPO
    formats for fine-tuning local LMStudio models.

    Args:
        db_path: Path to the SQLite database. Defaults to config value
            or ``data/training_flywheel.db``.
        export_dir: Directory for exported files. Defaults to config value
            or ``data/training_exports/``.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        export_dir: Optional[str] = None,
    ) -> None:
        cfg = get_config()
        self._db_path = db_path or cfg.get(
            "training.flywheel.db_path", "data/training_flywheel.db"
        )
        self._export_dir = export_dir or cfg.get(
            "training.flywheel.export_dir", "data/training_exports"
        )
        self._lock = threading.Lock()
        self._init_db()
        logger.info("TrainingFlywheel initialised — db=%s", self._db_path)

    # ──── Database Setup ────

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS examples (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    output_text TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    quality_score REAL DEFAULT 0.5,
                    metadata TEXT DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    exported INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_examples_source
                    ON examples(source);
                CREATE INDEX IF NOT EXISTS idx_examples_quality
                    ON examples(quality_score);
                CREATE INDEX IF NOT EXISTS idx_examples_exported
                    ON examples(exported);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_examples_hash
                    ON examples(content_hash);

                CREATE TABLE IF NOT EXISTS export_history (
                    id TEXT PRIMARY KEY,
                    format TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    example_count INTEGER DEFAULT 0,
                    filters TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ──── Storage Helpers ────

    def _store_example(self, example: TrainingExample) -> str:
        """Insert an example, skipping duplicates.

        Args:
            example: The training example to store.

        Returns:
            The example ID, or empty string if duplicate.
        """
        content_hash = example.content_hash()
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO examples
                            (id, source, input_text, output_text, model,
                             quality_score, metadata, content_hash,
                             created_at, exported)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            example.id,
                            example.source,
                            example.input_text,
                            example.output_text,
                            example.model,
                            example.quality_score,
                            json.dumps(example.metadata),
                            content_hash,
                            example.created_at.isoformat(),
                            0,
                        ),
                    )
                    return example.id
                except sqlite3.IntegrityError:
                    logger.debug(
                        "Duplicate example skipped — hash=%s", content_hash
                    )
                    return ""

    def _update_stat(self, key: str, value: str) -> None:
        """Upsert a stats row."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stats (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    # ──── Collection Methods ────

    def collect_from_task(
        self,
        task: Any,
        result: str,
        model: str = "",
    ) -> str:
        """Collect a training example from a completed AgentTask.

        Args:
            task: An AgentTask instance (or any object with title,
                description, tags, complexity, assigned_agent attributes).
            result: The agent's solution text.
            model: Model that produced the result.

        Returns:
            Example ID, or empty string if duplicate.
        """
        title = getattr(task, "title", "")
        description = getattr(task, "description", "")
        input_text = f"{title}\n\n{description}".strip()
        if not input_text or not result:
            logger.warning("collect_from_task: empty input or result — skipped")
            return ""

        duration = 0.0
        completed_at = getattr(task, "completed_at", 0.0)
        created_at = getattr(task, "created_at", 0.0)
        if completed_at and created_at:
            duration = completed_at - created_at

        metadata: Dict[str, Any] = {
            "task_id": getattr(task, "id", ""),
            "tags": getattr(task, "tags", []),
            "complexity": getattr(task, "complexity", ""),
            "agent": getattr(task, "assigned_agent", ""),
            "duration_s": round(duration, 2),
        }

        example = TrainingExample(
            source="task",
            input_text=input_text,
            output_text=result,
            model=model or getattr(task, "assigned_agent", ""),
            quality_score=0.6,
            metadata=metadata,
        )
        eid = self._store_example(example)
        if eid:
            logger.info("Collected task example — id=%s task=%s", eid[:8], title)
        return eid

    def collect_from_qa(
        self,
        question: str,
        answer: str,
        source: str = "manual",
        confidence: float = 0.7,
        model: str = "",
    ) -> str:
        """Collect a training example from a Q&A pair.

        Args:
            question: The question text.
            answer: The answer text.
            source: Origin of the answer (cache/FTS/NLM/LLM/manual).
            confidence: Confidence score of the answer.
            model: Model that generated the answer.

        Returns:
            Example ID, or empty string if duplicate.
        """
        if not question.strip() or not answer.strip():
            logger.warning("collect_from_qa: empty question or answer — skipped")
            return ""

        quality = min(1.0, max(0.0, confidence))

        example = TrainingExample(
            source="qa",
            input_text=question.strip(),
            output_text=answer.strip(),
            model=model,
            quality_score=quality,
            metadata={"qa_source": source},
        )
        eid = self._store_example(example)
        if eid:
            logger.info(
                "Collected Q&A example — id=%s source=%s", eid[:8], source
            )
        return eid

    def collect_from_nlm(
        self,
        conversation: List[Dict[str, Any]],
        topic: str = "",
    ) -> List[str]:
        """Collect training examples from an NLM conversation.

        Distills multi-turn conversation into individual Q&A pairs.
        Each human→gpt turn pair becomes one training example.

        Args:
            conversation: List of message dicts with ``role`` and ``content``
                keys (e.g. ``[{"role": "user", "content": "..."}, ...]``).
            topic: Optional topic label for metadata.

        Returns:
            List of stored example IDs (empty strings for duplicates).
        """
        ids: List[str] = []
        pairs = self._extract_qa_pairs(conversation)
        for q, a in pairs:
            example = TrainingExample(
                source="nlm",
                input_text=q,
                output_text=a,
                model="nlm",
                quality_score=0.75,
                metadata={"topic": topic, "turn_count": len(conversation)},
            )
            ids.append(self._store_example(example))

        stored = sum(1 for i in ids if i)
        logger.info(
            "Collected %d NLM examples from %d turns — topic=%s",
            stored,
            len(conversation),
            topic,
        )
        return ids

    def collect_from_routing(
        self,
        request: str,
        model_chosen: str,
        reason: str,
    ) -> str:
        """Collect a routing decision as training data.

        Args:
            request: The original request/prompt text.
            model_chosen: The model that was selected.
            reason: Why this model was chosen.

        Returns:
            Example ID, or empty string if duplicate.
        """
        if not request.strip():
            logger.warning("collect_from_routing: empty request — skipped")
            return ""

        output = json.dumps({"model": model_chosen, "reason": reason})
        example = TrainingExample(
            source="routing",
            input_text=request.strip(),
            output_text=output,
            model="router",
            quality_score=0.8,
            metadata={"model_chosen": model_chosen, "reason": reason},
        )
        eid = self._store_example(example)
        if eid:
            logger.info(
                "Collected routing example — id=%s model=%s", eid[:8], model_chosen
            )
        return eid

    def collect_preference(
        self,
        prompt: str,
        chosen: str,
        rejected: str,
        model: str = "",
    ) -> str:
        """Collect a preference pair for DPO training.

        Args:
            prompt: The original prompt.
            chosen: The preferred response.
            rejected: The dispreferred response.
            model: Model that generated the responses.

        Returns:
            Example ID, or empty string if duplicate.
        """
        if not prompt.strip() or not chosen.strip() or not rejected.strip():
            logger.warning("collect_preference: empty field(s) — skipped")
            return ""

        example = TrainingExample(
            source="preference",
            input_text=prompt.strip(),
            output_text=chosen.strip(),
            model=model,
            quality_score=0.9,
            metadata={"rejected": rejected.strip()},
        )
        eid = self._store_example(example)
        if eid:
            logger.info("Collected preference example — id=%s", eid[:8])
        return eid

    # ──── Export Methods ────

    def export_jsonl(
        self,
        min_quality: float = 0.5,
        source_filter: str = "",
    ) -> Dict[str, Any]:
        """Export examples as JSONL for instruction tuning.

        Format per line: ``{"instruction": "...", "input": "", "output": "..."}``

        Args:
            min_quality: Minimum quality score to include.
            source_filter: If set, only export examples from this source.

        Returns:
            Dict with ``file``, ``count``, and ``export_id`` keys.
        """
        rows = self._query_for_export(min_quality, source_filter, exclude_source="preference")
        if not rows:
            logger.info("export_jsonl: no examples to export")
            return {"file": "", "count": 0, "export_id": ""}

        export_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"jsonl_{timestamp}_{export_id}.jsonl"
        filepath = os.path.join(self._export_dir, filename)
        os.makedirs(self._export_dir, exist_ok=True)

        ids_exported: List[str] = []
        with open(filepath, "w", encoding="utf-8") as f:
            for row in rows:
                record = {
                    "instruction": row["input_text"],
                    "input": "",
                    "output": row["output_text"],
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                ids_exported.append(row["id"])

        self._mark_exported(ids_exported, export_id, "jsonl", filepath)
        logger.info("Exported %d examples to %s", len(ids_exported), filepath)
        return {"file": filepath, "count": len(ids_exported), "export_id": export_id}

    def export_sharegpt(
        self,
        min_quality: float = 0.5,
    ) -> Dict[str, Any]:
        """Export examples in ShareGPT conversation format.

        Format per line::

            {"conversations": [
                {"from": "human", "value": "..."},
                {"from": "gpt", "value": "..."}
            ]}

        Args:
            min_quality: Minimum quality score to include.

        Returns:
            Dict with ``file``, ``count``, and ``export_id`` keys.
        """
        rows = self._query_for_export(min_quality, "", exclude_source="preference")
        if not rows:
            logger.info("export_sharegpt: no examples to export")
            return {"file": "", "count": 0, "export_id": ""}

        export_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"sharegpt_{timestamp}_{export_id}.jsonl"
        filepath = os.path.join(self._export_dir, filename)
        os.makedirs(self._export_dir, exist_ok=True)

        ids_exported: List[str] = []
        with open(filepath, "w", encoding="utf-8") as f:
            for row in rows:
                record = {
                    "conversations": [
                        {"from": "human", "value": row["input_text"]},
                        {"from": "gpt", "value": row["output_text"]},
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                ids_exported.append(row["id"])

        self._mark_exported(ids_exported, export_id, "sharegpt", filepath)
        logger.info("Exported %d ShareGPT examples to %s", len(ids_exported), filepath)
        return {"file": filepath, "count": len(ids_exported), "export_id": export_id}

    def export_dpo(self) -> Dict[str, Any]:
        """Export preference examples in DPO format.

        Format per line::

            {"prompt": "...", "chosen": "...", "rejected": "..."}

        Returns:
            Dict with ``file``, ``count``, and ``export_id`` keys.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, input_text, output_text, metadata
                FROM examples
                WHERE source = 'preference' AND exported = 0
                ORDER BY created_at
                """
            ).fetchall()

        if not rows:
            logger.info("export_dpo: no preference examples to export")
            return {"file": "", "count": 0, "export_id": ""}

        export_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"dpo_{timestamp}_{export_id}.jsonl"
        filepath = os.path.join(self._export_dir, filename)
        os.makedirs(self._export_dir, exist_ok=True)

        ids_exported: List[str] = []
        with open(filepath, "w", encoding="utf-8") as f:
            for row in rows:
                meta = json.loads(row["metadata"])
                record = {
                    "prompt": row["input_text"],
                    "chosen": row["output_text"],
                    "rejected": meta.get("rejected", ""),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                ids_exported.append(row["id"])

        self._mark_exported(ids_exported, export_id, "dpo", filepath)
        logger.info("Exported %d DPO examples to %s", len(ids_exported), filepath)
        return {"file": filepath, "count": len(ids_exported), "export_id": export_id}

    # ──── Query & Stats ────

    def stats(self) -> Dict[str, Any]:
        """Return aggregate statistics about collected training data.

        Returns:
            Dict with total counts, per-source breakdown, quality
            distribution, and export history.
        """
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0]
            exported = conn.execute(
                "SELECT COUNT(*) FROM examples WHERE exported = 1"
            ).fetchone()[0]

            by_source = {}
            for row in conn.execute(
                "SELECT source, COUNT(*) as cnt FROM examples GROUP BY source"
            ):
                by_source[row["source"]] = row["cnt"]

            avg_quality = conn.execute(
                "SELECT AVG(quality_score) FROM examples"
            ).fetchone()[0]

            quality_buckets: Dict[str, int] = {}
            for label, lo, hi in [
                ("low", 0.0, 0.3),
                ("medium", 0.3, 0.7),
                ("high", 0.7, 1.01),
            ]:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM examples WHERE quality_score >= ? AND quality_score < ?",
                    (lo, hi),
                ).fetchone()[0]
                quality_buckets[label] = cnt

            export_count = conn.execute(
                "SELECT COUNT(*) FROM export_history"
            ).fetchone()[0]

        return {
            "total_examples": total,
            "exported": exported,
            "unexported": total - exported,
            "by_source": by_source,
            "avg_quality": round(avg_quality, 3) if avg_quality else 0.0,
            "quality_distribution": quality_buckets,
            "total_exports": export_count,
        }

    def sync_from_nexus(self) -> Dict[str, Any]:
        """Pull existing Q&A pairs from Nexus into the flywheel.

        Requires a running Nexus server. Fetches Q&A entries and stores
        them as ``qa`` source examples, skipping duplicates.

        Returns:
            Dict with ``synced`` (new), ``skipped`` (duplicate), and
            ``errors`` counts.
        """
        try:
            from engine.nexus.client import get_nexus_client
        except ImportError:
            logger.error("sync_from_nexus: nexus client not available")
            return {"synced": 0, "skipped": 0, "errors": 1}

        client = get_nexus_client()
        synced = 0
        skipped = 0
        errors = 0

        try:
            if not client.is_available():
                logger.warning("sync_from_nexus: Nexus server not reachable")
                return {"synced": 0, "skipped": 0, "errors": 1}

            entries = client.list_entries(content_type="qa", limit=500)
            if not entries:
                logger.info("sync_from_nexus: no Q&A entries found in Nexus")
                return {"synced": 0, "skipped": 0, "errors": 0}

            for entry in entries:
                question = entry.title
                answer = entry.content
                if not question or not answer:
                    skipped += 1
                    continue

                eid = self.collect_from_qa(
                    question=question,
                    answer=answer,
                    source="nexus_sync",
                    confidence=entry.get("quality_score", 0.7),
                )
                if eid:
                    synced += 1
                else:
                    skipped += 1

        except Exception as exc:
            logger.error("sync_from_nexus error: %s", exc)
            errors += 1

        logger.info(
            "Nexus sync complete — synced=%d skipped=%d errors=%d",
            synced,
            skipped,
            errors,
        )
        return {"synced": synced, "skipped": skipped, "errors": errors}

    # ──── Internal Helpers ────

    def _extract_qa_pairs(
        self, conversation: List[Dict[str, Any]]
    ) -> List[tuple[str, str]]:
        """Extract sequential user→assistant pairs from a conversation.

        Args:
            conversation: List of message dicts with ``role`` and ``content``.

        Returns:
            List of (question, answer) tuples.
        """
        pairs: List[tuple[str, str]] = []
        i = 0
        while i < len(conversation) - 1:
            msg = conversation[i]
            role = msg.get("role", "").lower()
            if role in ("user", "human"):
                next_msg = conversation[i + 1]
                next_role = next_msg.get("role", "").lower()
                if next_role in ("assistant", "gpt", "model"):
                    q = msg.get("content", "").strip()
                    a = next_msg.get("content", "").strip()
                    if q and a:
                        pairs.append((q, a))
                    i += 2
                    continue
            i += 1
        return pairs

    def _query_for_export(
        self,
        min_quality: float,
        source_filter: str,
        exclude_source: str = "",
    ) -> List[sqlite3.Row]:
        """Query unexported examples matching filters.

        Args:
            min_quality: Minimum quality score.
            source_filter: Restrict to a single source type.
            exclude_source: Exclude a single source type.

        Returns:
            List of Row objects.
        """
        clauses = ["exported = 0", "quality_score >= ?"]
        params: List[Any] = [min_quality]

        if source_filter:
            clauses.append("source = ?")
            params.append(source_filter)
        if exclude_source:
            clauses.append("source != ?")
            params.append(exclude_source)

        where = " AND ".join(clauses)
        query = f"SELECT * FROM examples WHERE {where} ORDER BY created_at"

        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    def _mark_exported(
        self,
        ids: List[str],
        export_id: str,
        fmt: str,
        filepath: str,
    ) -> None:
        """Mark examples as exported and log the export.

        Args:
            ids: List of example IDs that were exported.
            export_id: Unique export identifier.
            fmt: Export format name.
            filepath: Path to the export file.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                for eid in ids:
                    conn.execute(
                        "UPDATE examples SET exported = 1 WHERE id = ?",
                        (eid,),
                    )
                conn.execute(
                    """
                    INSERT INTO export_history
                        (id, format, file_path, example_count, filters, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (export_id, fmt, filepath, len(ids), "{}", now),
                )


# ──── Singleton ────

_flywheel: Optional[TrainingFlywheel] = None
_lock = threading.Lock()


def get_training_flywheel() -> TrainingFlywheel:
    """Return the global TrainingFlywheel singleton.

    Thread-safe. Creates the instance on first call.

    Returns:
        The singleton TrainingFlywheel instance.
    """
    global _flywheel
    with _lock:
        if _flywheel is None:
            _flywheel = TrainingFlywheel()
    return _flywheel
