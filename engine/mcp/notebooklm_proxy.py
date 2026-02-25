"""
NotebookLM MCP Proxy — bridges CosySim skills to the notebooklm-mcp server.

Architecture
~~~~~~~~~~~~
The ``notebooklm-mcp`` npm package exposes NotebookLM
capabilities (ask, add source, generate audio, etc.) through a Node.js
server.  This proxy manages the Node.js process lifecycle and forwards
HTTP requests from Python skills to the server's REST API.

    CosySim skill  ──▶  NotebookLMProxy  ──HTTP──▶  notebooklm-mcp (Node.js)
                                                         │
                                                    Google Auth
                                                   (Chrome profile)

Configuration (``config/default.yaml`` under ``notebooklm`` key)::

    notebooklm:
      enabled: true
      node_cmd: "node"
      server_path: "node_modules/notebooklm-mcp/dist/index.js"
      base_url: "http://localhost:8800"
      auth_profile_dir: ""          # Chrome profile for Google sign-in

Usage::

    from engine.mcp.notebooklm_proxy import get_notebooklm_proxy
    proxy = get_notebooklm_proxy()
    if proxy.start():
        result = proxy.ask("notebook-abc", "Summarise the key points")
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Defaults ───────────────────────────────────────────────────────────
_DEFAULT_BASE_URL = "http://localhost:8800"
_HEALTH_TIMEOUT = 10          # seconds to wait for server readiness
_REQUEST_TIMEOUT = 30         # per-request timeout
_HEALTH_POLL_INTERVAL = 0.5   # seconds between health-check polls


# ── Proxy Class ────────────────────────────────────────────────────────

class NotebookLMProxy:
    """Manages the notebooklm-mcp Node.js process and forwards requests."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._base_url: str = config.get("base_url", _DEFAULT_BASE_URL)
        self._node_cmd: str = config.get("node_cmd", "node")
        self._server_path: str = config.get("server_path", "")
        self._auth_profile: str = config.get("auth_profile_dir", "")
        self._lock = threading.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the Node.js server and wait until it is healthy."""
        with self._lock:
            if self.is_running():
                return True
            if not self._server_path:
                logger.error("notebooklm.server_path not configured")
                return False
            env = None
            if self._auth_profile:
                import os
                env = {**os.environ, "CHROME_PROFILE_DIR": self._auth_profile}
            try:
                self._process = subprocess.Popen(
                    [self._node_cmd, self._server_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                logger.info("notebooklm-mcp process started (pid=%s)", self._process.pid)
            except FileNotFoundError:
                logger.error("Node.js binary not found: %s", self._node_cmd)
                return False
            except OSError as exc:
                logger.error("Failed to start notebooklm-mcp: %s", exc)
                return False
        return self._wait_healthy()

    def stop(self) -> None:
        """Terminate the Node.js server if running."""
        with self._lock:
            if self._process is None:
                return
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
            except OSError:
                pass
            logger.info("notebooklm-mcp process stopped")
            self._process = None

    def restart(self) -> bool:
        """Stop then start the server."""
        self.stop()
        return self.start()

    def is_running(self) -> bool:
        """Return *True* if the Node.js process is alive."""
        return self._process is not None and self._process.poll() is None

    # ── API methods ────────────────────────────────────────────────────

    def ask(self, notebook_id: str, question: str) -> dict:
        """Send a question to a NotebookLM notebook."""
        return self._post("/ask", {"notebook_id": notebook_id, "question": question})

    def add_source(self, notebook_id: str, source_type: str, source_value: str) -> dict:
        """Add a source (URL, text, file) to a notebook."""
        return self._post("/add_source", {
            "notebook_id": notebook_id,
            "source_type": source_type,
            "source_value": source_value,
        })

    def generate_audio(self, notebook_id: str, customization: str = "") -> dict:
        """Generate an Audio Overview for a notebook."""
        payload: Dict[str, Any] = {"notebook_id": notebook_id}
        if customization:
            payload["customization"] = customization
        return self._post("/generate_audio", payload)

    def list_notebooks(self) -> list:
        """List available notebooks."""
        result = self._get("/list_notebooks")
        return result.get("notebooks", []) if isinstance(result, dict) else []

    def search(self, query: str) -> list:
        """Search across notebooks."""
        result = self._post("/search", {"query": query})
        return result.get("results", []) if isinstance(result, dict) else []

    # ── internal helpers ───────────────────────────────────────────────

    def _wait_healthy(self) -> bool:
        """Poll the server until it responds or timeout expires."""
        deadline = time.monotonic() + _HEALTH_TIMEOUT
        while time.monotonic() < deadline:
            if not self.is_running():
                logger.error("notebooklm-mcp process exited prematurely")
                return False
            try:
                resp = urllib.request.urlopen(
                    f"{self._base_url}/health", timeout=2,
                )
                if resp.status == 200:
                    logger.info("notebooklm-mcp server is healthy")
                    return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(_HEALTH_POLL_INTERVAL)
        logger.error("notebooklm-mcp did not become healthy within %ss", _HEALTH_TIMEOUT)
        return False

    def _post(self, path: str, payload: dict) -> dict:
        return self._request(path, payload)

    def _get(self, path: str) -> dict:
        return self._request(path, data=None)

    def _request(self, path: str, data: Optional[dict] = None) -> dict:
        """Send an HTTP request to the Node.js server and return parsed JSON."""
        if not self.is_running():
            return {"error": "notebooklm-mcp server is not running"}
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
    """Return the global *NotebookLMProxy* instance (created on first call)."""
    global _proxy
    if _proxy is None:
        with _proxy_lock:
            if _proxy is None:
                cfg = get_config().get("notebooklm", default={})
                _proxy = NotebookLMProxy(cfg if isinstance(cfg, dict) else {})
    return _proxy
