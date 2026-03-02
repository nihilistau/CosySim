import os
import re

content = """
\"\"\"
Nexus HTTP Client — CosySim's interface to the Nexus Knowledge System.

v0.60a: Refactored to use Pydantic models and broken into Domain Clients.
\"\"\"
import json
import logging
import time
import urllib.parse
import urllib.request
import urllib.error
import threading
from typing import Any, Dict, List, Optional

from engine.nexus.models import NexusEntry, NexusRule, SessionLog, AgentMemory, NexusResponse

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8700"


class NexusHttpClient:
    \"\"\"Base HTTP client for Nexus REST API with retry.\"\"\"
    def __init__(self, base_url: str = _DEFAULT_URL, timeout: int = 30, max_retries: int = 2):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

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
        last_err = None
        for attempt in range(1, self._max_retries + 1):
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
                last_err = exc
                if attempt < self._max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                logger.debug("Nexus %s %s failed after %d attempts: %s",
                             method, path, attempt, exc)
        return {"ok": False, "error": str(last_err)}


class KnowledgeDomain:
    def __init__(self, http: NexusHttpClient):
        self.http = http

    def search(self, query: str, limit: int = 10) -> List[NexusEntry]:
        encoded = urllib.parse.urlencode({"q": query, "limit": limit})
        result = self.http._get(f"/api/search?{encoded}")
        if result.get("ok"):
            return [NexusEntry(**d) for d in result.get("data", [])]
        return []

    def add_entry(self, title: str, content: str, content_type: str = "note",
                  category: str = "", tags: list = None,
                  created_by: str = "cosysim") -> Optional[str]:
        result = self.http._post("/api/entries", {
            "title": title, "content": content, "content_type": content_type,
            "category": category, "tags": tags or [], "created_by": created_by,
        })
        return result.get("data", {}).get("id") if result.get("ok") else None

    def get_entry(self, entry_id: str) -> Optional[NexusEntry]:
        result = self.http._get(f"/api/entries/{entry_id}")
        if result.get("ok") and result.get("data"):
            return NexusEntry(**result.get("data"))
        return None

    def update_entry(self, entry_id: str, **fields) -> bool:
        result = self.http._put(f"/api/entries/{entry_id}", fields)
        return result.get("ok", False)

    def delete_entry(self, entry_id: str) -> bool:
        result = self.http._delete(f"/api/entries/{entry_id}")
        return result.get("ok", False)

    def list_entries(self, content_type: str = "", category: str = "",
                     limit: int = 20) -> List[NexusEntry]:
        params = []
        if content_type: params.append(f"type={content_type}")
        if category: params.append(f"category={category}")
        params.append(f"limit={limit}")
        result = self.http._get(f"/api/entries?{'&'.join(params)}")
        if result.get("ok"):
            return [NexusEntry(**d) for d in result.get("data", [])]
        return []

    def list_by_type(self, content_type: str, category: str = "",
                     limit: int = 50) -> List[NexusEntry]:
        params = [f"limit={limit}"]
        if category:
            params.append(f"category={category}")
        result = self.http._get(f"/api/entries/by-type/{content_type}?{'&'.join(params)}")
        if result.get("ok"):
            return [NexusEntry(**d) for d in result.get("data", [])]
        return []

    def batch_add(self, entries: List[Dict]) -> List[str]:
        result = self.http._post("/api/batch", {"entries": entries})
        if result.get("ok"):
            return result.get("data", {}).get("ids", [])
        return []


class RulesDomain:
    def __init__(self, http: NexusHttpClient):
        self.http = http

    def get_rules(self, scope: str = "", rule_type: str = "") -> List[NexusRule]:
        params = []
        if scope: params.append(f"scope={scope}")
        if rule_type: params.append(f"type={rule_type}")
        qs = f"?{'&'.join(params)}" if params else ""
        result = self.http._get(f"/api/rules{qs}")
        if result.get("ok"):
            # Map id -> rule_id if needed, assuming API returns rule_id or id
            rules_data = result.get("data", [])
            out = []
            for d in rules_data:
                if "rule_id" not in d and "id" in d:
                    d["rule_id"] = d.pop("id")
                out.append(NexusRule(**d))
            return out
        return []

    def add_rule(self, scope: str, rule_type: str, name: str,
                 condition: dict, action: dict,
                 priority: int = 50) -> Optional[str]:
        result = self.http._post("/api/rules", {
            "scope": scope, "rule_type": rule_type, "name": name,
            "condition": condition, "action": action, "priority": priority,
        })
        return result.get("data", {}).get("id") if result.get("ok") else None


class SessionDomain:
    def __init__(self, http: NexusHttpClient):
        self.http = http

    def log_session(self, session_id: str = None, project: str = "",
                    repo: str = "", branch: str = "",
                    agent_id: str = "copilot") -> Optional[str]:
        payload = {
            "project": project, "repo": repo,
            "branch": branch, "agent_id": agent_id,
        }
        if session_id:
            payload["id"] = session_id
        result = self.http._post("/api/sessions", payload)
        return result.get("data", {}).get("id") if result.get("ok") else None

    def update_session(self, session_id: str, **fields) -> bool:
        result = self.http._put(f"/api/sessions/{session_id}", fields)
        return result.get("ok", False)

    def get_session(self, session_id: str) -> Optional[SessionLog]:
        result = self.http._get(f"/api/sessions/{session_id}")
        if result.get("ok") and result.get("data"):
            d = result.get("data")
            if "session_id" not in d and "id" in d:
                d["session_id"] = d.pop("id")
            # map start_time if needed, pydantic handles basic datetime parsing
            return SessionLog(**d)
        return None

    def list_sessions(self, project: str = "", status: str = "",
                      limit: int = 50) -> List[SessionLog]:
        params = [f"limit={limit}"]
        if project: params.append(f"project={project}")
        if status: params.append(f"status={status}")
        result = self.http._get(f"/api/sessions?{'&'.join(params)}")
        if result.get("ok"):
            out = []
            for d in result.get("data", []):
                if "session_id" not in d and "id" in d:
                    d["session_id"] = d.pop("id")
                out.append(SessionLog(**d))
            return out
        return []


class NexusClient(NexusHttpClient):
    \
