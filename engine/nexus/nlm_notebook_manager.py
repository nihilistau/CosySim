"""NLM Notebook Manager — manages a fleet of purpose-built NotebookLM notebooks.

Provides named notebook "slots" for different CosySim knowledge domains
(architecture docs, codebase, tests, research topics) with lifecycle
management including creation, seeding, rotation, and staleness cleanup.

Usage:
    from engine.nexus.nlm_notebook_manager import get_notebook_manager
    mgr = get_notebook_manager()
    nb = mgr.ensure_notebook("cosysim-architecture")
    mgr.seed_from_docs()
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config
from engine.nexus.nlm_engine import get_nlm_engine

logger = logging.getLogger(__name__)

# ──── Constants ────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_METADATA_PATH = "data/nlm_notebooks.json"

BUILTIN_SLOTS = {
    "cosysim-architecture": "CosySim architecture and framework documentation",
    "cosysim-codebase": "Key CosySim engine source files",
    "cosysim-tests": "Test patterns, fixtures, and conventions",
}

_DEFAULT_DOC_FILES = [
    "docs/ARCHITECTURE.md",
    "docs/MCP_FRAMEWORK.md",
    "docs/SKILLS.md",
    "docs/SCENES.md",
    "docs/INTERCEPTORS.md",
    "docs/NEXUS_INTEGRATION.md",
    "docs/NOTEBOOKLM.md",
    "docs/CONFIGURATION.md",
]


# ──── Notebook Manager ────

class NLMNotebookManager:
    """Manages a fleet of named NotebookLM notebooks for CosySim.

    Each notebook occupies a named "slot" (e.g. ``cosysim-architecture``,
    ``research-mcp-state``).  Metadata is persisted to a local JSON file
    so notebook IDs survive restarts.

    Args:
        metadata_path: Path to the JSON metadata file.  Defaults to
            ``data/nlm_notebooks.json`` relative to the project root.
    """

    def __init__(self, metadata_path: Optional[str] = None) -> None:
        cfg = get_config()
        rel = metadata_path or cfg.get(
            "notebooklm.metadata_path", _DEFAULT_METADATA_PATH
        )
        self._metadata_path = _PROJECT_ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        self._lock = threading.Lock()
        self._notebooks: Dict[str, Dict[str, Any]] = {}
        self._load_metadata()

    # ──── Public API ────

    def ensure_notebook(self, slot_name: str) -> Dict[str, Any]:
        """Return the notebook for *slot_name*, creating it if absent.

        Args:
            slot_name: Logical slot name (e.g. ``cosysim-architecture``).

        Returns:
            Dict with ``slot_name``, ``notebook_id``, ``created_at``, etc.
        """
        with self._lock:
            if slot_name in self._notebooks:
                logger.debug("Notebook slot '%s' already exists", slot_name)
                return dict(self._notebooks[slot_name])

        description = BUILTIN_SLOTS.get(slot_name, f"CosySim notebook: {slot_name}")
        engine = get_nlm_engine()
        result = engine.create_notebook(f"[CosySim] {slot_name}")
        notebook_id = result.get("notebook_id") or result.get("id", "")
        if not notebook_id:
            logger.error("Failed to create notebook for slot '%s': %s", slot_name, result)
            return {"error": "create_failed", "detail": result}

        entry: Dict[str, Any] = {
            "slot_name": slot_name,
            "notebook_id": notebook_id,
            "description": description,
            "created_at": _now_iso(),
            "source_count": 0,
            "last_seeded": None,
            "last_asked": None,
        }

        with self._lock:
            self._notebooks[slot_name] = entry
            self._save_metadata()

        logger.info("Created notebook slot '%s' → %s", slot_name, notebook_id)
        return dict(entry)

    def seed_notebook(self, slot_name: str, sources: List[str]) -> Dict[str, Any]:
        """Add file-based sources to an existing notebook slot.

        Args:
            slot_name: Target slot name.
            sources: List of file paths (relative to project root or absolute).

        Returns:
            Dict with ``slot_name``, ``added``, ``errors``.
        """
        nb = self.ensure_notebook(slot_name)
        if "error" in nb:
            return nb

        notebook_id = nb["notebook_id"]
        engine = get_nlm_engine()
        added = 0
        errors: List[str] = []

        for src in sources:
            path = Path(src) if Path(src).is_absolute() else _PROJECT_ROOT / src
            if not path.exists():
                errors.append(f"{src}: not found")
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                suffix = path.suffix.lstrip(".")
                source_text = f"# File: {path.name}\n\n```{suffix}\n{content}\n```"
                engine.add_source(notebook_id, "text", source_text)
                added += 1
            except Exception as exc:
                errors.append(f"{src}: {exc}")

        with self._lock:
            entry = self._notebooks.get(slot_name)
            if entry:
                entry["source_count"] = entry.get("source_count", 0) + added
                entry["last_seeded"] = _now_iso()
                self._save_metadata()

        logger.info("Seeded slot '%s' with %d sources (%d errors)", slot_name, added, len(errors))
        return {"slot_name": slot_name, "added": added, "errors": errors}

    def seed_from_docs(self, slot_name: str = "cosysim-architecture") -> Dict[str, Any]:
        """Auto-seed a notebook from the ``docs/`` directory.

        Args:
            slot_name: Target slot (defaults to ``cosysim-architecture``).

        Returns:
            Dict with seeding results.
        """
        docs_dir = _PROJECT_ROOT / "docs"
        if not docs_dir.is_dir():
            return {"error": "docs_dir_missing", "path": str(docs_dir)}

        sources = [
            str(p.relative_to(_PROJECT_ROOT))
            for p in sorted(docs_dir.glob("*.md"))
            if p.is_file()
        ]
        if not sources:
            sources = list(_DEFAULT_DOC_FILES)

        return self.seed_notebook(slot_name, sources)

    def seed_from_code(
        self,
        slot_name: str = "cosysim-codebase",
        paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Auto-seed a notebook from engine source files.

        Args:
            slot_name: Target slot (defaults to ``cosysim-codebase``).
            paths: Explicit file paths.  If ``None``, a default set of key
                engine modules is used.

        Returns:
            Dict with seeding results.
        """
        if paths is None:
            paths = [
                "engine/config.py",
                "engine/mcp/__init__.py",
                "engine/scenes/base_scene.py",
                "engine/skills/skill.py",
                "engine/agents/virtual_agent.py",
                "engine/lmstudio/client.py",
                "engine/nexus/client.py",
            ]
        return self.seed_notebook(slot_name, paths)

    def get_or_create_research(self, topic: str) -> Dict[str, Any]:
        """Return (or create) a research notebook for *topic*.

        Args:
            topic: Short topic label (e.g. ``mcp-state-persistence``).

        Returns:
            Dict with notebook metadata.
        """
        slot_name = f"research-{topic}"
        return self.ensure_notebook(slot_name)

    def rotate_notebook(self, slot_name: str) -> Dict[str, Any]:
        """Delete and recreate a notebook slot (e.g. for stale content).

        Args:
            slot_name: Slot to rotate.

        Returns:
            Dict with the freshly-created notebook metadata.
        """
        engine = get_nlm_engine()

        with self._lock:
            existing = self._notebooks.pop(slot_name, None)

        if existing:
            notebook_id = existing.get("notebook_id", "")
            if notebook_id:
                try:
                    engine.delete_notebook(notebook_id)
                    logger.info("Deleted notebook %s for rotation", notebook_id)
                except Exception as exc:
                    logger.warning("Failed to delete notebook %s: %s", notebook_id, exc)

        with self._lock:
            self._save_metadata()

        return self.ensure_notebook(slot_name)

    def health(self) -> Dict[str, Any]:
        """Report health of all managed notebooks.

        Returns:
            Dict with per-slot health info and overall summary.
        """
        now = time.time()
        slots: List[Dict[str, Any]] = []

        with self._lock:
            entries = list(self._notebooks.values())

        for entry in entries:
            created_iso = entry.get("created_at", "")
            age_days: Optional[float] = None
            if created_iso:
                try:
                    created_ts = datetime.fromisoformat(created_iso).timestamp()
                    age_days = round((now - created_ts) / 86400, 1)
                except (ValueError, OSError):
                    pass

            slots.append({
                "slot_name": entry["slot_name"],
                "notebook_id": entry.get("notebook_id", ""),
                "source_count": entry.get("source_count", 0),
                "age_days": age_days,
                "last_seeded": entry.get("last_seeded"),
                "last_asked": entry.get("last_asked"),
            })

        return {
            "total_slots": len(slots),
            "slots": slots,
        }

    def cleanup_stale(self, max_age_days: int = 30) -> List[str]:
        """Delete research notebooks older than *max_age_days*.

        Only notebooks whose slot name starts with ``research-`` are
        considered for cleanup.

        Args:
            max_age_days: Maximum age in days before a research notebook
                is considered stale.

        Returns:
            List of slot names that were removed.
        """
        now = time.time()
        cutoff = max_age_days * 86400
        engine = get_nlm_engine()
        removed: List[str] = []

        with self._lock:
            candidates = [
                (name, entry)
                for name, entry in self._notebooks.items()
                if name.startswith("research-")
            ]

        for slot_name, entry in candidates:
            created_iso = entry.get("created_at", "")
            if not created_iso:
                continue
            try:
                created_ts = datetime.fromisoformat(created_iso).timestamp()
            except (ValueError, OSError):
                continue

            if (now - created_ts) > cutoff:
                notebook_id = entry.get("notebook_id", "")
                if notebook_id:
                    try:
                        engine.delete_notebook(notebook_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to delete stale notebook %s: %s",
                            notebook_id, exc,
                        )
                with self._lock:
                    self._notebooks.pop(slot_name, None)
                removed.append(slot_name)
                logger.info("Cleaned up stale notebook slot '%s'", slot_name)

        if removed:
            with self._lock:
                self._save_metadata()

        return removed

    def list_managed(self) -> List[Dict[str, Any]]:
        """List all managed notebook slots with metadata.

        Returns:
            List of dicts, one per slot.
        """
        with self._lock:
            return [dict(v) for v in self._notebooks.values()]

    # ──── Internal Helpers ────

    def _load_metadata(self) -> None:
        """Load notebook metadata from the JSON file."""
        if not self._metadata_path.exists():
            self._notebooks = {}
            return
        try:
            raw = self._metadata_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._notebooks = data
            else:
                self._notebooks = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load NLM metadata from %s: %s", self._metadata_path, exc)
            self._notebooks = {}

    def _save_metadata(self) -> None:
        """Persist notebook metadata to the JSON file (caller holds lock)."""
        try:
            self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self._metadata_path.write_text(
                json.dumps(self._notebooks, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save NLM metadata to %s: %s", self._metadata_path, exc)


def _now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ──── Singleton ────

_manager: Optional[NLMNotebookManager] = None
_manager_lock = threading.Lock()


def get_notebook_manager() -> NLMNotebookManager:
    """Return the global NLMNotebookManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = NLMNotebookManager()
    return _manager
