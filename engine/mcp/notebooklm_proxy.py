"""
NotebookLM Proxy — bridges CosySim skills to the NLM Live Proxy server.

Architecture
~~~~~~~~~~~~
This proxy talks to ``nlm_live_proxy.py`` (a Flask server at :8800) which uses
browser-attached Google auth/session capture (CDP preferred, HAR import as
recovery) to make direct batchexecute calls to NotebookLM.

Flow::

    CosySim skill  ──▶  NotebookLMProxy  ──HTTP──▶  NLM Live Proxy (:8800)
                                                          │
                                               batchexecute to Google
                                     (using browser-captured session cookies)

Cookie/session setup:
    1. Preferred: capture cookies from a live Chrome NotebookLM tab via CDP.
    2. Recovery: save a fresh HAR with content and import it into the proxy.
    3. Proxy serves direct batchexecute requests until the session expires.

Configuration (``config/default.yaml`` under ``notebooklm`` key)::

    notebooklm:
      enabled: true
      base_url: "http://localhost:8800"

Usage::

    from engine.mcp.notebooklm_proxy import get_notebooklm_proxy
    proxy = get_notebooklm_proxy()
    if proxy.is_running():
        result = proxy.list_notebooks()
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8800"
_REQUEST_TIMEOUT = 30


# ── Proxy Class ────────────────────────────────────────────────────────

class NotebookLMProxy:
    """HTTP client for the NLM Live Proxy server at :8800."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._base_url: str = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Check if the NLM Live Proxy server is reachable.

        The live proxy is started separately (via launcher.py nlm_proxy).
        This method only verifies connectivity.
        """
        return self.is_running()

    def stop(self) -> None:
        """No-op — the live proxy is an independent service."""

    def restart(self) -> bool:
        """No-op — restart via launcher."""
        return self.is_running()

    def is_running(self) -> bool:
        """Return True if the NLM Live Proxy server responds to /health."""
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/health", timeout=3,
            ) as resp:
                return resp.status in (200, 503)  # 503 = no cookies but server up
        except (urllib.error.URLError, OSError):
            return False

    def has_cookies(self) -> bool:
        """Return True if the proxy has valid auth cookies."""
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/health", timeout=3,
            ) as resp:
                data = json.loads(resp.read().decode())
                return bool(data.get("has_cookies", False))
        except Exception:
            return False

    # ── API methods ────────────────────────────────────────────────────

    def ask(self, notebook_id: str, question: str) -> Dict[str, Any]:
        """Ask a question to a NotebookLM notebook (CYK0Xb RPC).

        Args:
            notebook_id: UUID of the target notebook.
            question: The question to ask.

        Returns:
            Dict with: answer_id, answer (markdown text), sources (list).
        """
        return self._post(f"/notebooks/{notebook_id}/ask", {"question": question})

    def batch_ask(
        self,
        notebook_id: str,
        questions: List[str],
        max_batch: int = 5,
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions in a single HTTP request (up to max_batch per call).

        This is the most efficient way to interact with NotebookLM — up to 5
        questions per HTTP request instead of 5 sequential requests.

        Args:
            notebook_id: UUID of the target notebook.
            questions: List of question strings.
            max_batch: Max questions per HTTP request (default 5).

        Returns:
            List of answer dicts in the same order as questions.
        """
        result = self._post(
            f"/notebooks/{notebook_id}/ask_batch",
            {"questions": questions, "max_batch": max_batch},
        )
        if isinstance(result, dict) and "answers" in result:
            return result["answers"]
        return [result] if result else []

    def generate_document(
        self,
        notebook_id: str,
        source_ids: List[str],
        doc_type: int = 2,
    ) -> Dict[str, Any]:
        """Generate a document/report from selected notebook sources.

        Args:
            notebook_id: UUID of the target notebook.
            source_ids: List of source UUIDs to include.
            doc_type: Document type (2=standard, 9=deep research).

        Returns:
            Dict with: title, description, source_ids.
        """
        return self._post(
            f"/notebooks/{notebook_id}/generate",
            {"source_ids": source_ids, "doc_type": doc_type},
        )

    def save_note(
        self,
        notebook_id: str,
        source_ids: List[str],
        note_type: int = 2,
    ) -> Dict[str, Any]:
        """Create/save a note artifact in a notebook.

        Args:
            notebook_id: UUID of the target notebook.
            source_ids: List of source UUIDs to associate.
            note_type: Note type (2=standard, 9=deep research).

        Returns:
            Dict with: note_id, title, note_type.
        """
        return self._post(
            f"/notebooks/{notebook_id}/save_note",
            {"source_ids": source_ids, "note_type": note_type},
        )

    def capture_cookies(self) -> Dict[str, Any]:
        """Automatically capture auth cookies from Chrome via CDP.

        Requires Chrome to be running or will attempt to launch it.

        Returns:
            Dict with: imported_cookies, bl, f_sid, status.
        """
        return self._post("/cookies/capture", {})

    def get_meta(self) -> Dict[str, Any]:
        """Return current build label and session metadata."""
        return self._get("/meta")

    def list_notebooks(self) -> list:
        """List available notebooks from the user's Google account."""
        result = self._get("/notebooks")
        return result.get("notebooks", []) if isinstance(result, dict) else []

    def get_sources(self, notebook_id: str) -> dict:
        """Get sources for a notebook."""
        return self._get(f"/notebooks/{notebook_id}/sources")

    def get_notes(self, notebook_id: str) -> dict:
        """Get notes/blueprints for a notebook."""
        return self._get(f"/notebooks/{notebook_id}/notes")

    def get_summary(self, notebook_id: str) -> dict:
        """Get AI summary/study guide for a notebook."""
        return self._get(f"/notebooks/{notebook_id}/summary")

    def get_conversations(self, notebook_id: str) -> dict:
        """Get Q&A conversation history for a notebook."""
        return self._get(f"/notebooks/{notebook_id}/conversations")

    def get_notebook(self, notebook_id: str) -> dict:
        """Get all data for a notebook in one call."""
        return self._get(f"/notebooks/{notebook_id}")

    def import_cookies_from_har(self, har_path: str) -> dict:
        """Extract and store auth cookies from a HAR file."""
        return self._post("/cookies/import", {"har_path": har_path})

    def add_source(self, notebook_id: str, source_type: str, source_value: str) -> Dict[str, Any]:
        """Not supported via batchexecute reverse-engineered API."""
        return {"error": "not_supported",
                "detail": "add_source currently requires the browser-driven NotebookLM tooling or another live UI automation path"}

    def generate_audio(self, notebook_id: str, customization: str = "") -> Dict[str, Any]:
        """Not supported via batchexecute reverse-engineered API."""
        return {"error": "not_supported",
                "detail": "generate_audio requires the NotebookLM web UI"}

    def search(self, query: str) -> list:
        """List all notebooks (search is not exposed via batchexecute)."""
        return self.list_notebooks()

    # ── v2.1: Configure Chat, Source Reader, Quota ────────────────────

    def chat_message(
        self,
        notebook_id: str,
        question: str,
        role: str = "",
        response_length: int = 4,
    ) -> Dict[str, Any]:
        """Send a chat message with optional role injection (s0tc2d RPC).

        This RPC is asynchronous — the response is queued. Poll
        get_conversations() after ~2-5 seconds to retrieve the answer.

        Args:
            notebook_id: UUID of the notebook to chat with.
            question: The question or prompt to send.
            role: Optional configure-chat role string (e.g. "Act as a PhD researcher").
            response_length: 4=Default, 1=Longer, 2=Shorter.

        Returns:
            Dict with: queued, notebook_id, question.
        """
        return self._post(
            f"/notebooks/{notebook_id}/chat",
            {"question": question, "role": role, "response_length": response_length},
        )

    def chat_messages_batch(
        self,
        notebook_id: str,
        questions: list,
        role: str = "",
        response_length: int = 4,
        max_batch: int = 5,
    ) -> Dict[str, Any]:
        """Send multiple chat messages in parallel (batched s0tc2d).

        Args:
            notebook_id: UUID of the notebook.
            questions: List of question strings.
            role: Optional configure-chat role string.
            response_length: 4=Default, 1=Longer, 2=Shorter.
            max_batch: Maximum concurrent requests per batch.

        Returns:
            Dict with: results, queued_count, count, questions.
        """
        return self._post(
            f"/notebooks/{notebook_id}/chat_batch",
            {
                "questions": questions,
                "role": role,
                "response_length": response_length,
                "max_batch": max_batch,
            },
        )

    def read_source(self, source_id: str) -> Dict[str, Any]:
        """Read the full text content of a source document (tr032e RPC).

        Use this to extract all source content from NLM into Nexus for offline analysis.

        Args:
            source_id: UUID of the source document.

        Returns:
            Dict with: source_id, content, word_count.
        """
        return self._get(f"/sources/{source_id}/content")

    def get_user_quota(self) -> Dict[str, Any]:
        """Fetch user account info and storage quota (ozz5Z RPC).

        Returns:
            Dict with: quota_data, extracted.
        """
        return self._get("/user/quota")

    # ── internal helpers ───────────────────────────────────────────────

    def _get(self, path: str) -> dict:
        return self._request(path, data=None)

    def _post(self, path: str, payload: dict) -> dict:
        return self._request(path, payload)

    def _request(self, path: str, data: Optional[dict] = None) -> dict:
        """Send an HTTP request to the NLM Live Proxy and return parsed JSON."""
        if not self.is_running():
            return {"error": "nlm_proxy_offline",
                    "detail": "NLM Live Proxy is not running. Start with: python launcher.py nlm_proxy"}
        url = f"{self._base_url}{path}"
        try:
            if data is not None:
                body = json.dumps(data).encode()
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json"},
                )
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace") if exc.fp else ""
            logger.error("HTTP %s from %s: %s", exc.code, path, body_text[:200])
            return {"error": f"HTTP {exc.code}", "detail": body_text[:500]}
        except urllib.error.URLError as exc:
            logger.error("Connection error for %s: %s", path, exc.reason)
            return {"error": "connection_error", "detail": str(exc.reason)}
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Request to %s failed: %s", path, exc)
            return {"error": "request_failed", "detail": str(exc)}


# ── Singleton ──────────────────────────────────────────────────────────

_proxy: Optional[NotebookLMProxy] = None
_proxy_lock = threading.Lock()


def get_notebooklm_proxy() -> NotebookLMProxy:
    """Return the global NotebookLMProxy instance (created on first call)."""
    global _proxy
    if _proxy is None:
        with _proxy_lock:
            if _proxy is None:
                cfg = get_config().get("notebooklm", default={})
                _proxy = NotebookLMProxy(cfg if isinstance(cfg, dict) else {})
    return _proxy
