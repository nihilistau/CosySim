"""
Nexus HTTP Client — CosySim's interface to the Nexus Knowledge System.

Usage:
    from engine.nexus.client import get_nexus_client
    client = get_nexus_client()
    results = client.search("combat mechanics")
    client.add_entry("Combat Log", "Player defeated dragon", content_type="history")
"""
import json
import logging
import urllib.request
import urllib.error
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8700"

class NexusClient:
    """HTTP client for Nexus REST API."""
    
    def __init__(self, base_url: str = _DEFAULT_URL, timeout: int = 30):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
    
    # ─── Knowledge Entries ─────────────────────────────────────
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        result = self._get(f"/api/search?q={query}&limit={limit}")
        return result.get("data", []) if result.get("ok") else []
    
    def add_entry(self, title: str, content: str, content_type: str = "note",
                  category: str = "", tags: list = None,
                  created_by: str = "cosysim") -> Optional[str]:
        result = self._post("/api/entries", {
            "title": title, "content": content, "content_type": content_type,
            "category": category, "tags": tags or [], "created_by": created_by,
        })
        return result.get("data", {}).get("id") if result.get("ok") else None
    
    def get_entry(self, entry_id: str) -> Optional[Dict]:
        result = self._get(f"/api/entries/{entry_id}")
        return result.get("data") if result.get("ok") else None
    
    def update_entry(self, entry_id: str, **fields) -> bool:
        result = self._put(f"/api/entries/{entry_id}", fields)
        return result.get("ok", False)
    
    def delete_entry(self, entry_id: str) -> bool:
        result = self._delete(f"/api/entries/{entry_id}")
        return result.get("ok", False)
    
    def list_entries(self, content_type: str = "", category: str = "",
                     limit: int = 20) -> List[Dict]:
        params = []
        if content_type: params.append(f"content_type={content_type}")
        if category: params.append(f"category={category}")
        params.append(f"limit={limit}")
        result = self._get(f"/api/entries?{'&'.join(params)}")
        return result.get("data", []) if result.get("ok") else []
    
    # ─── Agent Submission ──────────────────────────────────────
    
    def agent_submit(self, agent_id: str, submit_type: str, title: str,
                     content: str, category: str = "", tags: list = None) -> Optional[str]:
        result = self._post("/api/agent/submit", {
            "agent_id": agent_id, "type": submit_type,
            "title": title, "content": content,
            "category": category, "tags": tags or [],
        })
        return result.get("data", {}).get("entry_id") if result.get("ok") else None
    
    # ─── NotebookLM ───────────────────────────────────────────
    
    def nlm_ask(self, question: str, notebook_id: str = "") -> Dict:
        payload = {"question": question}
        if notebook_id: payload["notebook_id"] = notebook_id
        return self._post("/api/nlm/ask", payload)
    
    def nlm_list_notebooks(self) -> List[Dict]:
        result = self._get("/api/nlm/notebooks")
        return result.get("data", []) if result.get("ok") else []
    
    def nlm_sync(self, notebook_id: str = "") -> Dict:
        payload = {"notebook_id": notebook_id} if notebook_id else {}
        return self._post("/api/nlm/sync", payload)
    
    # ─── System ───────────────────────────────────────────────
    
    def health(self) -> Dict:
        return self._get("/api/health")
    
    def stats(self) -> Dict:
        return self._get("/api/stats")
    
    def is_available(self) -> bool:
        try:
            result = self.health()
            return result.get("ok", False)
        except Exception:
            return False
    
    # ─── HTTP Helpers ─────────────────────────────────────────
    
    def _get(self, path: str) -> dict:
        return self._request("GET", path)
    
    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)
    
    def _put(self, path: str, payload: dict) -> dict:
        return self._request("PUT", path, payload)
    
    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)
    
    def _request(self, method: str, path: str, payload: dict = None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            if payload and method in ("POST", "PUT"):
                data = json.dumps(payload).encode()
                req = urllib.request.Request(url, data=data, method=method,
                    headers={"Content-Type": "application/json"})
            else:
                req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("Nexus %s %s failed: %s", method, path, exc)
            return {"ok": False, "error": str(exc)}


# Singleton
_client = None
_lock = threading.Lock()

def get_nexus_client(base_url: str = None) -> NexusClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                if base_url is None:
                    try:
                        from engine.config import get_config
                        base_url = get_config().get("nexus.base_url", _DEFAULT_URL)
                    except Exception:
                        base_url = _DEFAULT_URL
                _client = NexusClient(base_url)
    return _client
