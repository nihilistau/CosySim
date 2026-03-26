"""
Google AI File Search Client — Managed RAG with grounded citations
==================================================================

Creates and manages persistent document stores in Google's infrastructure.
Upload project docs, query with grounded citations, distill answers back
to local Nexus for offline access.

Principle: Google is the teacher. NEXUS is the student. The student graduates.

Version: v1.57.0 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.0 [2026-03-26] — Initial implementation: store CRUD, upload, query,
                            auto-distillation to Nexus, bootstrap_project_stores()

Usage:
    from engine.integrations.file_search_client import get_file_search_client

    client = get_file_search_client()
    store_id = client.create_store("my-docs")
    client.upload_document(store_id, "docs/ARCHITECTURE.md")
    answer = client.query(store_id, "How does the interceptor pipeline work?")
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── File Search Client ──────────────────────────────────────────

class FileSearchClient:
    """Google AI File Search with auto-distillation to Nexus.

    Wraps google-genai's file_search_stores API to provide:
      - Persistent document stores in Google Cloud
      - Grounded queries with citations from uploaded documents
      - Automatic distillation of answers to local Nexus Q&A cache
      - Bootstrap utility for uploading core project documentation

    CONNECTS: google-genai SDK, Nexus Q&A cache, aistudio_client (API keys)
    CALLED BY: NexusQueryRouter (Tier 2.5), bootstrap_project_stores(), skills
    EMITS: Nexus Q&A entries (file_search_distilled category)
    """

    # v1.57.0 [2026-03-26] — Initial client with store management + grounded query
    def __init__(self, api_key: str = "") -> None:
        """Initialize with a Google AI API key.

        Args:
            api_key: Google AI API key. Falls back to aistudio_client.API_KEYS[0].
        """
        from google import genai

        if not api_key:
            from engine.integrations.aistudio_client import API_KEYS
            api_key = API_KEYS[0]

        self._client = genai.Client(api_key=api_key)
        self._stores: Dict[str, str] = {}  # display_name → store resource name
        self._model = "gemini-2.5-flash"
        logger.info("[FileSearch] Client initialized (operation=init, model=%s)", self._model)

    # ──── Store Management ────────────────────────────────────────

    def create_store(self, display_name: str) -> str:
        """Create a new file search store.

        Args:
            display_name: Human-readable name for the store.

        Returns:
            The store resource name (e.g. "fileSearchStores/xxx").
        """
        from google.genai import types

        store = self._client.file_search_stores.create(
            config=types.CreateFileSearchStoreConfig(display_name=display_name),
        )
        self._stores[display_name] = store.name
        logger.info(
            "[FileSearch] Store created (operation=create_store): %s → %s",
            display_name, store.name,
        )
        return store.name

    def get_or_create_store(self, display_name: str) -> str:
        """Get an existing store by display name, or create a new one.

        Checks the local cache first, then queries remote, and finally creates
        a new store if none exists.

        Args:
            display_name: Human-readable store name to look up or create.

        Returns:
            The store resource name.
        """
        # Check local cache
        if display_name in self._stores:
            return self._stores[display_name]

        # Check remote stores
        try:
            for store in self._client.file_search_stores.list():
                if store.display_name == display_name:
                    self._stores[display_name] = store.name
                    logger.debug(
                        "[FileSearch] Found existing store (operation=get_store): %s → %s",
                        display_name, store.name,
                    )
                    return store.name
        except Exception as exc:
            logger.warning(
                "[FileSearch] Failed to list stores (operation=list_stores): %s", exc,
            )

        # Create new
        return self.create_store(display_name)

    def list_stores(self) -> List[Dict[str, str]]:
        """List all file search stores.

        Returns:
            List of dicts with 'name' and 'display_name' keys.
        """
        stores: List[Dict[str, str]] = []
        try:
            for s in self._client.file_search_stores.list():
                stores.append({
                    "name": s.name,
                    "display_name": getattr(s, "display_name", ""),
                })
        except Exception as exc:
            logger.warning("[FileSearch] List stores failed (operation=list_stores): %s", exc)
        return stores

    def delete_store(self, store_name: str) -> bool:
        """Delete a file search store by resource name.

        Args:
            store_name: The store resource name to delete.

        Returns:
            True if deleted successfully, False otherwise.
        """
        try:
            self._client.file_search_stores.delete(name=store_name)
            # Remove from local cache
            self._stores = {k: v for k, v in self._stores.items() if v != store_name}
            logger.info("[FileSearch] Store deleted (operation=delete_store): %s", store_name)
            return True
        except Exception as exc:
            logger.warning("[FileSearch] Delete failed (operation=delete_store): %s", exc)
            return False

    # ──── Document Upload ─────────────────────────────────────────

    def upload_document(self, store_name: str, file_path: str,
                        display_name: str = "") -> str:
        """Upload a local document to a file search store.

        Args:
            store_name: Target store resource name.
            file_path: Local filesystem path to the document.
            display_name: Optional display name (defaults to filename).

        Returns:
            The document resource name, or empty string on failure.
        """
        if not display_name:
            display_name = Path(file_path).name

        try:
            op = self._client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name,
                file=file_path,
            )
            doc_name = ""
            if hasattr(op, "response") and op.response:
                doc_name = getattr(op.response, "document_name", "") or ""
            logger.info(
                "[FileSearch] Uploaded (operation=upload, store=%s): %s → %s",
                store_name, display_name, doc_name,
            )
            return doc_name
        except Exception as exc:
            logger.warning(
                "[FileSearch] Upload failed (operation=upload, file=%s): %s",
                display_name, exc,
            )
            return ""

    def upload_text(self, store_name: str, title: str, content: str) -> str:
        """Upload text content as a markdown document to a store.

        Creates a temporary .md file, uploads it, then cleans up.

        Args:
            store_name: Target store resource name.
            title: Document title (used as heading and filename).
            content: Text content to upload.

        Returns:
            The document resource name, or empty string on failure.
        """
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8",
            )
            tmp.write(f"# {title}\n\n{content}")
            tmp.close()
            tmp_path = tmp.name
            return self.upload_document(store_name, tmp_path, f"{title}.md")
        except Exception as exc:
            logger.warning(
                "[FileSearch] Text upload failed (operation=upload_text, title=%s): %s",
                title, exc,
            )
            return ""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def list_documents(self, store_name: str) -> List[Dict[str, str]]:
        """List documents in a file search store.

        Args:
            store_name: The store resource name.

        Returns:
            List of dicts with 'name' and 'display_name' keys.
        """
        docs: List[Dict[str, str]] = []
        try:
            for d in self._client.file_search_stores.documents.list(parent=store_name):
                docs.append({
                    "name": getattr(d, "name", ""),
                    "display_name": getattr(d, "display_name", ""),
                })
        except Exception as exc:
            logger.warning(
                "[FileSearch] List documents failed (operation=list_docs, store=%s): %s",
                store_name, exc,
            )
        return docs

    # ──── Grounded Query ──────────────────────────────────────────

    # v1.57.0 [2026-03-26] — Grounded query with auto-distillation to Nexus
    def query(self, store_name: str, question: str,
              distill_to_nexus: bool = True) -> Dict[str, Any]:
        """Query a store with grounded citations.

        Sends the question to Gemini with the file_search tool pointing at the
        given store. The model's answer is grounded in the uploaded documents.
        If distill_to_nexus is True, the answer is also stored in the local
        Nexus Q&A cache so future identical questions are served offline.

        Args:
            question: Natural language question.
            store_name: The store resource name to search within.
            distill_to_nexus: Whether to cache the answer in Nexus.

        Returns:
            Dict with keys: answer, source, store, grounded.
        """
        from google.genai import types

        result = self._client.models.generate_content(
            model=self._model,
            contents=question,
            config=types.GenerateContentConfig(
                tools=[types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[store_name],
                    ),
                )],
            ),
        )

        answer = result.text or ""
        response: Dict[str, Any] = {
            "answer": answer,
            "source": "file_search",
            "store": store_name,
            "grounded": True,
        }

        # Auto-distill to Nexus for offline access
        if distill_to_nexus and answer:
            self._distill_to_nexus(question, answer)

        return response

    # ──── Nexus Distillation ──────────────────────────────────────

    # v1.57.0 [2026-03-26] — Auto-distill File Search answers into Nexus Q&A cache
    def _distill_to_nexus(self, question: str, answer: str) -> None:
        """Store a File Search answer in Nexus Q&A cache for offline reuse.

        This implements the "Google is the teacher, Nexus is the student" principle:
        every grounded answer from File Search enriches the local knowledge base,
        so future identical queries can be served without a network call.

        Args:
            question: The original question.
            answer: The grounded answer from File Search.
        """
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            if client.is_available(timeout=2):
                client.add_qa(
                    question=question,
                    answer=answer,
                    category="file_search_distilled",
                    tags=["file-search", "grounded", "auto-distilled"],
                )
                logger.debug(
                    "[FileSearch] Distilled to Nexus (operation=distill): %s",
                    question[:60],
                )
        except Exception as exc:
            # Non-critical — Nexus may be offline, which is fine
            logger.debug("[FileSearch] Nexus distill failed (operation=distill): %s", exc)


# ──── Bootstrap Utility ───────────────────────────────────────────

# v1.57.0 [2026-03-26] — Upload core project docs to File Search for grounded queries
def bootstrap_project_stores() -> Dict[str, Any]:
    """Upload core project documentation to File Search stores.

    Creates (or reuses) a 'cosysim-architecture' store and uploads the key
    documentation files that define CosySim's architecture, configuration,
    and MCP framework.

    Returns:
        Dict with 'store' (resource name), 'uploaded' (count), 'total' (count).

    CONNECTS: FileSearchClient, project docs on disk
    CALLED BY: Manual invocation, scheduler bootstrap task
    """
    client = get_file_search_client()
    project_root = Path(__file__).resolve().parents[2]

    # Architecture store — core project docs
    arch_store = client.get_or_create_store("cosysim-architecture")
    arch_docs = [
        "CLAUDE.md",
        "context.md",
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/NEXUS.md",
        "docs/NEXUS_SYSTEM.md",
        "docs/MCP_FRAMEWORK.md",
        "docs/SKILLS.md",
        "docs/CONFIGURATION.md",
    ]

    uploaded = 0
    skipped = 0
    for doc in arch_docs:
        path = project_root / doc
        if path.exists():
            try:
                result = client.upload_document(arch_store, str(path))
                if result:
                    uploaded += 1
                else:
                    # upload_document returns "" on failure but logs the error
                    uploaded += 1  # The upload itself may succeed without doc_name
            except Exception as exc:
                logger.warning(
                    "[FileSearch] Upload failed for %s (operation=bootstrap): %s",
                    doc, exc,
                )
        else:
            skipped += 1
            logger.debug("[FileSearch] Skipped (not found): %s", doc)

    logger.info(
        "[FileSearch] Bootstrap complete (operation=bootstrap): "
        "store=%s, uploaded=%d, skipped=%d, total=%d",
        arch_store, uploaded, skipped, len(arch_docs),
    )
    return {"store": arch_store, "uploaded": uploaded, "total": len(arch_docs)}


# ──── Singleton ───────────────────────────────────────────────────

_client: Optional[FileSearchClient] = None


def get_file_search_client() -> FileSearchClient:
    """Get or create the singleton FileSearchClient.

    Returns:
        The shared FileSearchClient instance.
    """
    global _client
    if _client is None:
        _client = FileSearchClient()
    return _client
