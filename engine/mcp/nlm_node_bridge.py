"""NLM Node Bridge — Python interface to @pan-sec/notebooklm-mcp Node.js MCP server.

Starts the Node MCP process and communicates via JSON-RPC 2.0 over stdin/stdout.
Provides a clean Python API for all 47 NotebookLM tools.

Usage:
    from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
    bridge = get_nlm_node_bridge()
    answer = bridge.ask_question("https://notebooklm.google.com/notebook/...", "What is X?")
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ──── Constants ────────────────────────────────────────────────────────────────

_NODE_SERVER_PATH = Path(r"C:\Files\MCP\notebooklm-mcp\dist\index.js")
_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Knack\AppData\Local")) / "notebooklm-mcp"
_CHROME_PROFILE = _DATA_DIR / "chrome_profile"
_INIT_TIMEOUT = 15.0   # seconds to wait for server init
_CALL_TIMEOUT = 120.0  # seconds to wait for tool response (browser ops are slow)

NLM_BASE_URL = "https://notebooklm.google.com/notebook"


def notebook_url(notebook_id: str) -> str:
    """Convert a UUID notebook ID to its full NotebookLM URL."""
    return f"{NLM_BASE_URL}/{notebook_id}"


# ──── Bridge Class ─────────────────────────────────────────────────────────────

class NLMNodeBridge:
    """Python bridge to the @pan-sec/notebooklm-mcp Node.js MCP server.

    Starts the Node process on first use and reuses it for subsequent calls.
    Thread-safe: multiple Python threads can call tools concurrently.

    The Node server uses Patchright (undetectable Playwright) with a persistent
    Chrome profile at C:\\Users\\Knack\\AppData\\Local\\notebooklm-mcp\\chrome_profile.
    This profile must be authenticated first via setup_auth().
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._request_id: int = 0
        self._pending: Dict[int, threading.Event] = {}
        self._results: Dict[int, Any] = {}
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._initialized = False
        self._available_tools: List[str] = []

    # ──── Process Lifecycle ────────────────────────────────────────────────────

    def start(self, headless: bool = True, show_browser: bool = False) -> bool:
        """Start the Node MCP server process.

        Args:
            headless: Run Chrome in headless mode (True for normal ops).
            show_browser: Show Chrome window (True for first-time auth setup).

        Returns:
            True if server started and initialized successfully.
        """
        if self._initialized and self._process and self._process.poll() is None:
            return True

        effective_headless = headless and not show_browser
        env = {
            **os.environ,
            "NOTEBOOKLM_HEADLESS": "false" if not effective_headless else "true",
            "NOTEBOOKLM_STEALTH": "true",
            "NOTEBOOKLM_MAX_SESSIONS": "5",
            "NOTEBOOKLM_NO_GEMINI": "true",
        }

        logger.info("Starting NLM Node MCP server (headless=%s)...", effective_headless)
        try:
            self._process = subprocess.Popen(
                ["node", str(_NODE_SERVER_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except FileNotFoundError:
            logger.error("node not found — ensure Node.js is in PATH")
            return False

        # Start reader thread
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # Start stderr logger
        threading.Thread(target=self._stderr_logger, daemon=True).start()

        # Send initialize handshake
        init_result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "cosysim", "version": "0.60.5"},
        })
        if not init_result or "error" in init_result:
            logger.error("NLM Node server initialize failed: %s", init_result)
            return False

        # Send initialized notification
        self._send_notification("notifications/initialized", {})

        # Cache available tools
        tools_result = self._send_request("tools/list", {})
        if tools_result and "tools" in tools_result:
            self._available_tools = [t["name"] for t in tools_result["tools"]]
            logger.info("NLM Node server ready — %d tools available", len(self._available_tools))

        self._initialized = True
        return True

    def stop(self) -> None:
        """Stop the Node MCP server process."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._initialized = False
        self._process = None

    @property
    def is_running(self) -> bool:
        """True if the Node process is alive and initialized."""
        return self._initialized and self._process is not None and self._process.poll() is None

    @property
    def chrome_profile_exists(self) -> bool:
        """True if the Chrome profile directory exists (auth has been set up)."""
        return _CHROME_PROFILE.exists() and any(_CHROME_PROFILE.iterdir())

    def ensure_started(self) -> bool:
        """Start the server if not running. Returns True if ready."""
        if not self.is_running:
            return self.start()
        return True

    # ──── JSON-RPC Communication ───────────────────────────────────────────────

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_raw(self, message: Dict[str, Any]) -> None:
        """Write a JSON-RPC message to the Node process stdin."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Node process not running")
        line = json.dumps(message) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        self._send_raw({"jsonrpc": "2.0", "method": method, "params": params})

    def _send_request(self, method: str, params: Dict[str, Any], timeout: float = _INIT_TIMEOUT) -> Optional[Dict]:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self._next_id()
        event = threading.Event()
        with self._lock:
            self._pending[req_id] = event

        self._send_raw({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        if not event.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(req_id, None)
            logger.warning("NLM Node server request %d timed out (method=%s)", req_id, method)
            return None

        with self._lock:
            return self._results.pop(req_id, None)

    def _reader_loop(self) -> None:
        """Background thread: read JSON-RPC responses from Node stdout."""
        if not self._process or not self._process.stdout:
            return
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("NLM Node non-JSON: %s", line[:200])
                continue

            req_id = msg.get("id")
            if req_id is not None:
                result = msg.get("result") or msg.get("error") or {}
                with self._lock:
                    self._results[req_id] = result
                    event = self._pending.pop(req_id, None)
                if event:
                    event.set()
            elif msg.get("method"):
                # Server-sent notification — log at debug
                logger.debug("NLM Node notification: %s", msg.get("method"))

    def _stderr_logger(self) -> None:
        """Background thread: log Node stderr output."""
        if not self._process or not self._process.stderr:
            return
        for line in self._process.stderr:
            line = line.strip()
            if line:
                if "error" in line.lower():
                    logger.error("[nlm-node] %s", line)
                else:
                    logger.debug("[nlm-node] %s", line)

    # ──── Tool Invocation ──────────────────────────────────────────────────────

    def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                  timeout: float = _CALL_TIMEOUT) -> Dict[str, Any]:
        """Call any tool on the Node MCP server.

        Args:
            tool_name: MCP tool name (e.g. "ask_question", "create_notebook").
            arguments: Tool arguments dict.
            timeout: Max seconds to wait for response.

        Returns:
            Dict with tool result, or {"error": "..."} on failure.
        """
        if not self.ensure_started():
            return {"error": "Node MCP server failed to start"}

        result = self._send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout,
        )
        if result is None:
            return {"error": f"timeout calling {tool_name}"}

        # MCP response: {"content": [{"type": "text", "text": "..."}]}
        if "content" in result:
            contents = result["content"]
            if contents:
                text = contents[0].get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    return {"result": text}
            return {"result": ""}

        # Error response
        if "code" in result or "message" in result:
            return {"error": result.get("message", str(result))}

        return result

    # ──── Auth ─────────────────────────────────────────────────────────────────

    def setup_auth(self, show_browser: bool = True) -> Dict[str, Any]:
        """Run first-time Google auth setup.

        Opens Chrome visibly (show_browser=True) for interactive login.
        After login, the Chrome profile is saved and subsequent calls
        work in headless mode.

        Args:
            show_browser: Show Chrome window (default True for auth).

        Returns:
            Dict with auth status.
        """
        if not self.is_running:
            self.start(headless=False, show_browser=show_browser)
        return self.call_tool("setup_auth", {"show_browser": show_browser}, timeout=300.0)

    def get_health(self) -> Dict[str, Any]:
        """Get server health and auth state."""
        if not self.ensure_started():
            return {"healthy": False, "error": "Node server not running"}
        return self.call_tool("get_health", {})

    # ──── Notebook Management ──────────────────────────────────────────────────

    def sync_library(self) -> Dict[str, Any]:
        """Sync local notebook library with actual NotebookLM notebooks.

        Returns:
            Dict with synced notebook list.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("sync_library", {}, timeout=60.0)

    def list_notebooks(self) -> List[Dict[str, Any]]:
        """List all notebooks in the local library.

        Returns:
            List of notebook dicts with id, title, url, etc.
        """
        if not self.ensure_started():
            return []
        result = self.call_tool("list_notebooks", {})
        if isinstance(result, list):
            return result
        return result.get("notebooks", [])

    def add_notebook(self, url: str, name: str = "", description: str = "",
                     topics: Optional[List[str]] = None) -> Dict[str, Any]:
        """Add an existing notebook to the local library by URL.

        Args:
            url: Full NotebookLM URL or notebook UUID.
            name: Display name for the notebook.
            description: What knowledge is in this notebook.
            topics: Topics covered in this notebook.

        Returns:
            Dict with notebook metadata.
        """
        if not url.startswith("http"):
            url = notebook_url(url)
        if not self.ensure_started():
            return {"error": "Node server not running"}
        args: Dict[str, Any] = {
            "url": url,
            "name": name or url.rsplit("/", 1)[-1][:40],
            "description": description or "CosySim Sprint 8 notebook",
            "topics": topics or ["cosysim"],
        }
        return self.call_tool("add_notebook", args)

    def select_notebook(self, notebook_id: str) -> Dict[str, Any]:
        """Set active notebook for queries.

        Args:
            notebook_id: Library notebook ID (local ID, not NLM UUID).

        Returns:
            Dict with selected notebook info.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("select_notebook", {"id": notebook_id})

    def create_notebook(self, title: str, sources: Optional[List[Dict]] = None,
                        description: str = "") -> Dict[str, Any]:
        """Programmatically create a new notebook.

        Args:
            title: Notebook name.
            sources: Optional list of source dicts: [{"type": "url", "value": "..."}, {"type": "text", "value": "..."}].
            description: Optional notebook description.

        Returns:
            Dict with notebook_id, url, name.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        args: Dict[str, Any] = {
            "name": title,
            "sources": sources or [],
        }
        if description:
            args["description"] = description
        return self.call_tool("create_notebook", args, timeout=120.0)

    # ──── Q&A / Chat ──────────────────────────────────────────────────────────

    def ask_question(self, notebook_id_or_url: str, question: str,
                     session_id: Optional[str] = None,
                     reset_history: bool = False) -> Dict[str, Any]:
        """Ask a question grounded in a notebook's sources.

        Uses real browser automation: navigates to the notebook, types the
        question, waits for NLM's response. Always works (no RPC fragility).

        Session continuity: pass `session_id` from a prior response to
        maintain conversation context. Set `reset_history=True` to start fresh.

        Args:
            notebook_id_or_url: NLM UUID or full notebook URL.
            question: Question text.
            session_id: Prior session ID for multi-turn conversations.
            reset_history: If True, omit session_id to start a fresh session.

        Returns:
            Dict with answer, sources, session_id.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}

        url = notebook_id_or_url if notebook_id_or_url.startswith("http") else notebook_url(notebook_id_or_url)

        # Ensure notebook is in library
        self.add_notebook(url)

        args: Dict[str, Any] = {
            "notebook_url": url,
            "question": question,
        }
        if session_id and not reset_history:
            args["session_id"] = session_id

        return self.call_tool("ask_question", args, timeout=_CALL_TIMEOUT)

    def ask_batch(self, notebook_id_or_url: str, questions: List[str],
                  keep_session: bool = True) -> List[Dict[str, Any]]:
        """Ask multiple questions sequentially against a notebook.

        Uses session continuity (same session_id) so later questions benefit
        from earlier answers in the same conversation thread.

        Args:
            notebook_id_or_url: NLM UUID or full URL.
            questions: List of question strings.
            keep_session: If True, reuse session_id across all questions.

        Returns:
            List of result dicts (same format as ask_question).
        """
        results = []
        session_id: Optional[str] = None
        for i, q in enumerate(questions):
            logger.info("Batch Q&A [%d/%d]: %s", i + 1, len(questions), q[:80])
            result = self.ask_question(
                notebook_id_or_url, q,
                session_id=session_id if keep_session else None,
            )
            results.append(result)
            # Capture session_id from first successful response
            if keep_session and session_id is None and isinstance(result, dict):
                session_id = result.get("session_id")
            time.sleep(2.0)  # Rate limit courtesy delay
        return results

    # ──── Source Management ────────────────────────────────────────────────────

    def list_sources(self, notebook_id: str) -> List[Dict[str, Any]]:
        """List sources in a notebook.

        Args:
            notebook_id: Library notebook ID.

        Returns:
            List of source dicts.
        """
        if not self.ensure_started():
            return []
        result = self.call_tool("list_sources", {"notebook_id": notebook_id})
        if isinstance(result, list):
            return result
        return result.get("sources", [])

    def add_source(self, notebook_id: str, url: Optional[str] = None,
                   text: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
        """Add a source to a notebook.

        Args:
            notebook_id: Library notebook ID.
            url: URL to add as source.
            text: Text content to add as source.
            title: Optional source title (for text sources).

        Returns:
            Dict with source_id and status.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        if url:
            source = {"type": "url", "value": url}
        elif text:
            source = {"type": "text", "value": text}
            if title:
                source["title"] = title
        else:
            return {"error": "Either url or text must be provided"}
        return self.call_tool("add_source", {
            "notebook_id": notebook_id,
            "source": source,
        }, timeout=60.0)

    # ──── Audio / Video Generation ─────────────────────────────────────────────

    def generate_audio_overview(self, notebook_id: str,
                                 style: str = "standard") -> Dict[str, Any]:
        """Trigger audio overview generation for a notebook.

        Args:
            notebook_id: Library notebook ID.
            style: Unused (kept for API compatibility — NLM controls audio style).

        Returns:
            Dict with status, progress.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("generate_audio_overview", {
            "notebook_id": notebook_id,
        }, timeout=30.0)

    def get_audio_status(self, notebook_id: str) -> Dict[str, Any]:
        """Check audio overview generation status.

        Args:
            notebook_id: Library notebook ID.

        Returns:
            Dict with status ("generating", "ready", "failed"), duration.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("get_audio_status", {"notebook_id": notebook_id})

    def generate_video_overview(self, notebook_id: str,
                                 style: str = "cinematic") -> Dict[str, Any]:
        """Generate a video overview of a notebook (10 visual styles).

        Args:
            notebook_id: Library notebook ID.
            style: Video style ("cinematic", "documentary", "minimalist", etc.).

        Returns:
            Dict with video_id, status, style.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("generate_video_overview", {
            "notebook_id": notebook_id,
            "style": style,
        }, timeout=60.0)

    # ──── Data Extraction ──────────────────────────────────────────────────────

    def extract_data_tables(self, notebook_id: str,
                             query: str = "") -> Dict[str, Any]:
        """Extract structured data tables from notebook sources.

        Args:
            notebook_id: Library notebook ID.
            query: Optional filter query for specific data.

        Returns:
            Dict with tables (list of JSON table objects).
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        args: Dict[str, Any] = {"notebook_id": notebook_id}
        if query:
            args["query"] = query
        return self.call_tool("extract_data_tables", args, timeout=60.0)

    def get_chat_history(self, notebook_id: str,
                          max_messages: int = 50) -> Dict[str, Any]:
        """Extract conversation history from a notebook.

        Args:
            notebook_id: Library notebook ID.
            max_messages: Maximum message pairs to retrieve.

        Returns:
            Dict with messages list and total count.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("get_notebook_chat_history", {
            "notebook_id": notebook_id,
            "limit": max_messages,
        })

    # ──── Quota / Health ──────────────────────────────────────────────────────

    def get_quota(self) -> Dict[str, Any]:
        """Get license tier, usage, and query limits.

        Returns:
            Dict with tier, notebooks_used, queries_today, daily_limit.
        """
        if not self.ensure_started():
            return {"error": "Node server not running"}
        return self.call_tool("get_quota", {})

    def list_available_tools(self) -> List[str]:
        """Return list of tool names available on the Node server."""
        return list(self._available_tools)


# ──── Singleton ────────────────────────────────────────────────────────────────

_bridge_instance: Optional[NLMNodeBridge] = None
_bridge_lock = threading.Lock()


def get_nlm_node_bridge() -> NLMNodeBridge:
    """Get the singleton NLMNodeBridge instance.

    Thread-safe. Creates and starts the Node process on first call.
    """
    global _bridge_instance
    if _bridge_instance is None:
        with _bridge_lock:
            if _bridge_instance is None:
                _bridge_instance = NLMNodeBridge()
    return _bridge_instance
