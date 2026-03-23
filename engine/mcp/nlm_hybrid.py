"""NLM Hybrid Router — unified interface routing between batchexecute proxy and Node MCP bridge.

Intelligently routes NLM operations to the fastest/most reliable backend:
- Node MCP bridge  → chat/Q&A, audio, video, data tables (browser-based, auth-stable)
- Batchexecute proxy → source add, notebook create/rename (fast HTTP RPCs)

Usage:
    from engine.mcp.nlm_hybrid import get_nlm_hybrid
    hybrid = get_nlm_hybrid()
    answer = hybrid.ask("311f2b2e-...", "What is the MCP framework?")
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Routing Constants ────────────────────────────────────────────────────────

# Operations that go through the Node MCP bridge (browser-based, auth-stable)
_NODE_OPS = frozenset({
    "ask", "ask_batch", "audio", "video", "data_tables",
    "chat_history", "quota", "health", "setup_auth",
})

# Operations that go through the batchexecute proxy (fast HTTP RPCs)
_PROXY_OPS = frozenset({
    "add_text_source", "add_url_source", "rename_notebook",
    "list_sources_fast", "delete_source",
})

from engine.port_registry import get_service_url as _get_svc_url

_PROXY_BASE = _get_svc_url("nlm_proxy")


class NLMHybrid:
    """Unified NLM interface routing to Node bridge or batchexecute proxy.

    Strategy:
        - Chat / Q&A → always Node bridge (batchexecute chat RPC is broken)
        - Audio / Video / Data tables → Node bridge (only available there)
        - Source add / rename → batchexecute proxy (fast, works reliably)
        - Fallback: if primary backend fails, try the other
    """

    def __init__(self) -> None:
        self._node: Optional[Any] = None  # NLMNodeBridge, lazy import
        self._lock = threading.Lock()

    def _get_node(self) -> Any:
        """Lazy-import and return the Node bridge singleton."""
        if self._node is None:
            with self._lock:
                if self._node is None:
                    from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                    self._node = get_nlm_node_bridge()
        return self._node

    def _proxy_post(self, path: str, body: Dict[str, Any],
                    timeout: float = 30.0) -> Dict[str, Any]:
        """POST to the batchexecute proxy."""
        import json
        import urllib.error
        import urllib.request

        url = f"{_PROXY_BASE}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            logger.error("Proxy HTTP %d for %s: %s", exc.code, path, body_text[:300])
            return {"error": f"HTTP {exc.code}", "detail": body_text}
        except Exception as exc:
            logger.error("Proxy call failed %s: %s", path, exc)
            return {"error": str(exc)}

    # ──── Q&A / Chat ──────────────────────────────────────────────────────────

    def ask(self, notebook_id: str, question: str,
            reset_history: bool = False,
            session_id: Optional[str] = None) -> Dict[str, Any]:
        """Ask a question against a notebook.

        Routes to Node bridge (browser-based, always reliable).

        Args:
            notebook_id: NLM notebook UUID.
            question: Question text.
            reset_history: If True, start a fresh session (no session_id).
            session_id: Prior session ID for multi-turn continuity.

        Returns:
            Dict with answer, sources, session_id.
        """
        logger.info("NLM ask → Node bridge [%s]: %s", notebook_id[:8], question[:80])
        node = self._get_node()
        if not node.ensure_started():
            return {"error": "NLM Node server unavailable — run setup_auth first"}
        return node.ask_question(
            notebook_id, question,
            session_id=None if reset_history else session_id,
            reset_history=reset_history,
        )

    def ask_batch(self, notebook_id: str, questions: List[str]) -> List[Dict[str, Any]]:
        """Ask multiple questions against a notebook via Node bridge.

        Args:
            notebook_id: NLM notebook UUID.
            questions: List of question strings.

        Returns:
            List of answer dicts.
        """
        logger.info("NLM ask_batch → Node bridge [%s]: %d questions",
                    notebook_id[:8], len(questions))
        node = self._get_node()
        if not node.ensure_started():
            return [{"error": "NLM Node server unavailable"}] * len(questions)
        return node.ask_batch(notebook_id, questions)

    # ──── Source Management ────────────────────────────────────────────────────

    def add_text_source(self, notebook_id: str, title: str,
                         content: str) -> Dict[str, Any]:
        """Add a text source to a notebook via batchexecute proxy (fast path).

        Falls back to Node bridge if proxy unavailable.

        Args:
            notebook_id: NLM notebook UUID.
            title: Source title.
            content: Source text content.

        Returns:
            Dict with source_id, status.
        """
        logger.info("NLM add_text_source → proxy [%s]: %s", notebook_id[:8], title)
        result = self._proxy_post(
            f"/notebooks/{notebook_id}/sources/text",
            {"title": title, "content": content},
        )
        if "error" not in result:
            return result

        # Fallback to Node bridge
        logger.warning("Proxy failed for add_text_source, trying Node bridge")
        node = self._get_node()
        if node.ensure_started():
            return node.add_source(notebook_id, text=content, title=title)
        return result

    def add_url_source(self, notebook_id: str, url: str) -> Dict[str, Any]:
        """Add a URL source to a notebook via batchexecute proxy.

        Args:
            notebook_id: NLM notebook UUID.
            url: URL to add.

        Returns:
            Dict with source_id, status.
        """
        logger.info("NLM add_url_source → proxy [%s]: %s", notebook_id[:8], url)
        result = self._proxy_post(
            f"/notebooks/{notebook_id}/sources/url",
            {"url": url},
        )
        if "error" not in result:
            return result

        logger.warning("Proxy failed for add_url_source, trying Node bridge")
        node = self._get_node()
        if node.ensure_started():
            return node.add_source(notebook_id, url=url)
        return result

    # ──── Audio / Video ───────────────────────────────────────────────────────

    def generate_audio(self, notebook_id: str, style: str = "standard") -> Dict[str, Any]:
        """Generate audio overview via Node bridge.

        Args:
            notebook_id: NLM notebook UUID.
            style: Audio style ("standard", "deep_dive").

        Returns:
            Dict with audio_id, status.
        """
        logger.info("NLM generate_audio → Node bridge [%s]", notebook_id[:8])
        node = self._get_node()
        if not node.ensure_started():
            return {"error": "NLM Node server unavailable"}
        return node.generate_audio_overview(notebook_id, style)

    def generate_video(self, notebook_id: str, style: str = "cinematic") -> Dict[str, Any]:
        """Generate video overview via Node bridge (10 visual styles).

        Args:
            notebook_id: NLM notebook UUID.
            style: Video style ("cinematic", "documentary", "minimalist", etc.).

        Returns:
            Dict with video_id, status.
        """
        logger.info("NLM generate_video → Node bridge [%s]", notebook_id[:8])
        node = self._get_node()
        if not node.ensure_started():
            return {"error": "NLM Node server unavailable"}
        return node.generate_video_overview(notebook_id, style)

    # ──── Data Extraction ──────────────────────────────────────────────────────

    def extract_tables(self, notebook_id: str, query: str = "") -> Dict[str, Any]:
        """Extract structured data tables from notebook sources.

        Args:
            notebook_id: NLM notebook UUID.
            query: Optional filter query.

        Returns:
            Dict with tables list.
        """
        logger.info("NLM extract_tables → Node bridge [%s]", notebook_id[:8])
        node = self._get_node()
        if not node.ensure_started():
            return {"error": "NLM Node server unavailable"}
        return node.extract_data_tables(notebook_id, query)

    # ──── System ───────────────────────────────────────────────────────────────

    def setup_auth(self) -> Dict[str, Any]:
        """Run first-time Google auth setup (opens Chrome visibly).

        Returns:
            Dict with auth status.
        """
        node = self._get_node()
        node.stop()  # Restart with headless=False
        node.start(headless=False, show_browser=True)
        return node.setup_auth(show_browser=True)

    def health(self) -> Dict[str, Any]:
        """Get combined health status from both backends.

        Returns:
            Dict with node_bridge and proxy health info.
        """
        import json
        import urllib.request

        node = self._get_node()
        node_health = node.get_health() if node.is_running else {"status": "not_started"}

        proxy_health: Dict[str, Any] = {"status": "unknown"}
        try:
            with urllib.request.urlopen(f"{_PROXY_BASE}/health", timeout=3) as resp:
                proxy_health = json.loads(resp.read())
        except Exception as e:
            logger.debug("[NLMHybrid] Proxy health check failed (operation=get_health): %s", e)
            proxy_health = {"status": "unreachable"}

        return {
            "node_bridge": node_health,
            "batchexecute_proxy": proxy_health,
            "chrome_profile_exists": node.chrome_profile_exists,
            "node_tools_available": len(node.list_available_tools()),
        }


# ──── Singleton ────────────────────────────────────────────────────────────────

_hybrid_instance: Optional[NLMHybrid] = None
_hybrid_lock = threading.Lock()


def get_nlm_hybrid() -> NLMHybrid:
    """Get the singleton NLMHybrid router instance."""
    global _hybrid_instance
    if _hybrid_instance is None:
        with _hybrid_lock:
            if _hybrid_instance is None:
                _hybrid_instance = NLMHybrid()
    return _hybrid_instance
