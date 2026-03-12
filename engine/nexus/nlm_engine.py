"""NLM Engine — Unified NotebookLM client for CosySim.

Wraps the CosySim NLM Live Proxy (port 8800) providing a single Python
interface to all NLM operations via the batchexecute API.

Usage:
    from engine.nexus.nlm_engine import get_nlm_engine
    engine = get_nlm_engine()
    answer = engine.ask("notebook-id", "How does X work?")
    answers = engine.ask_batch("notebook-id", ["Q1?", "Q2?", "Q3?"])
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from engine.config import get_config
from engine.mcp.nlm_live_proxy import NLMClient, get_nlm_client  # noqa: F401  re-exported

logger = logging.getLogger(__name__)


# ──── Data Models ────

@dataclass
class NLMStats:
    """Tracks NLM usage metrics for savings calculation."""

    asks: int = 0
    batch_asks: int = 0
    cache_hits: int = 0
    creates: int = 0
    sources_added: int = 0
    docs_generated: int = 0
    errors: int = 0
    total_questions: int = 0
    _start_time: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize stats to dict."""
        uptime = time.monotonic() - self._start_time
        return {
            "asks": self.asks,
            "batch_asks": self.batch_asks,
            "total_questions": self.total_questions,
            "cache_hits": self.cache_hits,
            "creates": self.creates,
            "sources_added": self.sources_added,
            "docs_generated": self.docs_generated,
            "errors": self.errors,
            "uptime_seconds": round(uptime, 1),
        }


# ──── NLM Engine ────

class NLMEngine:
    """Unified NotebookLM client backed by the CosySim Live Proxy.

    All requests route through the nlm_live_proxy at localhost:8800
    which handles batchexecute RPC calls directly with stored auth cookies.

    Usage:
        engine = NLMEngine()
        engine.ask("nb-id", "What is X?")
        engine.ask_batch("nb-id", ["Q1?", "Q2?"])
        engine.create_notebook("My Research", sources=["https://example.com"])
    """

    def __init__(self) -> None:
        cfg = get_config()
        self._proxy_url: str = cfg.get(
            "notebooklm.base_url", "http://localhost:8800"
        )
        self._timeout: int = cfg.get("notebooklm.timeout", 120)
        self._cookies: Dict[str, str] = {}
        self._stats = NLMStats()
        self._lock = threading.Lock()

    # ──── Status ────

    def is_available(self) -> bool:
        """Check if the NLM proxy backend is reachable."""
        return self._check_backend(self._proxy_url)

    def status(self) -> Dict[str, Any]:
        """Return status of the proxy backend."""
        proxy_ok = self._check_backend(self._proxy_url)
        return {
            "available": proxy_ok,
            "proxy": {"url": self._proxy_url, "healthy": proxy_ok},
            "has_cookies": bool(self._cookies),
            "stats": self._stats.to_dict(),
        }

    def stats(self) -> Dict[str, Any]:
        """Return usage statistics."""
        return self._stats.to_dict()

    # ──── Cookie Management (for direct batchexecute) ────

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """Set auth cookies extracted from HAR for direct API access.

        Args:
            cookies: Dict of cookie_name -> cookie_value.
        """
        with self._lock:
            self._cookies = dict(cookies)
        logger.info("Set %d auth cookies for direct NLM access", len(cookies))

    def get_cookies(self) -> Dict[str, str]:
        """Return currently set auth cookies."""
        return dict(self._cookies)

    # ──── Notebook Management ────

    def create_notebook(self, name: str, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a new notebook in NotebookLM.

        Args:
            name: Notebook name.
            sources: Optional list of source URLs to add.

        Returns:
            Dict with notebook info or error.
        """
        self._stats.creates += 1
        payload: Dict[str, Any] = {"name": name}
        if sources:
            payload["sources"] = sources
        return self._post_any("/notebooks/create", payload)

    def delete_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Delete a notebook.

        Args:
            notebook_id: Notebook UUID.

        Returns:
            Dict with result or error.
        """
        return self._delete_any(f"/notebooks/{urllib.parse.quote(notebook_id)}")

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all available notebooks.

        Returns:
            List of notebook dicts.
        """
        # Try proxy first
        result = self._get_any("/notebooks")
        if isinstance(result, dict):
            return result.get("notebooks", result.get("data", []))
        return result if isinstance(result, list) else []

    def get_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Get details of a specific notebook.

        Args:
            notebook_id: Notebook UUID.

        Returns:
            Dict with notebook details.
        """
        return self._get_any(f"/notebooks/{urllib.parse.quote(notebook_id)}")

    # ──── Source Management ────

    def add_source(
        self,
        notebook_id: str,
        source_type: str,
        source_value: str,
    ) -> Dict[str, Any]:
        """Add a source to a notebook.

        Args:
            notebook_id: Target notebook UUID.
            source_type: Type — "url", "text", "pdf", "youtube".
            source_value: The source content or URL.

        Returns:
            Dict with result or error.
        """
        self._stats.sources_added += 1
        return self._post_any("/content/sources", {
            "notebook_id": notebook_id,
            "source_type": source_type,
            "source_value": source_value,
        })

    def add_sources_batch(
        self,
        notebook_id: str,
        sources: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Add multiple sources to a notebook.

        Args:
            notebook_id: Target notebook UUID.
            sources: List of dicts with "type" and "value" keys.

        Returns:
            List of results (one per source).
        """
        results = []
        for src in sources:
            result = self.add_source(
                notebook_id,
                src.get("type", "text"),
                src.get("value", ""),
            )
            results.append(result)
        return results

    def remove_source(self, source_id: str, notebook_id: str = "") -> Dict[str, Any]:
        """Remove a source from a notebook.

        Args:
            source_id: Source UUID to remove.
            notebook_id: Optional notebook UUID.

        Returns:
            Dict with result or error.
        """
        params: Dict[str, str] = {}
        if notebook_id:
            params["notebook_id"] = notebook_id
        return self._delete_any(
            f"/content/sources/{urllib.parse.quote(source_id)}", params=params
        )

    # ──── Codebase Notebooks ────

    def create_from_files(
        self,
        file_paths: List[str],
        name: str,
        max_chars_per_source: int = 50000,
        category: str = "knowledge",
    ) -> Dict[str, Any]:
        """Create a notebook with source code files as text sources.

        Args:
            file_paths: List of file paths to add as sources.
            name: Notebook name.
            max_chars_per_source: Max characters per source (NLM limit).
            category: Factory category for notebook lifecycle management.

        Returns:
            Dict with notebook info and source add results.
        """
        # Use factory for creation/dedup
        try:
            from engine.nexus.nlm_notebook_factory import get_notebook_factory

            factory = get_notebook_factory()
            notebook_id = factory.get_or_create(name, category=category)
        except Exception:
            notebook_id = None

        if not notebook_id:
            # Fallback to direct creation
            result = self.create_notebook(name)
            notebook_id = result.get("notebook_id") or result.get("id", "")
        if not notebook_id:
            return {"error": "Failed to create notebook", "detail": {}}

        source_results = []
        for fpath in file_paths:
            try:
                path = Path(fpath)
                if not path.exists():
                    source_results.append({"file": fpath, "error": "not found"})
                    continue

                content = path.read_text(encoding="utf-8", errors="replace")
                if len(content) > max_chars_per_source:
                    content = content[:max_chars_per_source] + "\n... (truncated)"

                # Format as code block with filename
                source_text = f"# File: {path.name}\n\n```{path.suffix.lstrip('.')}\n{content}\n```"

                add_result = self.add_source(notebook_id, "text", source_text)
                source_results.append({"file": fpath, "result": add_result})
            except Exception as e:
                source_results.append({"file": fpath, "error": str(e)})

        return {
            "notebook_id": notebook_id,
            "name": name,
            "sources_added": len([r for r in source_results if "error" not in r]),
            "source_results": source_results,
        }

    # ──── Q&A — The Core Value ────

    def ask(self, notebook_id: str, question: str) -> Dict[str, Any]:
        """Ask a question to a NotebookLM notebook.

        Args:
            notebook_id: Target notebook UUID.
            question: The question to ask.

        Returns:
            Dict with answer, sources, and metadata.
        """
        self._stats.asks += 1
        self._stats.total_questions += 1

        # Try proxy endpoint
        result = self._post_any("/ask", {
            "notebook_id": notebook_id,
            "question": question,
        })
        if "error" in result:
            self._stats.errors += 1
        return result

    def ask_batch(
        self,
        notebook_id: str,
        questions: List[str],
        delay: float = 1.0,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Ask multiple questions to a notebook sequentially.

        Each answer is collected and returned. Use `on_progress` callback
        to track progress.

        Args:
            notebook_id: Target notebook UUID.
            questions: List of questions to ask.
            delay: Seconds between questions (avoid rate limiting).
            on_progress: Optional callback(current, total, question).

        Returns:
            List of answer dicts (one per question).
        """
        self._stats.batch_asks += 1
        results = []
        total = len(questions)

        for i, q in enumerate(questions):
            if on_progress:
                on_progress(i + 1, total, q)

            answer = self.ask(notebook_id, q)
            results.append({
                "question": q,
                "answer": answer,
                "index": i,
            })

            if i < total - 1 and delay > 0:
                time.sleep(delay)

        return results

    # ──── Conversation (Teacher Mode) ────

    def converse(self, notebook_id: str, message: str, session_id: str = "") -> Dict[str, Any]:
        """Have a conversation with NLM — teacher mode.

        Args:
            notebook_id: Target notebook UUID.
            message: Message to send.
            session_id: Optional session ID for continuity.

        Returns:
            Dict with response and session info.
        """
        payload: Dict[str, Any] = {
            "notebook_id": notebook_id,
            "question": message,
        }
        if session_id:
            payload["session_id"] = session_id
        return self._post_any("/ask", payload)

    # ──── Content Generation ────

    def generate(
        self,
        notebook_id: str,
        doc_type: str = "study_guide",
        instructions: str = "",
        language: str = "",
    ) -> Dict[str, Any]:
        """Generate a document from a notebook.

        Args:
            notebook_id: Source notebook UUID.
            doc_type: Document type — study_guide, faq, briefing, deep_dive, timeline.
            instructions: Custom instructions to guide generation.
            language: Output language.

        Returns:
            Dict with generated content or job status.
        """
        self._stats.docs_generated += 1
        payload: Dict[str, Any] = {
            "notebook_id": notebook_id,
            "type": doc_type,
        }
        if instructions:
            payload["custom_instructions"] = instructions
        if language:
            payload["language"] = language
        return self._post_any("/content/generate", payload)

    def generate_audio(
        self,
        notebook_id: str,
        customization: str = "",
    ) -> Dict[str, Any]:
        """Generate an audio overview (podcast) for a notebook.

        Args:
            notebook_id: Source notebook UUID.
            customization: Free-text to guide audio focus/style.
                Examples: "Focus on security implications",
                          "Make it beginner-friendly",
                          "Cover deployment architecture in depth"

        Returns:
            Dict with audio generation status.
        """
        self._stats.docs_generated += 1
        payload: Dict[str, Any] = {"notebook_id": notebook_id}
        if customization:
            payload["customization"] = customization
        result = self._try_post(self._proxy_url, "/generate_audio", payload)
        if result is not None:
            return result
        return {"error": "NLM proxy unavailable for audio generation"}

    def download_content(
        self,
        notebook_id: str,
        content_type: str,
    ) -> Dict[str, Any]:
        """Download previously generated content.

        Args:
            notebook_id: Source notebook UUID.
            content_type: Content type to download.

        Returns:
            Dict with content data.
        """
        params = {"notebook_id": notebook_id, "type": content_type}
        return self._get_any("/content/download", params=params)

    # ──── Notes ────

    def create_note(
        self,
        notebook_id: str,
        title: str,
        content: str,
    ) -> Dict[str, Any]:
        """Create a note in a notebook.

        Args:
            notebook_id: Target notebook UUID.
            title: Note title.
            content: Note content text.

        Returns:
            Dict with result.
        """
        return self._post_any("/content/notes", {
            "notebook_id": notebook_id,
            "title": title,
            "content": content,
        })

    # ──── Internal: Dual-Backend HTTP ────

    def _check_backend(self, base_url: str) -> bool:
        """Check if a backend is reachable."""
        try:
            req = urllib.request.Request(f"{base_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _try_post(self, base_url: str, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try POST to a specific backend. Returns None if unreachable."""
        url = f"{base_url}{path}"
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _try_get(self, base_url: str, path: str, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Try GET to a specific backend. Returns None if unreachable."""
        url = f"{base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _try_delete(self, base_url: str, path: str, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Try DELETE to a specific backend. Returns None if unreachable."""
        url = f"{base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, method="DELETE")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _post_any(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the proxy backend."""
        result = self._try_post(self._proxy_url, path, payload)
        if result is not None:
            return result
        self._stats.errors += 1
        return {"error": "NLM proxy unavailable"}

    def _get_any(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """GET from the proxy backend."""
        result = self._try_get(self._proxy_url, path, params)
        if result is not None:
            return result
        return {"error": "NLM proxy unavailable"}

    def _delete_any(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """DELETE on the proxy backend."""
        result = self._try_delete(self._proxy_url, path, params)
        if result is not None:
            return result
        return {"error": "NLM proxy unavailable"}


# ──── Singleton ────

_engine: Optional[NLMEngine] = None
_engine_lock = threading.Lock()


def get_nlm_engine() -> NLMEngine:
    """Return the global NLMEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = NLMEngine()
    return _engine
