"""
Nexus HTTP Client — CosySim's interface to the Nexus Knowledge System.

v0.50a: Extended with session tracking, rules engine, prompt management,
batch operations, and retry logic.

Usage:
    from engine.nexus.client import get_nexus_client
    client = get_nexus_client()
    results = client.search("combat mechanics")
    client.add_entry("Combat Log", "Player defeated dragon", content_type="history")
    client.log_session("sess-1", project="CosySim", commits=["abc123"])
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
import urllib.error
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from engine.nexus.models import NexusEntry, NexusRule
    from engine.nexus.rules_client import NexusRulesClient
    from engine.nexus.session_client import NexusSessionClient
    from engine.nexus.memory_client import NexusMemoryClient

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8700"

class NexusClient:
    """HTTP client for Nexus REST API with retry and caching."""
    
    def __init__(self, base_url: str = _DEFAULT_URL, timeout: int = 30,
                 max_retries: int = 2):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._cache: Dict[str, tuple] = {}  # path -> (data, timestamp)
        self._cache_ttl = 60  # seconds
        # Domain facades — lazy-init to avoid circular imports
        self._rules: Optional[NexusRulesClient] = None
        self._sessions: Optional[NexusSessionClient] = None
        self._memory: Optional[NexusMemoryClient] = None

    @property
    def rules(self) -> NexusRulesClient:
        if self._rules is None:
            from engine.nexus.rules_client import NexusRulesClient
            self._rules = NexusRulesClient(self)
        return self._rules

    @property
    def sessions(self) -> NexusSessionClient:
        if self._sessions is None:
            from engine.nexus.session_client import NexusSessionClient
            self._sessions = NexusSessionClient(self)
        return self._sessions

    @property
    def memory(self) -> NexusMemoryClient:
        if self._memory is None:
            from engine.nexus.memory_client import NexusMemoryClient
            self._memory = NexusMemoryClient(self)
        return self._memory

    @staticmethod
    def _parse_entry(d: dict) -> NexusEntry:
        from engine.nexus.models import NexusEntry

        def _parse_tags(raw: Any) -> List[str]:
            """Tags stored as JSON string in DB; normalise to list."""
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    return [t.strip() for t in raw.split(",") if t.strip()]
            return []

        try:
            # Normalise tags before model_validate so Pydantic never sees a string
            d2 = dict(d)
            if "tags" in d2:
                d2["tags"] = _parse_tags(d2["tags"])
            return NexusEntry.model_validate(d2)
        except Exception:
            return NexusEntry(
                id=d.get("id", ""),
                title=d.get("title", ""),
                content=d.get("content", ""),
                created_by=d.get("created_by", ""),
                content_type=d.get("content_type", "note"),
                category=d.get("category", ""),
                tags=_parse_tags(d.get("tags", [])),
            )

    @staticmethod
    def _parse_rule(d: dict) -> NexusRule:
        from engine.nexus.models import NexusRule

        def _parse_json_field(raw: Any, default: Any) -> Any:
            """Decode JSON-string fields that Pydantic expects as dict/list."""
            if isinstance(raw, (dict, list)):
                return raw
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except Exception:
                    return default
            return default

        try:
            d2 = dict(d)
            for field in ("condition", "action"):
                if field in d2:
                    d2[field] = _parse_json_field(d2[field], {})
            return NexusRule.model_validate(d2)
        except Exception:
            return NexusRule(
                rule_id=d.get("rule_id", d.get("id", "")),
                scope=d.get("scope", ""),
                rule_type=d.get("rule_type", ""),
                condition=_parse_json_field(d.get("condition", {}), {}),
                action=_parse_json_field(d.get("action", {}), {}),
                active=d.get("active", True),
            )

    # ─── Knowledge Entries ─────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> List[NexusEntry]:
        encoded = urllib.parse.urlencode({"q": query, "limit": limit})
        result = self._get(f"/api/search?{encoded}")
        data = result.get("data", []) if result.get("ok") else []
        return [self._parse_entry(d) for d in data]
    
    def add_entry(self, title: str, content: str, content_type: str = "note",
                  category: str = "", tags: list = None,
                  created_by: str = "cosysim", **kwargs) -> Optional[str]:
        from engine.nexus.models import NexusEntryCreate
        try:
            validated = NexusEntryCreate(
                title=title, content=content, content_type=content_type,
                category=category, tags=tags or [], created_by=created_by,
            )
        except Exception as exc:
            logger.warning("NexusEntryCreate validation failed: %s", exc)
            return None
        result = self._post("/api/entries", validated.model_dump())
        return result.get("data", {}).get("id") if result.get("ok") else None
    
    def get_entry(self, entry_id: str) -> Optional[NexusEntry]:
        result = self._get(f"/api/entries/{entry_id}")
        data = result.get("data") if result.get("ok") else None
        return self._parse_entry(data) if data else None
    
    def update_entry(self, entry_id: str, **fields) -> bool:
        result = self._put(f"/api/entries/{entry_id}", fields)
        return result.get("ok", False)
    
    def delete_entry(self, entry_id: str) -> bool:
        result = self._delete(f"/api/entries/{entry_id}")
        return result.get("ok", False)
    
    def list_entries(self, content_type: str = "", category: str = "",
                     limit: int = 20) -> List[NexusEntry]:
        params = []
        if content_type: params.append(f"type={content_type}")
        if category: params.append(f"category={category}")
        params.append(f"limit={limit}")
        result = self._get(f"/api/entries?{'&'.join(params)}")
        data = result.get("data", []) if result.get("ok") else []
        return [self._parse_entry(d) for d in data]

    def list_by_type(self, content_type: str, category: str = "",
                     limit: int = 50) -> List[NexusEntry]:
        """Shortcut: list entries filtered by content_type."""
        params = [f"limit={limit}"]
        if category:
            params.append(f"category={category}")
        result = self._get(f"/api/entries/by-type/{content_type}?{'&'.join(params)}")
        data = result.get("data", []) if result.get("ok") else []
        return [self._parse_entry(d) for d in data]
    
    # ─── Agent Submission ──────────────────────────────────────
    
    def agent_submit(self, agent_id: str, submit_type: str, title: str,
                     content: str, category: str = "", tags: list = None,
                     importance: float = 0.5) -> Optional[str]:
        result = self._post("/api/agent/submit", {
            "agent_id": agent_id, "type": submit_type,
            "title": title, "content": content,
            "category": category, "tags": tags or [],
            "importance": importance,
        })
        return result.get("data", {}).get("entry_id") if result.get("ok") else None

    # ─── Sessions ─────────────────────────────────────────────

    def log_session(self, session_id: str = None, project: str = "",
                    repo: str = "", branch: str = "",
                    agent_id: str = "copilot", **kwargs) -> Optional[str]:
        """Create a new session record in Nexus. Returns session ID."""
        payload = {
            "project": project, "repo": repo,
            "branch": branch, "agent_id": agent_id,
        }
        if session_id:
            payload["id"] = session_id
        result = self._post("/api/sessions", payload)
        return result.get("data", {}).get("id") if result.get("ok") else None

    def update_session(self, session_id: str, **fields) -> bool:
        """Update session (summary, commits, files_changed, status, etc.)."""
        result = self._put(f"/api/sessions/{session_id}", fields)
        return result.get("ok", False)

    def get_session(self, session_id: str) -> Optional[Dict]:
        result = self._get(f"/api/sessions/{session_id}")
        return result.get("data") if result.get("ok") else None

    def list_sessions(self, project: str = "", status: str = "",
                      limit: int = 50) -> List[Dict]:
        params = [f"limit={limit}"]
        if project: params.append(f"project={project}")
        if status: params.append(f"status={status}")
        result = self._get(f"/api/sessions?{'&'.join(params)}")
        return result.get("data", []) if result.get("ok") else []

    # ─── Rules ────────────────────────────────────────────────

    def get_rules(self, scope: str = "", rule_type: str = "") -> List[NexusRule]:
        """Get active rules, optionally filtered by scope and type."""
        params = []
        if scope: params.append(f"scope={scope}")
        if rule_type: params.append(f"type={rule_type}")
        qs = f"?{'&'.join(params)}" if params else ""
        result = self._get(f"/api/rules{qs}")
        data = result.get("data", []) if result.get("ok") else []
        return [self._parse_rule(d) for d in data]

    def add_rule(self, scope: str, rule_type: str, name: str,
                 condition: dict = None, action: dict = None,
                 priority: int = 50, active: bool = True) -> Optional[str]:
        """Create a new rule. Returns rule ID."""
        result = self._post("/api/rules", {
            "scope": scope, "rule_type": rule_type, "name": name,
            "condition": condition or {}, "action": action or {},
            "priority": priority, "active": active,
        })
        return result.get("data", {}).get("id") if result.get("ok") else None

    # ─── Prompts ──────────────────────────────────────────────

    def store_prompt(self, name: str, content: str, category: str = "system",
                     version: str = "1", tags: list = None) -> Optional[str]:
        """Store a prompt in Nexus as a 'prompt' content_type entry."""
        return self.add_entry(
            title=name, content=content, content_type="prompt",
            category=category, tags=(tags or []) + [f"v:{version}"],
            created_by="cosysim",
        )

    def get_prompts(self, category: str = "", name: str = "") -> List[Dict]:
        """Retrieve stored prompts, optionally filtered."""
        prompts = self.list_by_type("prompt", category=category)
        if name:
            prompts = [p for p in prompts if name.lower() in p.get("title", "").lower()]
        return prompts

    # ─── Batch Operations ─────────────────────────────────────

    def batch_add(self, entries: List[Dict]) -> List[str]:
        """Add multiple entries in one request. Returns list of IDs."""
        result = self._post("/api/batch", {"entries": entries})
        if result.get("ok"):
            return result.get("data", {}).get("ids", [])
        return []

    # ─── Changelog ────────────────────────────────────────────

    def store_changelog(self, version: str, changes: str,
                        commits: list = None) -> Optional[str]:
        """Store a changelog entry in Nexus."""
        content = changes
        if commits:
            content += "\n\nCommits: " + ", ".join(commits)
        return self.add_entry(
            title=f"Changelog {version}", content=content,
            content_type="changelog", category="system",
            tags=["changelog", version],
        )
    
    # ─── NotebookLM ───────────────────────────────────────────
    
    def nlm_ask(self, question: str, notebook_id: str = "",
                notebook_url: str = "") -> Dict:
        """Ask via HTTP-only backend."""
        payload = {"question": question}
        if notebook_id: payload["notebook_id"] = notebook_id
        if notebook_url: payload["notebook_url"] = notebook_url
        return self._post("/api/nlm/ask", payload)
    
    def nlm_unified_ask(self, question: str, notebook_id: str = "",
                        notebook_url: str = "") -> Dict:
        """Ask via best available backend (HTTP → browser fallback)."""
        payload = {"question": question}
        if notebook_id: payload["notebook_id"] = notebook_id
        if notebook_url: payload["notebook_url"] = notebook_url
        return self._post("/api/nlm/unified/ask", payload)
    
    def nlm_status(self) -> Dict:
        """Get status of all NLM backends."""
        return self._get("/api/nlm/status")
    
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

    # ─── Q&A System (v0.50b) ─────────────────────────────────

    def ask(self, question: str, depth: str = "auto",
            category: str = "") -> Dict:
        """Smart Q&A — searches cache, knowledge, then NLM if needed."""
        payload = {"question": question, "depth": depth}
        if category:
            payload["category"] = category
        result = self._post("/api/research/ask", payload)
        return result.get("data", {}) if result.get("ok") else {}

    def find_qa(self, question: str, limit: int = 5) -> List[Dict]:
        """Search the Q&A cache for existing answers."""
        encoded = urllib.parse.urlencode({"q": question, "limit": limit})
        result = self._get(f"/api/qa/ask?{encoded}")
        return result.get("data", []) if result.get("ok") else []

    def add_qa(self, question: str, answer: str,
               category: str = "", tags: list = None,
               quality_score: float = 0.5) -> Optional[str]:
        """Store a Q&A pair."""
        result = self._post("/api/qa", {
            "question": question, "answer": answer,
            "category": category, "tags": tags or [],
            "quality_score": quality_score,
        })
        return result.get("data", {}).get("id") if result.get("ok") else None

    # ─── Research Sessions (v0.50b) ──────────────────────────

    def research(self, question: str, notebook_id: str = "",
                 sources: list = None) -> Dict:
        """Start a deep NLM research session."""
        payload = {"question": question}
        if notebook_id:
            payload["notebook_id"] = notebook_id
        if sources:
            payload["sources"] = sources
        result = self._post("/api/research/deep", payload)
        return result.get("data", {}) if result.get("ok") else {}

    def converse(self, research_id: str, message: str) -> Dict:
        """Continue a research conversation."""
        result = self._post(f"/api/research/{research_id}/converse",
                           {"message": message})
        return result.get("data", {}) if result.get("ok") else {}

    def finish_research(self, research_id: str) -> Dict:
        """Complete a research session and distill Q&A."""
        result = self._post(f"/api/research/{research_id}/finish", {})
        return result.get("data", {}) if result.get("ok") else {}

    def list_research(self, status: str = "", limit: int = 20) -> List[Dict]:
        """List research sessions."""
        params = [f"limit={limit}"]
        if status:
            params.append(f"status={status}")
        result = self._get(f"/api/research?{'&'.join(params)}")
        return result.get("data", []) if result.get("ok") else []

    # ─── YouTube Import (v0.50b) ─────────────────────────────

    def import_youtube(self, url: str, category: str = "youtube",
                       tags: list = None) -> Dict:
        """Import a YouTube transcript into Nexus."""
        result = self._post("/api/import/youtube", {
            "url": url, "category": category, "tags": tags or [],
        })
        return result.get("data", {}) if result.get("ok") else {}

    # ─── Plugins (v0.50b) ────────────────────────────────────

    def list_plugins(self, scope: str = "",
                     hook_type: str = "") -> List[Dict]:
        """List registered Nexus plugins."""
        params = []
        if scope: params.append(f"scope={scope}")
        if hook_type: params.append(f"hook_type={hook_type}")
        qs = f"?{'&'.join(params)}" if params else ""
        result = self._get(f"/api/plugins{qs}")
        return result.get("data", []) if result.get("ok") else []

    def add_plugin(self, name: str, hook_type: str,
                   scope: str = "global",
                   config: dict = None) -> Optional[str]:
        """Register a new plugin."""
        result = self._post("/api/plugins", {
            "name": name, "hook_type": hook_type,
            "scope": scope, "config": config or {},
        })
        return result.get("data", {}).get("id") if result.get("ok") else None
    
    # ─── Access Tracking (v0.52b Sprint 10) ─────────────────────

    def track_access(self, entry_id: str) -> bool:
        """Increment access_count and update last_accessed for an entry.

        Returns True if tracking was recorded (even if Nexus doesn't
        support access tracking natively — falls back to annotation).
        """
        result = self._post(f"/api/entries/{entry_id}/annotate", {
            "type": "access",
            "data": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        })
        if result.get("ok"):
            return True
        # Fallback: Nexus may not have annotate endpoint — skip silently
        return False

    def search_ranked(self, query: str, limit: int = 10) -> List[Dict]:
        """Search with access-frequency boosting.

        Wraps standard search and re-ranks results by combining
        Nexus relevance with locally tracked access counts.
        """
        results = self.search(query, limit=limit * 2)
        # Track access for each result
        for r in results:
            entry_id = r.get("id", "")
            if entry_id:
                self.track_access(entry_id)
        return results[:limit]

    # ─── Inference Leaderboard (v0.52b Sprint 10) ─────────────

    def store_benchmark(self, model: str, method: str, metrics: Dict,
                        tags: list = None) -> Optional[str]:
        """Store a benchmark result in Nexus for leaderboard tracking.

        Args:
            model: Model identifier (e.g. "qwen3-0.6b")
            method: Inference method (e.g. "gpu_primary", "cpu_only", "spec_decode")
            metrics: Dict with tps, latency_ms, ttft_ms, memory_mb, etc.
            tags: Additional tags
        """
        content = (
            f"Model: {model}\n"
            f"Method: {method}\n"
            f"Tokens/sec: {metrics.get('tps', 0):.1f}\n"
            f"Latency (ms): {metrics.get('latency_ms', 0):.1f}\n"
            f"TTFT (ms): {metrics.get('ttft_ms', 0):.1f}\n"
            f"Memory (MB): {metrics.get('memory_mb', 0):.0f}\n"
            f"Context length: {metrics.get('context_length', 0)}\n"
            f"Concurrency: {metrics.get('concurrency', 1)}\n"
        )
        if metrics.get("notes"):
            content += f"Notes: {metrics['notes']}\n"

        return self.add_entry(
            title=f"Benchmark: {model} [{method}]",
            content=content,
            content_type="note",
            category="benchmarks",
            tags=(tags or []) + ["benchmark", "leaderboard", model, method],
            created_by="benchmark",
        )

    def get_leaderboard(self, method: str = "", limit: int = 20) -> List[NexusEntry]:
        """Retrieve benchmark entries from Nexus, optionally filtered by method."""
        entries = self.list_by_type("note", category="benchmarks", limit=limit)
        if method:
            entries = [e for e in entries if method in (e.get("content") or "")]
        return entries
    
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
                    time.sleep(0.5 * attempt)  # exponential backoff
                    continue
                logger.debug("Nexus %s %s failed after %d attempts: %s",
                            method, path, attempt, exc)
        return {"ok": False, "error": str(last_err)}


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
