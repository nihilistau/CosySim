"""
Google AI File Search Client — Managed RAG with grounded citations
==================================================================

Creates and manages persistent document stores in Google's infrastructure.
Upload project docs, query with grounded citations, distill answers back
to local Nexus for offline access.

Principle: Google is the teacher. NEXUS is the student. The student graduates.

Version: v1.57.1 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.1 [2026-03-26] — MIME type auto-detection for uploads (.md/.py/.yaml etc.),
                            bootstrap_code_store() for engine source files,
                            display_name passthrough in upload config
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


# ──── MIME Type Map ───────────────────────────────────────────────

# v1.57.1 [2026-03-26] — Auto-detect MIME for common file types
# The google-genai SDK infers MIME from extension, but fails on .md and others.
# We provide explicit mappings to avoid "Unknown mime type" errors.
_MIME_MAP = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".json": "application/json",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".html": "text/html",
    ".css": "text/css",
    ".csv": "text/csv",
    ".xml": "text/xml",
    ".sh": "text/x-shellscript",
    ".ps1": "text/plain",
    ".toml": "text/plain",
    ".cfg": "text/plain",
    ".ini": "text/plain",
    ".log": "text/plain",
    ".rst": "text/x-rst",
}


def _detect_mime(file_path: str) -> str:
    """Detect MIME type from file extension using the local map.

    Args:
        file_path: Path to the file.

    Returns:
        MIME type string, or empty string if unknown (let SDK try).
    """
    ext = Path(file_path).suffix.lower()
    return _MIME_MAP.get(ext, "")


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

    # v1.57.1 [2026-03-26] — MIME auto-detection + display_name via config
    def upload_document(self, store_name: str, file_path: str,
                        display_name: str = "") -> str:
        """Upload a local document to a file search store.

        Automatically detects MIME type for common extensions (.md, .py, .yaml,
        etc.) to prevent "Unknown mime type" errors from the Google API.

        Args:
            store_name: Target store resource name.
            file_path: Local filesystem path to the document.
            display_name: Optional display name (defaults to filename).

        Returns:
            The document resource name, or empty string on failure.
        """
        from google.genai import types

        if not display_name:
            display_name = Path(file_path).name

        # Build upload config with MIME type detection and display name
        config_kwargs: Dict[str, Any] = {"display_name": display_name}
        mime = _detect_mime(file_path)
        if mime:
            config_kwargs["mime_type"] = mime
            logger.debug(
                "[FileSearch] Detected MIME (operation=upload): %s → %s",
                display_name, mime,
            )

        try:
            op = self._client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name,
                file=file_path,
                config=types.UploadToFileSearchStoreConfig(**config_kwargs),
            )
            doc_name = ""
            if hasattr(op, "response") and op.response:
                doc_name = getattr(op.response, "document_name", "") or ""
            logger.info(
                "[FileSearch] Uploaded (operation=upload, store=%s, mime=%s): %s → %s",
                store_name, mime or "auto", display_name, doc_name,
            )
            return doc_name
        except Exception as exc:
            logger.warning(
                "[FileSearch] Upload failed (operation=upload, file=%s, mime=%s): %s",
                display_name, mime or "auto", exc,
            )
            return ""

    # v1.57.1 [2026-03-26] — upload_text now uses .md extension (MIME auto-detected)
    def upload_text(self, store_name: str, title: str, content: str) -> str:
        """Upload text content as a markdown document to a store.

        Creates a temporary .md file, uploads it, then cleans up.
        MIME type is automatically detected as text/markdown via _detect_mime().

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
            # upload_document will auto-detect text/markdown from .md suffix
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


# ──── Bootstrap Utilities ─────────────────────────────────────────


def _upload_file_list(
    client: FileSearchClient,
    store_name: str,
    file_list: List[str],
    project_root: Path,
    label: str,
) -> Dict[str, Any]:
    """Upload a list of files to a store, tracking success/skip counts.

    Args:
        client: FileSearchClient instance.
        store_name: Target store resource name.
        file_list: Relative file paths from project root.
        project_root: Absolute project root path.
        label: Label for logging (e.g. "architecture", "code").

    Returns:
        Dict with 'store', 'uploaded', 'skipped', 'failed', 'total'.

    CONNECTS: FileSearchClient
    CALLED BY: bootstrap_project_stores(), bootstrap_code_store()
    """
    uploaded = 0
    skipped = 0
    failed = 0
    for doc in file_list:
        path = project_root / doc
        if path.exists():
            try:
                result = client.upload_document(store_name, str(path))
                if result is not None:
                    # upload_document returns doc_name or "" — both mean the
                    # upload call succeeded (server may not return a doc name)
                    uploaded += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    "[FileSearch] Upload failed for %s (operation=bootstrap_%s): %s",
                    doc, label, exc,
                )
        else:
            skipped += 1
            logger.debug("[FileSearch] Skipped (not found): %s", doc)

    logger.info(
        "[FileSearch] Bootstrap %s complete (operation=bootstrap_%s): "
        "store=%s, uploaded=%d, skipped=%d, failed=%d, total=%d",
        label, label, store_name, uploaded, skipped, failed, len(file_list),
    )
    return {
        "store": store_name,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "total": len(file_list),
    }


# v1.57.1 [2026-03-26] — Re-upload with MIME fix, added INTERCEPTORS/OPERATIONS/GAME_SYSTEMS
def bootstrap_project_stores() -> Dict[str, Any]:
    """Upload core project documentation to File Search stores.

    Creates (or reuses) a 'cosysim-architecture' store and uploads the key
    documentation files that define CosySim's architecture, configuration,
    and MCP framework. MIME types are now auto-detected to prevent upload
    failures on .md files.

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
        "docs/INTERCEPTORS.md",
        "docs/OPERATIONS.md",
        "docs/GAME_SYSTEMS.md",
        "docs/CHARACTER_SYSTEM.md",
        "docs/INTEGRATIONS_SDK.md",
    ]

    return _upload_file_list(client, arch_store, arch_docs, project_root, "architecture")


# v1.57.1 [2026-03-26] — New: upload engine source files for code-grounded queries
def bootstrap_code_store() -> Dict[str, Any]:
    """Upload key engine source files to a code File Search store.

    Creates (or reuses) a 'cosysim-codebase' store and uploads the core
    engine Python modules. This enables grounded queries against actual
    source code (e.g. "How does _try_qa_cache work in query_router.py?").

    Returns:
        Dict with 'store' (resource name), 'uploaded' (count), 'total' (count).

    CONNECTS: FileSearchClient, engine source files on disk
    CALLED BY: Manual invocation, scheduler bootstrap task
    """
    client = get_file_search_client()
    project_root = Path(__file__).resolve().parents[2]

    # Code store — engine source files
    code_store = client.get_or_create_store("cosysim-codebase")
    code_files = [
        "engine/nexus/client.py",
        "engine/nexus/query_router.py",
        "engine/nexus/knowledge_pipeline.py",
        "engine/nexus/embedding_service.py",
        "engine/nexus/governance_rules.py",
        "engine/agents/agent_loop.py",
        "engine/agents/virtual_agent_manager.py",
        "engine/mcp/comms_framework.py",
        "engine/lmstudio/chat.py",
        "engine/lmstudio/router.py",
        "engine/skills/skill.py",
        "engine/skills/registry.py",
        "engine/config.py",
        "engine/integrations/file_search_client.py",
        "engine/integrations/aistudio_client.py",
    ]

    return _upload_file_list(client, code_store, code_files, project_root, "code")


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
