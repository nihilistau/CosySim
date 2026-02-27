"""NLM Deep Storage — archive all NotebookLM content into Nexus deep storage.

Pulls notebook metadata, sources, conversations, generated content, and notes
from NotebookLM and stores them in Nexus with structured tags and chain IDs
for full retrieval. Supports three storage tiers:

- **Ground Truth** (deep): Complete notebook snapshots — all sources, conversations,
  metadata, generated artifacts. Content-type ``notebook_archive``.
- **Knowledge Layer** (mid): Distilled Q&A, summaries, research findings.
  Stored via normal Nexus entries with category ``nlm_knowledge``.
- **Working Layer** (surface): Active notebook references, quick-access pointers.
  Stored in the notebook manager's JSON metadata.

Usage:
    from engine.nexus.nlm_deep_storage import get_deep_storage
    ds = get_deep_storage()
    ds.archive_all()                   # Pull all notebooks into deep storage
    ds.archive_notebook("nb-id-123")   # Archive a single notebook
    ds.retrieve("nb-id-123")           # Retrieve archived notebook
    ds.list_archives()                 # List all archived notebooks
    ds.search_conversations("MCP")     # Search across all archived conversations
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Constants ────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ARCHIVE_DIR = "data/nlm_archives"

CONTENT_TYPE_ARCHIVE = "notebook_archive"
CONTENT_TYPE_CONVERSATION = "notebook_conversation"
CONTENT_TYPE_SOURCE = "notebook_source"
CATEGORY_DEEP = "nlm_deep_storage"
CATEGORY_KNOWLEDGE = "nlm_knowledge"


# ──── Data Structures ────

def _now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _chain_id() -> str:
    """Generate a unique chain ID for conversation threading."""
    return f"chain-{uuid.uuid4().hex[:12]}"


def _content_hash(content: str) -> str:
    """Generate a hash for deduplication."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


# ──── Deep Storage Engine ────

class NLMDeepStorage:
    """Archive NotebookLM content into Nexus deep storage.

    Provides a complete archival pipeline that preserves the full state of
    NLM notebooks including metadata, sources, conversations, notes, and
    generated content. All archived data is retrievable via Nexus search.

    Args:
        archive_dir: Local directory for archive index. Defaults to
            ``data/nlm_archives/`` relative to project root.
    """

    def __init__(self, archive_dir: Optional[str] = None) -> None:
        cfg = get_config()
        rel = archive_dir or cfg.get("notebooklm.archive_dir", _DEFAULT_ARCHIVE_DIR)
        self._archive_dir = _PROJECT_ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._archive_dir / "archive_index.json"
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()

    # ──── Public API ────

    def archive_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Archive a single NLM notebook into Nexus deep storage.

        Pulls metadata, sources, conversations, notes, and generated content
        from NotebookLM, stores each piece in Nexus, and creates a master
        archive entry linking everything together.

        Args:
            notebook_id: The NLM notebook UUID to archive.

        Returns:
            Dict with archive results: entries_stored, conversations_stored, etc.
        """
        from engine.nexus.nlm_engine import get_nlm_engine
        from engine.nexus.client import get_nexus_client

        engine = get_nlm_engine()
        client = get_nexus_client()
        start = time.time()

        result: Dict[str, Any] = {
            "notebook_id": notebook_id,
            "archived_at": _now_iso(),
            "entries_stored": 0,
            "conversations_stored": 0,
            "sources_stored": 0,
            "notes_stored": 0,
            "errors": [],
        }

        # 1. Fetch notebook metadata
        nb_meta = engine.get_notebook(notebook_id)
        if not nb_meta or nb_meta.get("error"):
            result["errors"].append(f"Failed to fetch notebook: {nb_meta}")
            return result

        nb_name = nb_meta.get("name", nb_meta.get("title", notebook_id))
        archive_id = f"archive-{notebook_id[:12]}-{int(time.time())}"
        chain = _chain_id()

        # 2. Store notebook metadata as ground truth
        meta_content = json.dumps(nb_meta, indent=2, default=str)
        meta_entry_id = client.add_entry(
            title=f"[Archive] {nb_name} — metadata",
            content=meta_content,
            content_type=CONTENT_TYPE_ARCHIVE,
            category=CATEGORY_DEEP,
            tags=["notebook", "metadata", "ground_truth", archive_id, chain],
        )
        if meta_entry_id:
            result["entries_stored"] += 1
            logger.info("Archived metadata for notebook '%s'", nb_name)
        else:
            result["errors"].append("Failed to store metadata entry")

        # 3. Archive sources
        sources = nb_meta.get("sources", [])
        if isinstance(sources, list):
            for src in sources:
                src_content = json.dumps(src, indent=2, default=str)
                src_title = src.get("title", src.get("name", "Unnamed source"))
                src_id = client.add_entry(
                    title=f"[Source] {nb_name}/{src_title}",
                    content=src_content,
                    content_type=CONTENT_TYPE_SOURCE,
                    category=CATEGORY_DEEP,
                    tags=["notebook_source", archive_id, chain,
                          src.get("source_type", "unknown")],
                )
                if src_id:
                    result["sources_stored"] += 1
                else:
                    result["errors"].append(f"Failed to store source: {src_title}")

        # 4. Archive conversations (if available in metadata)
        conversations = nb_meta.get("conversations", [])
        if isinstance(conversations, list):
            for idx, conv in enumerate(conversations):
                conv_chain = f"{chain}-conv-{idx}"
                if isinstance(conv, str):
                    conv_content = conv
                else:
                    conv_content = json.dumps(conv, indent=2, default=str)

                conv_id = client.add_entry(
                    title=f"[Conversation] {nb_name} #{idx + 1}",
                    content=conv_content,
                    content_type=CONTENT_TYPE_CONVERSATION,
                    category=CATEGORY_DEEP,
                    tags=["conversation", archive_id, chain, conv_chain],
                )
                if conv_id:
                    result["conversations_stored"] += 1
                else:
                    result["errors"].append(f"Failed to store conversation #{idx + 1}")

        # 5. Archive notes
        notes = nb_meta.get("notes", [])
        if isinstance(notes, list):
            for idx, note in enumerate(notes):
                note_content = note if isinstance(note, str) else json.dumps(note, default=str)
                note_id = client.add_entry(
                    title=f"[Note] {nb_name} #{idx + 1}",
                    content=note_content,
                    content_type="note",
                    category=CATEGORY_DEEP,
                    tags=["notebook_note", archive_id, chain],
                )
                if note_id:
                    result["notes_stored"] += 1

        # 6. Create master archive index entry
        master_content = json.dumps({
            "archive_id": archive_id,
            "notebook_id": notebook_id,
            "notebook_name": nb_name,
            "chain_id": chain,
            "archived_at": result["archived_at"],
            "entries_stored": result["entries_stored"],
            "sources_stored": result["sources_stored"],
            "conversations_stored": result["conversations_stored"],
            "notes_stored": result["notes_stored"],
            "duration_seconds": round(time.time() - start, 2),
        }, indent=2)

        master_id = client.add_entry(
            title=f"[Archive Index] {nb_name}",
            content=master_content,
            content_type=CONTENT_TYPE_ARCHIVE,
            category=CATEGORY_DEEP,
            tags=["archive_index", archive_id, chain, "master"],
        )

        # 7. Update local index
        self._index[notebook_id] = {
            "archive_id": archive_id,
            "notebook_name": nb_name,
            "chain_id": chain,
            "archived_at": result["archived_at"],
            "master_entry_id": master_id,
            "stats": {
                "entries": result["entries_stored"],
                "sources": result["sources_stored"],
                "conversations": result["conversations_stored"],
                "notes": result["notes_stored"],
            },
        }
        self._save_index()

        result["archive_id"] = archive_id
        result["chain_id"] = chain
        result["duration_seconds"] = round(time.time() - start, 2)
        logger.info(
            "Archived notebook '%s': %d entries, %d sources, %d conversations in %.1fs",
            nb_name, result["entries_stored"], result["sources_stored"],
            result["conversations_stored"], result["duration_seconds"],
        )
        return result

    def archive_all(self) -> Dict[str, Any]:
        """Archive all NLM notebooks into Nexus deep storage.

        Returns:
            Dict with per-notebook results and totals.
        """
        from engine.nexus.nlm_engine import get_nlm_engine
        engine = get_nlm_engine()
        notebooks = engine.list_notebooks()

        results: Dict[str, Any] = {
            "archived_at": _now_iso(),
            "total_notebooks": len(notebooks),
            "successful": 0,
            "failed": 0,
            "notebooks": [],
        }

        for nb in notebooks:
            nb_id = nb.get("id", nb.get("notebook_id", ""))
            if not nb_id:
                results["failed"] += 1
                continue

            try:
                result = self.archive_notebook(nb_id)
                if result.get("errors"):
                    results["failed"] += 1
                else:
                    results["successful"] += 1
                results["notebooks"].append(result)
            except Exception as exc:
                logger.error("Failed to archive notebook %s: %s", nb_id, exc)
                results["failed"] += 1
                results["notebooks"].append({
                    "notebook_id": nb_id,
                    "error": str(exc),
                })

        logger.info(
            "Archive all complete: %d/%d successful",
            results["successful"], results["total_notebooks"],
        )
        return results

    def archive_from_har(self, har_path: str) -> Dict[str, Any]:
        """Archive notebook content extracted from a browser HAR file.

        Uses the HARExtractor to parse browser captures and stores all
        extracted data in Nexus deep storage.

        Args:
            har_path: Path to the HAR file.

        Returns:
            Dict with archive results.
        """
        from engine.nexus.har_extractor import HARExtractor

        extractor = HARExtractor()
        nb_data = extractor.extract(har_path)

        if not nb_data or not nb_data.notebook_id:
            return {"error": "Failed to extract notebook data from HAR"}

        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        archive_id = f"archive-har-{nb_data.notebook_id[:12]}-{int(time.time())}"
        chain = _chain_id()
        result: Dict[str, Any] = {
            "notebook_id": nb_data.notebook_id,
            "notebook_name": nb_data.notebook_name,
            "archive_id": archive_id,
            "chain_id": chain,
            "archived_at": _now_iso(),
            "entries_stored": 0,
            "sources_stored": 0,
            "conversations_stored": 0,
            "documents_stored": 0,
            "notes_stored": 0,
        }

        # Store full notebook snapshot
        snapshot = {
            "notebook_id": nb_data.notebook_id,
            "notebook_name": nb_data.notebook_name,
            "summary": nb_data.summary,
            "stats": nb_data.stats,
            "source_count": len(nb_data.sources),
            "document_count": len(nb_data.documents),
            "conversation_count": len(nb_data.conversations),
            "note_count": len(nb_data.notes),
        }
        meta_id = client.add_entry(
            title=f"[Archive] {nb_data.notebook_name} — HAR snapshot",
            content=json.dumps(snapshot, indent=2, default=str),
            content_type=CONTENT_TYPE_ARCHIVE,
            category=CATEGORY_DEEP,
            tags=["notebook", "metadata", "har_extract", archive_id, chain],
        )
        if meta_id:
            result["entries_stored"] += 1

        # Store sources
        for src in nb_data.sources:
            src_content = json.dumps(src, indent=2, default=str)
            src_id = client.add_entry(
                title=f"[Source] {nb_data.notebook_name}/{src.get('title', 'Unnamed')}",
                content=src_content,
                content_type=CONTENT_TYPE_SOURCE,
                category=CATEGORY_DEEP,
                tags=["notebook_source", "har_extract", archive_id, chain],
            )
            if src_id:
                result["sources_stored"] += 1

        # Store documents
        for idx, doc in enumerate(nb_data.documents):
            doc_id = client.add_entry(
                title=f"[Document] {nb_data.notebook_name} #{idx + 1}",
                content=doc if isinstance(doc, str) else json.dumps(doc, default=str),
                content_type="document",
                category=CATEGORY_DEEP,
                tags=["notebook_document", "har_extract", archive_id, chain],
            )
            if doc_id:
                result["documents_stored"] += 1

        # Store conversations with chain IDs
        for idx, conv in enumerate(nb_data.conversations):
            conv_chain = f"{chain}-conv-{idx}"
            conv_content = conv if isinstance(conv, str) else json.dumps(conv, default=str)
            conv_id = client.add_entry(
                title=f"[Conversation] {nb_data.notebook_name} #{idx + 1}",
                content=conv_content,
                content_type=CONTENT_TYPE_CONVERSATION,
                category=CATEGORY_DEEP,
                tags=["conversation", "har_extract", archive_id, chain, conv_chain],
            )
            if conv_id:
                result["conversations_stored"] += 1

        # Store notes
        for idx, note in enumerate(nb_data.notes):
            note_content = note if isinstance(note, str) else json.dumps(note, default=str)
            note_id = client.add_entry(
                title=f"[Note] {nb_data.notebook_name} #{idx + 1}",
                content=note_content,
                content_type="note",
                category=CATEGORY_DEEP,
                tags=["notebook_note", "har_extract", archive_id, chain],
            )
            if note_id:
                result["notes_stored"] += 1

        # Master index
        master_id = client.add_entry(
            title=f"[Archive Index] {nb_data.notebook_name} (HAR)",
            content=json.dumps(result, indent=2, default=str),
            content_type=CONTENT_TYPE_ARCHIVE,
            category=CATEGORY_DEEP,
            tags=["archive_index", archive_id, chain, "master", "har_extract"],
        )

        self._index[nb_data.notebook_id] = {
            "archive_id": archive_id,
            "notebook_name": nb_data.notebook_name,
            "chain_id": chain,
            "archived_at": result["archived_at"],
            "master_entry_id": master_id,
            "source": "har",
            "stats": {
                "entries": result["entries_stored"],
                "sources": result["sources_stored"],
                "conversations": result["conversations_stored"],
                "documents": result["documents_stored"],
                "notes": result["notes_stored"],
            },
        }
        self._save_index()

        logger.info(
            "Archived HAR notebook '%s': %d sources, %d conversations, %d docs",
            nb_data.notebook_name, result["sources_stored"],
            result["conversations_stored"], result["documents_stored"],
        )
        return result

    def store_conversation(
        self,
        notebook_id: str,
        messages: List[Dict[str, str]],
        topic: str = "",
        chain_id: Optional[str] = None,
        parent_chain_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a conversation chain in deep storage.

        Each conversation gets a unique chain ID. Conversations can be linked
        via parent_chain_id to form hierarchical threads.

        Args:
            notebook_id: The NLM notebook UUID.
            messages: List of ``{"role": "user"|"assistant", "content": "..."}`` dicts.
            topic: Topic tag for the conversation.
            chain_id: Optional pre-assigned chain ID. Auto-generated if absent.
            parent_chain_id: Optional parent chain for threading.

        Returns:
            Dict with chain_id, entry_id, message_count.
        """
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        cid = chain_id or _chain_id()
        tags = ["conversation", "deep_storage", cid]
        if parent_chain_id:
            tags.append(f"parent:{parent_chain_id}")
        if topic:
            tags.append(f"topic:{topic}")

        # Format conversation
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted_messages.append(f"**{role.upper()}:** {content}")
        conversation_text = "\n\n---\n\n".join(formatted_messages)

        nb_name = self._index.get(notebook_id, {}).get("notebook_name", notebook_id)
        topic_label = f" — {topic}" if topic else ""
        entry_id = client.add_entry(
            title=f"[Conversation] {nb_name}{topic_label}",
            content=conversation_text,
            content_type=CONTENT_TYPE_CONVERSATION,
            category=CATEGORY_DEEP,
            tags=tags,
        )

        return {
            "chain_id": cid,
            "entry_id": entry_id,
            "notebook_id": notebook_id,
            "message_count": len(messages),
            "parent_chain_id": parent_chain_id,
            "stored_at": _now_iso(),
        }

    def retrieve(self, notebook_id: str) -> Dict[str, Any]:
        """Retrieve all archived content for a notebook.

        Args:
            notebook_id: The NLM notebook UUID.

        Returns:
            Dict with metadata, sources, conversations, notes from Nexus.
        """
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        archive_info = self._index.get(notebook_id)
        if not archive_info:
            return {"error": f"No archive found for notebook {notebook_id}"}

        archive_id = archive_info["archive_id"]
        chain_id = archive_info["chain_id"]

        # Search by archive_id tag
        entries = client.search(archive_id, limit=100)

        result: Dict[str, Any] = {
            "notebook_id": notebook_id,
            "notebook_name": archive_info.get("notebook_name", ""),
            "archived_at": archive_info.get("archived_at", ""),
            "chain_id": chain_id,
            "metadata": [],
            "sources": [],
            "conversations": [],
            "notes": [],
            "documents": [],
            "other": [],
        }

        for entry in entries:
            ctype = entry.get("content_type", "")
            title = entry.get("title", "")
            if ctype == CONTENT_TYPE_ARCHIVE:
                result["metadata"].append(entry)
            elif ctype == CONTENT_TYPE_SOURCE:
                result["sources"].append(entry)
            elif ctype == CONTENT_TYPE_CONVERSATION:
                result["conversations"].append(entry)
            elif "[Note]" in title:
                result["notes"].append(entry)
            elif "[Document]" in title:
                result["documents"].append(entry)
            else:
                result["other"].append(entry)

        return result

    def list_archives(self) -> List[Dict[str, Any]]:
        """List all archived notebooks.

        Returns:
            List of archive metadata dicts.
        """
        return [
            {
                "notebook_id": nb_id,
                **info,
            }
            for nb_id, info in self._index.items()
        ]

    def search_conversations(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search across all archived conversations.

        Args:
            query: Search query string.
            limit: Maximum results.

        Returns:
            List of matching conversation entries.
        """
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        results = client.search(query, limit=limit * 2)
        conversations = [
            r for r in results
            if r.get("content_type") == CONTENT_TYPE_CONVERSATION
            or "conversation" in (r.get("title", "").lower())
        ]
        return conversations[:limit]

    def get_chain(self, chain_id: str) -> List[Dict[str, Any]]:
        """Retrieve all entries in a conversation chain.

        Args:
            chain_id: The chain UUID.

        Returns:
            List of entries in the chain, ordered by creation.
        """
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()

        results = client.search(chain_id, limit=50)
        chain_entries = [
            r for r in results
            if chain_id in r.get("tags", []) or chain_id in str(r.get("tags", ""))
        ]
        return sorted(chain_entries, key=lambda e: e.get("created_at", ""))

    def stats(self) -> Dict[str, Any]:
        """Get deep storage statistics.

        Returns:
            Dict with archive counts, total entries, disk usage.
        """
        total_entries = sum(
            info.get("stats", {}).get("entries", 0)
            + info.get("stats", {}).get("sources", 0)
            + info.get("stats", {}).get("conversations", 0)
            + info.get("stats", {}).get("notes", 0)
            + info.get("stats", {}).get("documents", 0)
            for info in self._index.values()
        )

        return {
            "total_archives": len(self._index),
            "total_entries_stored": total_entries,
            "archive_dir": str(self._archive_dir),
            "index_file": str(self._index_path),
            "archives": {
                nb_id: {
                    "name": info.get("notebook_name", ""),
                    "archived_at": info.get("archived_at", ""),
                    "stats": info.get("stats", {}),
                }
                for nb_id, info in self._index.items()
            },
        }

    def delete_archive(self, notebook_id: str) -> Dict[str, Any]:
        """Delete an archived notebook from deep storage.

        Removes the local index entry. Nexus entries are left for
        the maintenance system to clean up via tags.

        Args:
            notebook_id: The NLM notebook UUID.

        Returns:
            Dict with deletion status.
        """
        if notebook_id not in self._index:
            return {"deleted": False, "reason": "Not found in archive index"}

        archive_info = self._index.pop(notebook_id)
        self._save_index()

        logger.info(
            "Removed archive index for '%s' (archive_id: %s)",
            archive_info.get("notebook_name", notebook_id),
            archive_info.get("archive_id", "?"),
        )
        return {
            "deleted": True,
            "notebook_id": notebook_id,
            "archive_id": archive_info.get("archive_id"),
        }

    # ──── Private ────

    def _load_index(self) -> None:
        """Load the archive index from disk."""
        if self._index_path.exists():
            try:
                text = self._index_path.read_text(encoding="utf-8")
                self._index = json.loads(text)
            except Exception as exc:
                logger.warning("Failed to load archive index: %s", exc)
                self._index = {}

    def _save_index(self) -> None:
        """Persist the archive index to disk."""
        try:
            self._index_path.write_text(
                json.dumps(self._index, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save archive index: %s", exc)


# ──── Singleton ────

_instance: Optional[NLMDeepStorage] = None


def get_deep_storage() -> NLMDeepStorage:
    """Get the singleton NLMDeepStorage instance."""
    global _instance
    if _instance is None:
        _instance = NLMDeepStorage()
    return _instance
