"""NLMClient class — high-level wrapper for NLM operations with caching and session management."""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.nlm_auth import (
    _load_cookies,
    _save_cookies,
    extract_cookies_from_har,
    _get_bl,
    refresh_session_tokens,
    _COOKIES_FILE,
    _load_meta,
    _save_meta,
    _DEFAULT_BL,
)
from engine.mcp.nlm_transport import (
    _batchexecute,
    _parse_batchexecute,
    _build_headers,
    _extract_strings,
    _extract_sources,
    _dedup,
)
from engine.mcp.nlm_operations import (
    ask_question,
    rename_notebook,
    add_source_url,
    add_text_source,
    poll_source_status,
    wait_for_sources,
    register_file_sources,
    upload_file_to_nlm,
    create_note,
    save_note,
    get_source_summary,
    get_audio_options,
    sync_notes,
    ask_questions_batch,
    delete_source,
    start_deep_research,
    add_research_source,
    _grpc_ask,
    grpc_ask_batch,
    read_source,
)
from engine.mcp.nlm_archive import (
    download_all_sources,
    export_notebook,
    export_all_notebooks,
    get_user_quota,
    get_user_plan,
    generate_document,
    save_note_report,
)
from engine.mcp.nlm_rpc_constants import (
    RPC_LIST_NOTEBOOKS,
    RPC_NOTEBOOK_CONTENT,
    RPC_LIST_SOURCES,
    RPC_PENDING_SOURCES,
    RPC_GET_ARTIFACTS,
    RPC_SYNC_NOTES,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# NLMClient CLASS
#
# High-level object-oriented API over all module-level batchexecute helpers.
# This is the primary interface for CosySim agents and nlm_engine.py.
#
# Auth (cookies + meta) is managed via the module-level global store
# (data/nlm_cookies.json, data/nlm_meta.json) — the client itself is stateless.
#
# Method groups:
#   Auth:        get_cookies, has_cookies, import_cookies_from_har,
#                capture_cookies_from_chrome
#   Notebooks:   list_notebooks, get_notebook, get_sources, get_chat_history,
#                get_notes
#   Ask/Chat:    ask, ask_batch, grpc_ask, grpc_ask_batch
#                chat / chat_batch (backward-compat aliases → grpc_ask*)
#   Write:       rename, add_source, delete_source, deep_research,
#                deep_research_with_source
#   Generate:    generate_document, save_note
#   Read:        read_source, get_summary, get_user_quota
#   Status:      get_status
# ════════════════════════════════════════════════════════════════════════════

class NLMClient:
    """High-level NotebookLM client wrapping all batchexecute RPCs.

    Provides a clean class-based API over the module-level helper functions.
    Used by nlm_engine.py and any caller that needs direct NLM access.
    Delegates to module-level functions and uses the global cookie/meta store.
    """

    # ── Auth ──────────────────────────────────────────────────────────────

    def get_cookies(self) -> Dict[str, Any]:
        """Load cookies from disk. Returns empty dict if none."""
        return _load_cookies()

    def has_cookies(self) -> bool:
        """Return True if auth cookies are present."""
        return bool(_load_cookies())

    def import_cookies_from_har(self, har_path: str) -> Dict[str, Any]:
        """Extract and save cookies from a HAR file.

        Args:
            har_path: Path to the .har file.

        Returns:
            Dict with imported count, total count, and meta fields.
        """
        new_cookies, new_meta = extract_cookies_from_har(har_path)
        existing = _load_cookies()
        merged = {**existing, **new_cookies}
        _save_cookies(merged)
        existing_meta = _load_meta()
        if new_meta.get("bl"):
            existing_meta["bl"] = new_meta["bl"]
        if new_meta.get("f_sid"):
            existing_meta["f_sid"] = new_meta["f_sid"]
        if new_meta.get("at"):
            existing_meta["at"] = new_meta["at"]
            logger.info("import_cookies_from_har: updated at token from HAR")
        _save_meta(existing_meta)
        return {"imported": len(new_cookies), "total": len(merged), **existing_meta}

    def capture_cookies_from_chrome(self) -> Dict[str, Any]:
        """Auto-capture cookies from Chrome via CDP.

        Returns:
            Dict with captured cookie count and meta.
        """
        from engine.nexus.nlm_har_capture import capture_nlm_cookies
        return capture_nlm_cookies()

    # ── Notebooks ─────────────────────────────────────────────────────────

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks for the authenticated user.

        Returns:
            List of notebook dicts with id and name.
        """
        cookies = _load_cookies()
        if not cookies:
            return []
        _, data = _batchexecute(RPC_LIST_NOTEBOOKS, "[[2]]", cookies)
        if not data or isinstance(data, dict):
            return []
        notebooks = []
        try:
            for nb in (data[0] if isinstance(data, list) and data else []):
                if isinstance(nb, list):
                    texts = _extract_strings(nb, min_len=5)
                    name = texts[0] if texts else "Unknown"
                    nid = None
                    for part in nb:
                        if isinstance(part, str) and re.match(r"[a-f0-9-]{36}", part):
                            nid = part
                            break
                    if nid:
                        notebooks.append({"id": nid, "name": name})
        except (IndexError, TypeError) as exc:
            # v1.49.1 [2026-03-22] — Surface parse errors
            logger.warning("NLMClient.list_notebooks parse error: %s", exc)
        return notebooks

    def get_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Get full notebook data: summary, sources, notes, conversations.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            Dict with summary, sources, notes, conversations, and stats.
        """
        cookies = _load_cookies()
        result: Dict[str, Any] = {"notebook_id": notebook_id}
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
        result["summary"] = "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
        if data and not isinstance(data, dict):
            result["notebook_name"], result["sources"] = _extract_sources(data)
        else:
            result["notebook_name"] = ""
            result["sources"] = []
        _, data = _batchexecute(
            "gArtLc",
            json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""]),
            cookies, notebook_id,
        )
        notes = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["notes"] = [n for n in notes if len(n) > 100]
        _, data = _batchexecute(RPC_SYNC_NOTES, json.dumps([notebook_id, None, None, [2]]), cookies, notebook_id)
        convos = _dedup(_extract_strings(data, 80)) if data and not isinstance(data, dict) else []
        result["conversations"] = [c for c in convos if len(c) > 100]
        result["stats"] = {
            "sources": len(result["sources"]),
            "notes": len(result["notes"]),
            "conversations": len(result["conversations"]),
        }
        return result

    def get_sources(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List all sources in a notebook.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            List of source dicts.
        """
        cookies = _load_cookies()
        _, data = _batchexecute(RPC_LIST_SOURCES, json.dumps([None, 1, None, [2]]), cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        _, sources = _extract_sources(data)
        return sources

    def get_chat_history(self, notebook_id: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """Get conversation/chat history for a notebook (hPTbtc RPC).

        Args:
            notebook_id: The notebook UUID.
            page_size: Number of messages per page.

        Returns:
            List of conversation message dicts.
        """
        cookies = _load_cookies()
        args = json.dumps([[], None, notebook_id, page_size])
        _, data = _batchexecute(RPC_PENDING_SOURCES, args, cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        messages = []
        try:
            for s in _extract_strings(data, min_len=20):
                if len(s) > 50:
                    messages.append({"content": s, "type": "message"})
        except (IndexError, TypeError) as exc:
            logger.warning("NLMClient.get_chat_history parse error for %s: %s", notebook_id, exc)
        return messages

    def get_notes(self, notebook_id: str) -> List[str]:
        """Get all notes/artifacts for a notebook.

        Args:
            notebook_id: The notebook UUID.

        Returns:
            List of note text strings.
        """
        cookies = _load_cookies()
        args = json.dumps([[2], notebook_id, "NOT artifact.status = \"ARTIFACT_STATUS_SUGGESTED\""])
        _, data = _batchexecute(RPC_GET_ARTIFACTS, args, cookies, notebook_id)
        if not data or isinstance(data, dict):
            return []
        notes = _dedup(_extract_strings(data, 80))
        return [n for n in notes if len(n) > 100]

    # ── Ask / Chat ────────────────────────────────────────────────────────

    def ask(self, notebook_id: str, question: str) -> Dict[str, Any]:
        """Ask a single question using CYK0Xb (citation mode, synchronous).

        Args:
            notebook_id: The notebook UUID.
            question: The question to ask.

        Returns:
            Dict with answer_id, answer, and sources.
        """
        return ask_question(notebook_id, question, _load_cookies())

    def ask_batch(
        self, notebook_id: str, questions: List[str], max_batch: int = 5
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions in batches using CYK0Xb.

        Args:
            notebook_id: The notebook UUID.
            questions: List of question strings.
            max_batch: Max questions per HTTP request.

        Returns:
            List of answer dicts in question order.
        """
        return ask_questions_batch(notebook_id, questions, _load_cookies(), max_batch)

    def rename(self, notebook_id: str, new_name: str) -> Dict[str, Any]:
        """Rename a notebook using s0tc2d (RENAME_NOTEBOOK RPC).

        Args:
            notebook_id: The notebook UUID.
            new_name: The new title for the notebook.

        Returns:
            Dict with renamed (bool), notebook_id, and name.
        """
        return rename_notebook(notebook_id, new_name, _load_cookies())

    def add_source(self, notebook_id: str, url: str) -> Dict[str, Any]:
        """Add a URL or YouTube video as a notebook source (izAoDd RPC).

        Args:
            notebook_id: The notebook UUID.
            url: HTTP/HTTPS URL or YouTube URL to add.

        Returns:
            Dict with source_id, url, and status.
        """
        return add_source_url(notebook_id, url, _load_cookies())

    def delete_source(self, source_id: str) -> Dict[str, Any]:
        """Delete a notebook source (tGMBJ RPC).

        Args:
            source_id: UUID of the source to delete.

        Returns:
            Dict with deleted (bool) and source_id.
        """
        return delete_source(source_id, _load_cookies())

    def deep_research(self, notebook_id: str, topic: str) -> Dict[str, Any]:
        """Start a deep research session (QA9ei RPC).

        Args:
            notebook_id: The notebook UUID.
            topic: The research topic or question.

        Returns:
            Dict with session_id, topic, and notebook_id.
        """
        return start_deep_research(notebook_id, topic, _load_cookies())

    def deep_research_with_source(
        self, notebook_id: str, topic: str, title: str, content: str
    ) -> Dict[str, Any]:
        """Start deep research and add the generated document as a source.

        Runs QA9ei (start_deep_research) then LBwxtb (add_research_source).

        Args:
            notebook_id: The notebook UUID.
            topic: The research topic.
            title: Title for the research document.
            content: Full text content of the research document.

        Returns:
            Dict with session_id, source_id, title, and notebook_id.
        """
        cookies = _load_cookies()
        research = start_deep_research(notebook_id, topic, cookies)
        session_id = research.get("session_id") or topic[:36]
        source = add_research_source(notebook_id, session_id, title, content, cookies)
        return {**research, **source}

    def grpc_ask(
        self,
        notebook_id: str,
        question: str,
        source_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat via GenerateFreeFormStreamed (real NLM chat, synchronous).

        Auto-fetches source IDs if not provided. Supports multi-turn conversation
        via thread_id.

        Args:
            notebook_id: The notebook UUID.
            question: The question to ask.
            source_ids: Source UUIDs (auto-fetched if None).
            thread_id: Thread UUID for multi-turn, or None for new conversation.

        Returns:
            Dict with answer, thread_id, message_id, question, sources.
        """
        cookies = _load_cookies()
        if source_ids is None:
            _, data = _batchexecute(
                RPC_LIST_SOURCES,
                json.dumps([None, 1, None, [2]]),
                cookies,
                notebook_id,
            )
            _, srcs = _extract_sources(data) if data and not isinstance(data, dict) else (None, [])
            source_ids = [s["id"] for s in srcs if s.get("id")]
        return _grpc_ask(notebook_id, question, source_ids, cookies, thread_id)

    def grpc_ask_batch(
        self,
        notebook_id: str,
        questions: List[str],
        source_ids: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions via GenerateFreeFormStreamed.

        Args:
            notebook_id: The notebook UUID.
            questions: List of question strings.
            source_ids: Source UUIDs (auto-fetched if None).
            thread_id: Thread UUID for linked conversation (None = independent).

        Returns:
            List of grpc_ask response dicts in question order.
        """
        cookies = _load_cookies()
        if source_ids is None:
            _, data = _batchexecute(
                RPC_LIST_SOURCES,
                json.dumps([None, 1, None, [2]]),
                cookies,
                notebook_id,
            )
            _, srcs = _extract_sources(data) if data and not isinstance(data, dict) else (None, [])
            source_ids = [s["id"] for s in srcs if s.get("id")]
        return grpc_ask_batch(notebook_id, questions, source_ids, cookies, thread_id)

    # Backward-compat aliases — old "chat" and "chat_batch" now delegate to grpc_ask

    def chat(
        self,
        notebook_id: str,
        question: str,
        thread_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Alias for grpc_ask (backward compat). Uses GenerateFreeFormStreamed."""
        return self.grpc_ask(notebook_id, question, source_ids, thread_id)

    def chat_batch(
        self,
        notebook_id: str,
        questions: List[str],
        thread_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Alias for grpc_ask_batch (backward compat). Uses GenerateFreeFormStreamed."""
        return self.grpc_ask_batch(notebook_id, questions, source_ids, thread_id)

    # ── Generate ──────────────────────────────────────────────────────────

    def generate_document(
        self, notebook_id: str, source_ids: List[str], doc_type: int = 2
    ) -> Dict[str, Any]:
        """Generate a document from notebook sources (ciyUvf RPC).

        Args:
            notebook_id: The notebook UUID.
            source_ids: List of source UUIDs to include.
            doc_type: Document type integer (2=standard, 9=deep research).

        Returns:
            Dict with title, description, and source_ids.
        """
        return generate_document(notebook_id, source_ids, _load_cookies(), doc_type)

    def save_note(
        self, notebook_id: str, source_ids: List[str], note_type: int = 2
    ) -> Dict[str, Any]:
        """Save a note artifact to a notebook (R7cb6c RPC).

        Args:
            notebook_id: The notebook UUID.
            source_ids: List of source UUIDs to associate.
            note_type: Note type (2=standard, 9=deep research).

        Returns:
            Dict with note_id, title, and note_type.
        """
        return save_note_report(notebook_id, source_ids, _load_cookies(), note_type)

    def read_source(self, source_id: str) -> Dict[str, Any]:
        """Read the full text content of a source (tr032e RPC).

        Args:
            source_id: UUID of the source to read.

        Returns:
            Dict with source_id, content, and word_count.
        """
        return read_source(source_id, _load_cookies())

    def get_summary(self, notebook_id: str) -> str:
        """Get the AI-generated overview/summary of a notebook (VfAZjd RPC).

        Args:
            notebook_id: The notebook UUID.

        Returns:
            Summary text string.
        """
        cookies = _load_cookies()
        _, data = _batchexecute(RPC_NOTEBOOK_CONTENT, json.dumps([notebook_id, [2]]), cookies, notebook_id)
        return "\n\n".join(_extract_strings(data, 50)) if data and not isinstance(data, dict) else ""

    def get_user_quota(self) -> Dict[str, Any]:
        """Fetch user quota and account info (ozz5Z RPC).

        Returns:
            Dict with quota_data and extracted text.
        """
        return get_user_quota(_load_cookies())

    def get_user_plan(self) -> Dict[str, Any]:
        """Fetch user plan/tier and daily query allowance (ZwVcOc RPC).

        Returns:
            Dict with plan_name, daily_limit, queries_remaining.
        """
        return get_user_plan(_load_cookies())

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current auth and meta status.

        Returns:
            Dict with has_cookies, cookie_count, bl, bl_age_days, and bl_stale.
        """
        cookies = _load_cookies()
        meta = _load_meta()
        bl_age: Optional[int] = None
        try:
            updated_at = meta.get("bl_updated_at")
            if updated_at:
                bl_age = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(updated_at)
                ).days
        except Exception as exc:
            logger.debug("NLMClient.get_status BL age check failed: %s", exc)
        return {
            "has_cookies": bool(cookies),
            "cookie_count": len(cookies),
            "bl": meta.get("bl", _DEFAULT_BL),
            "bl_age_days": bl_age,
            "bl_stale": bl_age is not None and bl_age >= 8,
            "rpc_catalog_version": "v3.1",
            "known_rpcs": 25,
        }


# ── NLMClient singleton ───────────────────────────────────────────────────

_nlm_client: Optional["NLMClient"] = None


def get_nlm_client() -> NLMClient:
    """Return the shared NLMClient singleton.

    Returns:
        The global NLMClient instance.
    """
    global _nlm_client
    if _nlm_client is None:
        _nlm_client = NLMClient()
    return _nlm_client
