"""AnythingLLM integration — workspace, chat, and knowledge sync.

Connects to AnythingLLM instances (phone + laptop) for:
- Workspace management and document ingestion
- Chat with embedded knowledge bases
- Bidirectional knowledge sync with Nexus
- Multi-instance routing (phone vs laptop)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from engine.config import get_config

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────────────

_instance: Optional[AnythingLLMClient] = None
_lock = threading.Lock()


def get_anythingllm_client() -> AnythingLLMClient:
    """Get or create the singleton AnythingLLM client."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AnythingLLMClient()
    return _instance


def reset_anythingllm_client() -> None:
    """Reset singleton (for testing)."""
    global _instance
    _instance = None


# ── Client ──────────────────────────────────────────────────────────────


class AnythingLLMClient:
    """REST client for AnythingLLM API.

    Supports multiple named instances (e.g. 'laptop', 'phone') with
    automatic failover. Each instance has its own URL and API key.

    Args:
        instances: Optional dict of {name: {url, api_key}} overriding config.
    """

    def __init__(self, instances: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        cfg = get_config()
        self._instances: Dict[str, Dict[str, str]] = {}
        self._default_instance: str = ""
        self._stats: Dict[str, int] = {
            "requests": 0, "errors": 0, "chats": 0, "syncs": 0,
        }

        if instances:
            self._instances = instances
        else:
            raw = cfg.get("anythingllm.instances", {})
            if isinstance(raw, dict):
                for name, inst in raw.items():
                    if isinstance(inst, dict) and inst.get("url"):
                        self._instances[name] = {
                            "url": inst["url"].rstrip("/"),
                            "api_key": inst.get("api_key", ""),
                        }

        self._default_instance = cfg.get("anythingllm.default_instance", "")
        if not self._default_instance and self._instances:
            self._default_instance = next(iter(self._instances))

        self._timeout: int = cfg.get("anythingllm.timeout_seconds", 30)
        self._connected: Dict[str, bool] = {}

        logger.info(
            "AnythingLLM client initialized with %d instance(s): %s",
            len(self._instances),
            ", ".join(self._instances.keys()) or "none",
        )

    # ── HTTP Layer ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        instance: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        """Make an HTTP request to an AnythingLLM instance."""
        inst_name = instance or self._default_instance
        inst = self._instances.get(inst_name)
        if not inst:
            raise ValueError(f"Unknown AnythingLLM instance: {inst_name}")

        url = f"{inst['url']}{path}"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if inst.get("api_key"):
            headers["Authorization"] = f"Bearer {inst['api_key']}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)

        self._stats["requests"] += 1
        try:
            with urlopen(req, timeout=timeout or self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            self._stats["errors"] += 1
            logger.warning("AnythingLLM %s %s failed: %s", method, path, exc)
            raise

    def _get(self, path: str, instance: Optional[str] = None) -> Any:
        return self._request("GET", path, instance=instance)

    def _post(self, path: str, data: Optional[Dict[str, Any]] = None,
              instance: Optional[str] = None) -> Any:
        return self._request("POST", path, data=data, instance=instance)

    def _delete(self, path: str, instance: Optional[str] = None) -> Any:
        return self._request("DELETE", path, instance=instance)

    # ── Connection ──────────────────────────────────────────────────────

    def connect(self, instance: Optional[str] = None) -> Dict[str, Any]:
        """Test connection and verify API key.

        Returns:
            Dict with connection status and system info.
        """
        inst_name = instance or self._default_instance
        try:
            result = self._get("/api/v1/auth", instance=inst_name)
            self._connected[inst_name] = True
            logger.info("Connected to AnythingLLM instance %r", inst_name)
            return {"ok": True, "instance": inst_name, "auth": result}
        except Exception as exc:
            self._connected[inst_name] = False
            return {"ok": False, "instance": inst_name, "error": str(exc)}

    def is_connected(self, instance: Optional[str] = None) -> bool:
        """Check if an instance is connected."""
        inst_name = instance or self._default_instance
        return self._connected.get(inst_name, False)

    def connect_all(self) -> Dict[str, Dict[str, Any]]:
        """Connect to all configured instances."""
        results = {}
        for name in self._instances:
            results[name] = self.connect(instance=name)
        return results

    # ── Workspaces ──────────────────────────────────────────────────────

    def list_workspaces(self, instance: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all workspaces on an instance."""
        result = self._get("/api/v1/workspaces", instance=instance)
        return result.get("workspaces", []) if isinstance(result, dict) else []

    def get_workspace(self, slug: str, instance: Optional[str] = None) -> Dict[str, Any]:
        """Get workspace details by slug."""
        return self._get(f"/api/v1/workspace/{slug}", instance=instance)

    def create_workspace(
        self, name: str, instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new workspace."""
        return self._post("/api/v1/workspace/new", {"name": name}, instance=instance)

    def delete_workspace(self, slug: str, instance: Optional[str] = None) -> Dict[str, Any]:
        """Delete a workspace."""
        return self._delete(f"/api/v1/workspace/{slug}", instance=instance)

    # ── Chat ────────────────────────────────────────────────────────────

    def chat(
        self,
        workspace_slug: str,
        message: str,
        mode: str = "chat",
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a chat message to a workspace.

        Args:
            workspace_slug: The workspace to chat in.
            message: The user message.
            mode: 'chat' for normal, 'query' for RAG-only.
            instance: Which instance to use.

        Returns:
            Dict with response text, sources, etc.
        """
        self._stats["chats"] += 1
        result = self._post(
            f"/api/v1/workspace/{workspace_slug}/chat",
            {"message": message, "mode": mode},
            instance=instance,
        )
        return result

    def get_chat_history(
        self, workspace_slug: str, instance: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get chat history for a workspace."""
        result = self._get(
            f"/api/v1/workspace/{workspace_slug}/chats", instance=instance,
        )
        return result.get("history", []) if isinstance(result, dict) else []

    # ── Threads ─────────────────────────────────────────────────────────

    def list_threads(
        self, workspace_slug: str, instance: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List chat threads in a workspace."""
        result = self._get(
            f"/api/v1/workspace/{workspace_slug}/threads", instance=instance,
        )
        return result.get("threads", []) if isinstance(result, dict) else []

    def create_thread(
        self, workspace_slug: str, name: str = "",
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new chat thread in a workspace."""
        data = {"name": name} if name else {}
        return self._post(
            f"/api/v1/workspace/{workspace_slug}/thread/new",
            data, instance=instance,
        )

    def chat_in_thread(
        self,
        workspace_slug: str,
        thread_slug: str,
        message: str,
        mode: str = "chat",
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a message in a specific thread."""
        self._stats["chats"] += 1
        return self._post(
            f"/api/v1/workspace/{workspace_slug}/thread/{thread_slug}/chat",
            {"message": message, "mode": mode},
            instance=instance,
        )

    # ── Documents ───────────────────────────────────────────────────────

    def list_documents(self, instance: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all uploaded documents."""
        result = self._get("/api/v1/documents", instance=instance)
        items = result.get("localFiles", {}) if isinstance(result, dict) else {}
        if isinstance(items, dict):
            return items.get("items", [])
        return items if isinstance(items, list) else []

    def upload_document(
        self,
        workspace_slug: str,
        title: str,
        content: str,
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload text content as a document to a workspace.

        Uses the raw-text upload endpoint.
        """
        return self._post(
            f"/api/v1/document/raw-text",
            {"textContent": content, "metadata": {"title": title}},
            instance=instance,
        )

    def embed_document(
        self,
        workspace_slug: str,
        doc_path: str,
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Embed a document into a workspace's vector store."""
        return self._post(
            f"/api/v1/workspace/{workspace_slug}/update-embeddings",
            {"adds": [doc_path]},
            instance=instance,
        )

    # ── Nexus Sync ──────────────────────────────────────────────────────

    def sync_to_nexus(
        self,
        workspace_slug: str,
        instance: Optional[str] = None,
        category: str = "anythingllm",
    ) -> Dict[str, Any]:
        """Sync workspace chat history to Nexus as Q&A entries.

        Extracts user/assistant message pairs from chat history and
        stores them as Nexus Q&A entries for cross-system retrieval.

        Returns:
            Dict with count of synced entries.
        """
        from engine.nexus.client import get_nexus_client

        self._stats["syncs"] += 1
        client = get_nexus_client()
        history = self.get_chat_history(workspace_slug, instance=instance)

        synced = 0
        for entry in history:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content", "")
            role = entry.get("role", "")
            if role == "assistant" and content:
                # Find the preceding user message for Q&A pairing
                idx = history.index(entry)
                question = ""
                if idx > 0:
                    prev = history[idx - 1]
                    if isinstance(prev, dict) and prev.get("role") == "user":
                        question = prev.get("content", "")

                if question:
                    client.add_qa(question, content, category=category)
                    synced += 1

        logger.info(
            "Synced %d Q&A pairs from %s/%s to Nexus",
            synced, instance or self._default_instance, workspace_slug,
        )
        return {"synced": synced, "workspace": workspace_slug}

    def sync_from_nexus(
        self,
        workspace_slug: str,
        query: str = "*",
        limit: int = 50,
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Push Nexus knowledge into an AnythingLLM workspace.

        Searches Nexus for entries matching the query and uploads them
        as documents to the workspace for RAG retrieval.

        Returns:
            Dict with count of uploaded documents.
        """
        from engine.nexus.client import get_nexus_client

        self._stats["syncs"] += 1
        client = get_nexus_client()
        entries = client.search(query, limit=limit)

        uploaded = 0
        for entry in (entries or []):
            title = entry.get("title", "Untitled")
            content = entry.get("content", "")
            if not content:
                continue
            try:
                self.upload_document(
                    workspace_slug, title, content, instance=instance,
                )
                uploaded += 1
            except Exception as exc:
                logger.debug("Failed to upload %r: %s", title, exc)

        logger.info(
            "Pushed %d Nexus entries to %s/%s",
            uploaded, instance or self._default_instance, workspace_slug,
        )
        return {"uploaded": uploaded, "workspace": workspace_slug}

    # ── System Info ─────────────────────────────────────────────────────

    def system_info(self, instance: Optional[str] = None) -> Dict[str, Any]:
        """Get system information from an instance."""
        try:
            return self._get("/api/v1/system", instance=instance)
        except Exception as exc:
            return {"error": str(exc)}

    def status(self) -> Dict[str, Any]:
        """Get status of all configured instances."""
        return {
            "instances": {
                name: {
                    "url": inst["url"],
                    "connected": self._connected.get(name, False),
                }
                for name, inst in self._instances.items()
            },
            "default": self._default_instance,
            "stats": dict(self._stats),
        }

    def list_instances(self) -> List[Dict[str, str]]:
        """List all configured instances."""
        return [
            {"name": name, "url": inst["url"], "connected": self._connected.get(name, False)}
            for name, inst in self._instances.items()
        ]
