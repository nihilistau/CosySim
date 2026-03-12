"""Centralised NotebookLM notebook factory.

Consolidates 11 separate notebook creation paths into a single module with:
- Unified state file for deduplication and lifecycle tracking
- Fallback chain: NLMDirectClient → proxy → error
- Weekly rotation for ephemeral categories (news, argus)
- Persistent notebooks for long-lived categories (bootstrap, master)
- Metrics tracking for operational visibility

Usage:
    from engine.nexus.nlm_notebook_factory import get_notebook_factory

    factory = get_notebook_factory()
    nb_id = factory.get_or_create("News 2026-W11", category="news")
    nb_id = factory.get_or_create("System Knowledge", category="bootstrap")
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "data", "nlm_notebooks_state.json",
)

# Categories that rotate weekly — old notebooks are not reused across weeks
EPHEMERAL_CATEGORIES = {"news", "argus", "session", "research"}

# Categories that persist indefinitely — same notebook reused forever
PERSISTENT_CATEGORIES = {"bootstrap", "master", "training", "knowledge"}

# Maximum age in days before ephemeral notebooks are eligible for cleanup
EPHEMERAL_MAX_AGE_DAYS = 30


@dataclass
class NotebookRecord:
    """Tracked notebook metadata."""

    notebook_id: str
    name: str
    category: str
    created_at: str = ""
    last_used: str = ""
    source_count: int = 0
    week_label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotebookRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FactoryMetrics:
    """Operational metrics for the factory."""

    created: int = 0
    reused: int = 0
    failed: int = 0
    cleaned: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


class NLMNotebookFactory:
    """Centralised notebook creation and lifecycle management.

    Provides a single entry point for creating/reusing NotebookLM notebooks
    across all CosySim subsystems (news pipeline, bootstrap, teacher, ARGUS,
    session distillation, etc.).
    """

    def __init__(self, state_file: Optional[str] = None) -> None:
        self._state_file = state_file or _STATE_FILE
        self._lock = threading.Lock()
        self._direct_client = None
        self._state = self._load_state()
        self._metrics = FactoryMetrics()

    # ──── Public API ──────────────────────────────────────────────────────

    def get_or_create(
        self,
        name: str,
        category: str = "general",
        dedup_key: Optional[str] = None,
    ) -> Optional[str]:
        """Get an existing notebook or create a new one.

        Deduplication strategy:
        - If ``dedup_key`` is provided, reuse by that key (e.g. weekly label).
        - For persistent categories, reuse by name.
        - For ephemeral categories, reuse by name within the current week.

        Args:
            name: Display name for the notebook.
            category: Notebook category (news, bootstrap, training, etc.).
            dedup_key: Optional explicit deduplication key. If omitted, the
                factory derives one from category + name.

        Returns:
            Notebook ID string, or None if creation failed.
        """
        key = dedup_key or self._build_dedup_key(name, category)

        with self._lock:
            existing = self._find_by_key(key)
            if existing:
                self._metrics.reused += 1
                existing.last_used = _now_iso()
                self._save_state()
                logger.debug(
                    "Reusing notebook %s (%s) for key=%s",
                    existing.notebook_id, existing.name, key,
                )
                return existing.notebook_id

        notebook_id = self._create_notebook(name)
        if not notebook_id:
            self._metrics.failed += 1
            return None

        record = NotebookRecord(
            notebook_id=notebook_id,
            name=name,
            category=category,
            created_at=_now_iso(),
            last_used=_now_iso(),
            week_label=_week_label() if category in EPHEMERAL_CATEGORIES else "",
        )

        with self._lock:
            self._state["notebooks"][key] = record.to_dict()
            self._metrics.created += 1
            self._save_state()

        logger.info(
            "Created notebook %s -> %s (category=%s, key=%s)",
            name, notebook_id, category, key,
        )
        return notebook_id

    def get_notebook(self, dedup_key: str) -> Optional[NotebookRecord]:
        """Retrieve a notebook record by dedup key.

        Args:
            dedup_key: The deduplication key.

        Returns:
            NotebookRecord or None.
        """
        data = self._state["notebooks"].get(dedup_key)
        if data:
            return NotebookRecord.from_dict(data)
        return None

    def list_notebooks(self, category: Optional[str] = None) -> List[NotebookRecord]:
        """List all tracked notebooks, optionally filtered by category.

        Args:
            category: Filter by this category, or None for all.

        Returns:
            List of NotebookRecord objects.
        """
        records = []
        for data in self._state["notebooks"].values():
            rec = NotebookRecord.from_dict(data)
            if category is None or rec.category == category:
                records.append(rec)
        return records

    def cleanup_stale(self, max_age_days: int = EPHEMERAL_MAX_AGE_DAYS) -> int:
        """Remove ephemeral notebook records older than max_age_days.

        Does NOT delete the actual NotebookLM notebook — only removes the
        local tracking record so a new one will be created next time.

        Args:
            max_age_days: Maximum age for ephemeral notebooks.

        Returns:
            Number of records removed.
        """
        cutoff = time.time() - (max_age_days * 86400)
        to_remove: List[str] = []

        with self._lock:
            for key, data in self._state["notebooks"].items():
                rec = NotebookRecord.from_dict(data)
                if rec.category not in EPHEMERAL_CATEGORIES:
                    continue
                try:
                    created = datetime.fromisoformat(rec.created_at).timestamp()
                except (ValueError, TypeError):
                    continue
                if created < cutoff:
                    to_remove.append(key)

            for key in to_remove:
                del self._state["notebooks"][key]
                logger.info("Cleaned stale notebook record: %s", key)

            if to_remove:
                self._save_state()

        self._metrics.cleaned += len(to_remove)
        return len(to_remove)

    def record_source_added(self, dedup_key: str) -> None:
        """Increment source count for a tracked notebook.

        Args:
            dedup_key: The deduplication key for the notebook.
        """
        with self._lock:
            data = self._state["notebooks"].get(dedup_key)
            if data:
                data["source_count"] = data.get("source_count", 0) + 1
                data["last_used"] = _now_iso()
                self._save_state()

    def stats(self) -> Dict[str, Any]:
        """Return factory metrics and inventory summary.

        Returns:
            Dict with metrics, counts by category, and total notebooks tracked.
        """
        by_category: Dict[str, int] = {}
        for data in self._state["notebooks"].values():
            cat = data.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_tracked": len(self._state["notebooks"]),
            "by_category": by_category,
            "metrics": self._metrics.to_dict(),
        }

    # ──── Private Methods ─────────────────────────────────────────────────

    def _build_dedup_key(self, name: str, category: str) -> str:
        """Build a deduplication key from name and category.

        Ephemeral categories include the week label so they rotate weekly.
        Persistent categories use just the name for indefinite reuse.
        """
        if category in EPHEMERAL_CATEGORIES:
            return f"{category}:{name}:{_week_label()}"
        return f"{category}:{name}"

    def _find_by_key(self, key: str) -> Optional[NotebookRecord]:
        """Find a notebook record by dedup key."""
        data = self._state["notebooks"].get(key)
        if data:
            return NotebookRecord.from_dict(data)
        return None

    def _create_notebook(self, name: str) -> Optional[str]:
        """Create a notebook via NLMDirectClient with credential guard.

        Returns:
            Notebook ID string, or None on failure.
        """
        client = self._get_direct_client()
        if not client:
            logger.warning("No NLM client available — cannot create notebook '%s'", name)
            return None

        try:
            notebook_id = client.create_notebook(name)
            if notebook_id:
                return notebook_id
        except Exception as exc:
            logger.warning("NLMDirectClient.create_notebook failed for '%s': %s", name, exc)

        return None

    def _get_direct_client(self):
        """Lazy-load NLMDirectClient with credential guard."""
        if self._direct_client is not None:
            return self._direct_client
        try:
            from engine.integrations.google_account_pool import get_account_pool
            from engine.integrations.nlm_direct_client import NLMDirectClient

            pool = get_account_pool()
            account = pool.get_account("notebooklm")
            if account is None:
                account = pool.get_by_name("knack112358")
            if not account:
                logger.warning("No NLM account in pool")
                return None
            if not account.cookies:
                logger.warning("NLM account '%s' has no cookies", account.name)
                return None
            if account.is_stale():
                logger.warning("NLM account '%s' cookies stale — refresh recommended", account.name)

            self._direct_client = NLMDirectClient(account)
            return self._direct_client
        except Exception as exc:
            logger.warning("Could not load NLM direct client: %s", exc)
        return None

    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON file."""
        try:
            path = Path(self._state_file)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "notebooks" not in data:
                    data["notebooks"] = {}
                return data
        except Exception as exc:
            logger.warning("Failed to load notebook factory state: %s", exc)
        return {"notebooks": {}, "version": 1}

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            path = Path(self._state_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to save notebook factory state: %s", exc)


# ──── Module Helpers ──────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _week_label() -> str:
    """Return ISO week label like '2026-W11'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


# ──── Singleton ───────────────────────────────────────────────────────────

_factory_instance: Optional[NLMNotebookFactory] = None
_factory_lock = threading.Lock()


def get_notebook_factory() -> NLMNotebookFactory:
    """Get or create the singleton NLMNotebookFactory.

    Returns:
        NLMNotebookFactory instance.
    """
    global _factory_instance
    if _factory_instance is None:
        with _factory_lock:
            if _factory_instance is None:
                _factory_instance = NLMNotebookFactory()
    return _factory_instance
