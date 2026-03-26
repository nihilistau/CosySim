"""
Nexus HTTP Client — CosySim's interface to the Nexus Knowledge System.

v0.50a: Extended with session tracking, rules engine, prompt management,
batch operations, and retry logic.

Version: v1.57.1 [2026-03-26]
Author:  CosySim Team

Change Log:
    v1.57.1 [2026-03-26] — Non-blocking embedding hooks: auto_embed_entry/auto_embed_qa
                            now run in daemon threads so embedding failures never block
                            Nexus writes or health checks
    v1.56.0 [2026-03-26] — Agent registry access check before heuristic fallback
    v1.55.0 [2026-03-26] — Re-raise PermissionError in all governance-guarded methods (RBAC enforcement)
    v1.53.0 [2026-03-26] — Added filesystem/oracle/scheduler/training to trusted actors
    v1.49.5 [2026-03-22] — Per-request timeout override, structured logging
    v0.50a  [2026-03-15] — Session tracking, rules engine, prompt management, batch ops

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

from engine.port_registry import get_service_url

logger = logging.getLogger(__name__)

_DEFAULT_URL = get_service_url("nexus")


def _resolve_governance_actor(agent_id: str = "", created_by: str = "") -> str:
    """Resolve the effective actor used for client-side governance checks."""
    if agent_id:
        return agent_id

    created_by_normalized = (created_by or "").strip().lower()
    # v1.53.0 [2026-03-26] — Added filesystem, oracle, scheduler, training actors
    trusted_prefixes = (
        "copilot",
        "nexus",
        "session",
        "research",
        "content",
        "workflow",
        "benchmark",
        "api",
        "system",
        "filesystem",
        "oracle",
        "scheduler",
        "training",
    )
    trusted_suffixes = (
        "_workflow",
        "_sync",
        "_logger",
        "_bridge",
        "_pipeline",
        "_distiller",
        "_generator",
    )

    if not created_by_normalized:
        return "copilot"
    if created_by_normalized == "cosysim":
        return "copilot"
    if created_by_normalized.startswith(trusted_prefixes):
        return "copilot"
    if created_by_normalized.endswith(trusted_suffixes):
        return "copilot"
    return created_by_normalized

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

    # v1.56.0 [2026-03-26] — Check agent access via Nexus registry before heuristic
    # CONNECTS: Nexus agent_registry API, GovernanceManager
    # CALLED BY: _check_governance
    def _check_access_registry(self, agent_id: str, operation: str) -> Optional[bool]:
        """Check agent access via Nexus agent_registry. Falls back to heuristic.

        Queries the agent_registry for the agent's allowed_operations.
        Returns True/False if a definitive answer is found, or None to
        signal that the caller should fall back to the heuristic path.

        Args:
            agent_id: Agent identifier to look up.
            operation: Operation to check (read/write/delete/admin).

        Returns:
            True if allowed, False if denied, None if registry unavailable.
        """
        try:
            if self.is_available(timeout=2):
                resp = self._get(f"/api/agents/{agent_id}")
                if resp.get("ok") and resp.get("data", {}).get("agent_id"):
                    data = resp["data"]
                    raw_ops = data.get("allowed_operations", "")
                    if raw_ops:
                        allowed_ops = json.loads(raw_ops) if isinstance(raw_ops, str) else raw_ops
                        if isinstance(allowed_ops, list) and allowed_ops:
                            return operation in allowed_ops
                    # Agent exists but no stored ops — resolve from type
                    agent_type = data.get("agent_type", "")
                    if agent_type:
                        from engine.nexus.governance_rules import AGENT_TYPES
                        type_def = AGENT_TYPES.get(agent_type)
                        if type_def:
                            return operation in type_def.get("ops", [])
        except Exception:
            pass
        return None  # None = use heuristic fallback

    def _check_governance(
        self,
        operation: str,
        agent_id: str = "",
        created_by: str = "",
    ) -> str:
        """Resolve actor identity and enforce mutation permissions.

        v1.56.0: Checks the Nexus agent_registry first for a definitive
        allow/deny.  Falls back to the GovernanceManager heuristic when
        the registry is unavailable or the agent is not registered.
        """
        from engine.nexus.governance_rules import get_governance_manager

        actor = _resolve_governance_actor(agent_id=agent_id, created_by=created_by)

        # v1.56.0 — Try registry-backed access check first
        registry_result = self._check_access_registry(actor, operation)
        if registry_result is not None:
            if not registry_result:
                logger.warning(
                    "[NexusClient] Registry denied (operation=%s, actor=%s)",
                    operation,
                    actor,
                )
                raise PermissionError(f"Agent '{actor}' is not permitted to perform '{operation}'")
            return actor

        # Heuristic fallback via GovernanceManager
        mgr = get_governance_manager()
        if not mgr.check_permissions(actor, operation):
            # v1.49.3 [2026-03-22] — Structured logging context
            logger.warning(
                "[NexusClient] Governance denied (operation=%s, actor=%s)",
                operation,
                actor,
            )
            raise PermissionError(f"Agent '{actor}' is not permitted to perform '{operation}'")
        return actor

    def _normalize_entry_payload(
        self,
        title: str,
        content: str,
        content_type: str,
        category: str,
        tags: list | None,
        created_by: str,
        namespace: str = "",
    ) -> dict:
        """Normalize a knowledge-entry payload through namespace governance."""
        from engine.nexus.models import NexusEntryCreate
        from engine.nexus.nexus_namespaces import enforce_namespace

        normalized = enforce_namespace(
            title=title,
            content=content,
            content_type=content_type,
            category=category,
            tags=tags or [],
            namespace=namespace or None,
        )
        if normalized.get("errors"):
            logger.warning(
                "[NexusClient] Entry governance rejected (operation=normalize_entry, title=%s): %s",
                title[:80],
                "; ".join(normalized["errors"]),
            )
            raise ValueError("; ".join(normalized["errors"]))
        for warning in normalized.get("warnings", []):
            logger.debug("Nexus entry governance advisory: %s", warning)

        validated = NexusEntryCreate(
            title=normalized["title"],
            content=normalized["content"],
            content_type=normalized["content_type"],
            category=normalized["category"],
            tags=normalized["tags"],
            created_by=created_by,
        )
        return validated.model_dump()

    def _normalize_namespace_tags(
        self,
        category: str,
        tags: list | None,
        namespace: str = "",
    ) -> list:
        """Normalize namespace tags for non-entry payloads."""
        from engine.nexus.nexus_namespaces import normalize_namespace_tags

        normalized = normalize_namespace_tags(
            category=category,
            tags=tags or [],
            namespace=namespace or None,
        )
        if normalized.get("errors"):
            logger.warning(
                "[NexusClient] Namespace normalization rejected (operation=normalize_tags, category=%s): %s",
                category,
                "; ".join(normalized["errors"]),
            )
            raise ValueError("; ".join(normalized["errors"]))
        return normalized["tags"]

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
                  created_by: str = "cosysim", agent_id: str = "",
                  namespace: str = "", **kwargs) -> Optional[str]:
        try:
            self._check_governance("write", agent_id=agent_id, created_by=created_by)
            payload = self._normalize_entry_payload(
                title=title,
                content=content,
                content_type=content_type,
                category=category,
                tags=tags,
                created_by=created_by,
                namespace=namespace,
            )
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Entry validation failed (operation=add_entry): %s", exc)
            return None
        result = self._post("/api/entries", payload)
        entry_id = result.get("data", {}).get("id") if result.get("ok") else None
        if entry_id:
            # v1.57.1 [2026-03-26] — Non-blocking embed: run in daemon thread so
            # embedding failures never block the Nexus write path or health checks
            def _bg_embed() -> None:
                try:
                    from engine.nexus.embedding_hooks import auto_embed_entry
                    auto_embed_entry(entry_id, content, content_type, category, tags)
                except Exception as exc:
                    logger.debug("[NexusClient] Background embed failed for %s: %s", entry_id, exc)
            t = threading.Thread(target=_bg_embed, name=f"embed-{entry_id[:8]}", daemon=True)
            t.start()
        return entry_id
    
    def get_entry(self, entry_id: str) -> Optional[NexusEntry]:
        result = self._get(f"/api/entries/{entry_id}")
        data = result.get("data") if result.get("ok") else None
        return self._parse_entry(data) if data else None
    
    def update_entry(self, entry_id: str, agent_id: str = "", namespace: str = "", **fields) -> bool:
        try:
            current = self.get_entry(entry_id)
            created_by = fields.get(
                "created_by",
                current.get("created_by", "") if current else "",
            )
            self._check_governance("write", agent_id=agent_id, created_by=created_by)

            relevant = {"title", "content", "content_type", "category", "tags"}
            if namespace or any(key in fields for key in relevant):
                current_payload = current or {}
                normalized = self._normalize_entry_payload(
                    title=fields.get("title", current_payload.get("title", "")),
                    content=fields.get("content", current_payload.get("content", "")),
                    content_type=fields.get("content_type", current_payload.get("content_type", "note")),
                    category=fields.get("category", current_payload.get("category", "")),
                    tags=fields.get("tags", current_payload.get("tags", [])),
                    created_by=created_by or current_payload.get("created_by", "cosysim"),
                    namespace=namespace,
                )
                if "title" in fields:
                    fields["title"] = normalized["title"]
                if "content" in fields:
                    fields["content"] = normalized["content"]
                if "content_type" in fields:
                    fields["content_type"] = normalized["content_type"]
                if "category" in fields:
                    fields["category"] = normalized["category"]
                fields["tags"] = normalized["tags"]
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Update entry governance failed (operation=update_entry): %s", exc)
            return False
        result = self._put(f"/api/entries/{entry_id}", fields)
        return result.get("ok", False)
    
    def delete_entry(self, entry_id: str, agent_id: str = "") -> bool:
        try:
            current = self.get_entry(entry_id)
            created_by = current.get("created_by", "") if current else ""
            self._check_governance("delete", agent_id=agent_id, created_by=created_by)
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Delete entry governance failed (operation=delete_entry): %s", exc)
            return False
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
        try:
            self._check_governance("write", agent_id=agent_id, created_by=agent_id)
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Log session governance failed (operation=log_session): %s", exc)
            return None
        payload = {
            "project": project, "repo": repo,
            "branch": branch, "agent_id": agent_id,
        }
        if session_id:
            payload["id"] = session_id
        result = self._post("/api/sessions", payload)
        return result.get("data", {}).get("id") if result.get("ok") else None

    def update_session(self, session_id: str, agent_id: str = "copilot", **fields) -> bool:
        """Update session (summary, commits, files_changed, status, etc.)."""
        try:
            self._check_governance("write", agent_id=agent_id, created_by=agent_id)
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Update session governance failed (operation=update_session): %s", exc)
            return False
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
                 priority: int = 50, active: bool = True,
                 agent_id: str = "copilot") -> Optional[str]:
        """Create a new rule. Returns rule ID."""
        try:
            self._check_governance("admin", agent_id=agent_id, created_by=agent_id)
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Add rule governance failed (operation=add_rule): %s", exc)
            return None
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

    def batch_add(self, entries: List[Dict], agent_id: str = "copilot") -> List[str]:
        """Add multiple entries in one request. Returns list of IDs."""
        normalized_entries: List[Dict[str, Any]] = []
        for entry in entries:
            created_by = entry.get("created_by", "cosysim")
            effective_agent = entry.get("agent_id", agent_id)
            try:
                self._check_governance("write", agent_id=effective_agent, created_by=created_by)
                normalized_entries.append(
                    self._normalize_entry_payload(
                        title=entry.get("title", ""),
                        content=entry.get("content", ""),
                        content_type=entry.get("content_type", "note"),
                        category=entry.get("category", ""),
                        tags=entry.get("tags", []),
                        created_by=created_by,
                        namespace=entry.get("namespace", ""),
                    )
                )
            except PermissionError:
                raise  # v1.55.0 — Don't swallow RBAC violations
            except Exception as exc:
                logger.warning("[NexusClient] Skipping batch entry due to governance failure (operation=batch_add): %s", exc)
        if not normalized_entries:
            return []
        result = self._post("/api/batch", {"entries": normalized_entries})
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
    
    def is_available(self, timeout: float = 5.0) -> bool:
        """Check if Nexus KMS is reachable and healthy.

        Args:
            timeout: Health check timeout in seconds (default 5s, not 30s).
        """
        try:
            # v1.49.5 [2026-03-22] — Short timeout for health checks + logging on failure
            result = self._get("/api/health", timeout=timeout)
            return result.get("ok", False)
        except Exception as exc:
            logger.warning("[NexusClient] Health check failed (operation=health_check): %s", exc)
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
               quality_score: float = 0.5, agent_id: str = "",
               namespace: str = "") -> Optional[str]:
        """Store a Q&A pair."""
        try:
            self._check_governance("write", agent_id=agent_id, created_by=agent_id)
            normalized_tags = self._normalize_namespace_tags(
                category=category,
                tags=tags,
                namespace=namespace,
            )
        except PermissionError:
            raise  # v1.55.0 — Don't swallow RBAC violations
        except Exception as exc:
            logger.warning("[NexusClient] Add Q&A governance failed (operation=add_qa): %s", exc)
            return None
        result = self._post("/api/qa", {
            "question": question, "answer": answer,
            "category": category, "tags": normalized_tags,
            "quality_score": quality_score,
        })
        qa_id = result.get("data", {}).get("id") if result.get("ok") else None
        if qa_id:
            # v1.57.1 [2026-03-26] — Non-blocking embed: run in daemon thread so
            # embedding failures never block the Nexus write path or health checks
            def _bg_embed_qa() -> None:
                try:
                    from engine.nexus.embedding_hooks import auto_embed_qa
                    auto_embed_qa(qa_id, question, answer, category)
                except Exception as exc:
                    logger.debug("[NexusClient] Background Q&A embed failed for %s: %s", qa_id, exc)
            t = threading.Thread(target=_bg_embed_qa, name=f"embed-qa-{qa_id[:8]}", daemon=True)
            t.start()
        return qa_id

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
    
    def _get(self, path: str, timeout: Optional[float] = None) -> dict:
        return self._request("GET", path, timeout=timeout)

    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)
    
    def _put(self, path: str, payload: dict) -> dict:
        return self._request("PUT", path, payload)
    
    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)
    
    def _request(self, method: str, path: str, payload: dict = None, timeout: Optional[float] = None) -> dict:
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
                # v1.49.5 [2026-03-22] — Support per-request timeout override
                with urllib.request.urlopen(req, timeout=timeout or self._timeout) as resp:
                    return json.loads(resp.read().decode())
            except Exception as exc:
                last_err = exc
                if attempt < self._max_retries:
                    time.sleep(0.5 * attempt)  # exponential backoff
                    continue
                # v1.49.5 [2026-03-22] — Structured logging with operation context
                logger.warning(
                    "[NexusClient] %s %s failed after %d attempt(s) (operation=request): %s",
                    method, path, attempt, exc,
                )
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
                        logger.debug("Config unavailable for nexus.base_url, using default")
                        base_url = _DEFAULT_URL
                _client = NexusClient(base_url)
    return _client
