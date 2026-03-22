"""Nexus Control Panel — Full-featured knowledge management dashboard.

Provides real-time monitoring, Librarian agent chat, maintenance controls,
workflow management, training data curation, and Copilot integration panel.

Version: v1.51.0 [2026-03-22]

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene (unified base class)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request

from engine.config import get_config
from engine.scenes.flask_scene import FlaskScene

try:
    from flask_socketio import emit
except ImportError:
    emit = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

SCENE_ID = "nexus_panel"
# v1.49.1 [2026-03-22] — Use port registry instead of hardcoded value
try:
    from engine.port_registry import get_port as _get_port
    DEFAULT_PORT = _get_port("nexus_panel", 5570)
except Exception:
    DEFAULT_PORT = 5570

_MODULE_METADATA = {
    "name": "nexus_panel",
    "display_name": "NEXUS CONTROL PANEL",
    "port": DEFAULT_PORT,
    "title": "Nexus Control Panel",
    "description": "Knowledge management dashboard with Librarian AI assistant",
    "genre": "management",
    "type": "admin",
    "max_characters": 1,
    "features": [
        "real-time monitoring",
        "librarian agent",
        "knowledge explorer",
        "maintenance controls",
        "workflow management",
        "training data curation",
        "copilot integration",
        "activity feed",
    ],
}


# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class NexusPanelScene(FlaskScene):
    """Nexus knowledge management control panel."""

    SCENE_METADATA = _MODULE_METADATA

    # v1.51.0 [2026-03-22] — Migrated to FlaskScene
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        cfg = get_config()
        port = cfg.get(f"scenes.{SCENE_ID}.port", port)
        super().__init__(host=host, port=port)

        self.app.config["SECRET_KEY"] = cfg.get("flask.secret_key", "nexus-panel-key")

        # Activity feed — ring buffer of recent events
        self._activity: deque = deque(maxlen=500)
        self._activity_lock = threading.Lock()

        # Stats counters
        self._stats: Dict[str, int] = {
            "api_calls": 0,
            "searches": 0,
            "entries_added": 0,
            "qa_answered": 0,
            "maintenance_runs": 0,
            "librarian_chats": 0,
            "tokens_saved_est": 0,
        }

        # Guided distillation sessions
        self._guided_sessions: Dict[str, dict] = {}

        # Background ingest job tracker
        self._ingest_jobs: Dict[str, dict] = {}

        self._register_routes()
        logger.info("NexusPanelScene initialised on port %s", port)

    # ── Activity Tracking ───────────────────────────────────────────────

    def _log_activity(self, action: str, detail: str = "",
                      source: str = "system", level: str = "info") -> None:
        """Append an event to the activity feed."""
        event = {
            "ts": datetime.now().isoformat(),
            "action": action,
            "detail": detail[:200],
            "source": source,
            "level": level,
        }
        with self._activity_lock:
            self._activity.appendleft(event)
        self._stats["api_calls"] += 1

    def _get_activity(self, limit: int = 50) -> List[Dict]:
        with self._activity_lock:
            return list(self._activity)[:limit]

    def _emit_progress(self, event: str, data: Dict[str, Any]) -> None:
        """Emit a Socket.IO progress event if available."""
        if self.socketio is not None:
            try:
                self.socketio.emit(event, data)
            except Exception:
                pass

    # ── Nexus Proxy Helpers ─────────────────────────────────────────────

    def _get_client(self):
        """Get NexusClient, lazy import."""
        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client()
        except Exception:
            return None

    def _nlm_proxy_url(self) -> str:
        """Return the configured NLM proxy base URL."""
        return get_config().get("notebooklm.proxy_url", "http://localhost:8800")

    def _nlm_proxy_get(self, path: str) -> Optional[Any]:
        """GET request to NLM proxy. Returns parsed JSON or None on error."""
        import urllib.request
        try:
            url = f"{self._nlm_proxy_url()}{path}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("NLM proxy GET %s failed: %s", path, exc)
            return None

    # ── Routes ──────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template("nexus_panel.html", scene=SCENE_METADATA)

        @app.route("/health")
        def health():
            return jsonify({"status": "ok", "scene": SCENE_ID})

        # ── Dashboard Stats ─────────────────────────────────────────

        @app.route("/api/stats")
        def api_stats():
            client = self._get_client()
            nexus_stats = {}
            if client and client.is_available():
                try:
                    nexus_stats = client.stats()
                except Exception as exc:
                    nexus_stats = {"error": str(exc)}
            # Include query router stats
            router_stats = {}
            try:
                from engine.nexus.query_router import get_query_router
                router_stats = get_query_router().stats.to_dict()
            except Exception:
                pass
            self._log_activity("stats_check", source="dashboard")
            return jsonify({
                "panel_stats": self._stats,
                "nexus_stats": nexus_stats,
                "router_stats": router_stats,
                "nexus_available": bool(client and client.is_available()),
            })

        @app.route("/api/activity")
        def api_activity():
            limit = request.args.get("limit", 50, type=int)
            return jsonify(self._get_activity(limit))

        # ── Knowledge Explorer ──────────────────────────────────────

        @app.route("/api/smart_query")
        def api_smart_query():
            question = request.args.get("q", "")
            if not question:
                return jsonify({"error": "No question provided"}), 400
            try:
                from engine.nexus.query_router import get_query_router
                router = get_query_router()
                result = router.query(
                    question,
                    use_llm=request.args.get("llm", "true").lower() == "true",
                    category=request.args.get("category", ""),
                    source_hint="nexus_panel",
                )
                self._stats["searches"] += 1
                self._log_activity(
                    "smart_query",
                    f"q={question[:40]} → {result.source} (conf={result.confidence:.2f})",
                    "explorer",
                )
                return jsonify(result.to_dict())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/search")
        def api_search():
            query = request.args.get("q", "")
            limit = request.args.get("limit", 20, type=int)
            if not query:
                return jsonify([])
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                results = client.search(query, limit=limit)
                self._stats["searches"] += 1
                self._log_activity("search", f"q={query} ({len(results)} results)", "explorer")
                return jsonify(results)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/entries")
        def api_entries():
            content_type = request.args.get("type", "")
            category = request.args.get("category", "")
            limit = request.args.get("limit", 50, type=int)
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                entries = client.list_entries(
                    content_type=content_type, category=category, limit=limit
                )
                return jsonify(entries)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/entry/<entry_id>")
        def api_entry(entry_id: str):
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                entry = client.get_entry(entry_id)
                return jsonify(entry)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/entry/<entry_id>", methods=["DELETE"])
        def api_delete_entry(entry_id: str):
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                client.delete_entry(entry_id)
                self._log_activity("delete_entry", entry_id, "explorer")
                return jsonify({"status": "deleted"})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/entry", methods=["POST"])
        def api_add_entry():
            data = request.get_json(force=True)
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.add_entry(
                    title=data.get("title", ""),
                    content=data.get("content", ""),
                    content_type=data.get("content_type", "note"),
                    category=data.get("category", ""),
                    tags=data.get("tags", []),
                )
                self._stats["entries_added"] += 1
                self._log_activity("add_entry", data.get("title", "")[:60], "explorer")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Q&A ─────────────────────────────────────────────────────

        @app.route("/api/ask", methods=["POST"])
        def api_ask():
            data = request.get_json(force=True)
            question = data.get("question", "")
            if not question:
                return jsonify({"error": "No question provided"}), 400
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.ask(question, depth=data.get("depth", "auto"))
                self._stats["qa_answered"] += 1
                self._stats["tokens_saved_est"] += 500
                self._log_activity("ask", question[:80], "librarian")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/qa", methods=["GET"])
        def api_list_qa():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                qa = client.find_qa("", limit=50)
                return jsonify(qa)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Maintenance ─────────────────────────────────────────────

        @app.route("/api/maintain/<action>", methods=["POST"])
        def api_maintain(action: str):
            try:
                from engine.nexus.self_maintenance import (
                    nexus_health_report,
                    nexus_merge_duplicates,
                    nexus_compact_sessions,
                    nexus_score_entries,
                    nexus_full_maintenance,
                )
                actions = {
                    "health": nexus_health_report,
                    "dedup": lambda: nexus_merge_duplicates(dry_run=True),
                    "dedup-apply": lambda: nexus_merge_duplicates(dry_run=False),
                    "compact": nexus_compact_sessions,
                    "score": nexus_score_entries,
                    "full": lambda: nexus_full_maintenance(dry_run=True),
                    "full-apply": lambda: nexus_full_maintenance(dry_run=False),
                }
                if action not in actions:
                    return jsonify({"error": f"Unknown action: {action}"}), 400
                result = actions[action]()
                self._stats["maintenance_runs"] += 1
                self._log_activity("maintenance", action, "maintenance")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Research ────────────────────────────────────────────────

        @app.route("/api/research", methods=["POST"])
        def api_research():
            data = request.get_json(force=True)
            question = data.get("question", "")
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.research(question)
                self._log_activity("research_start", question[:80], "research")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/research/<research_id>/converse", methods=["POST"])
        def api_converse(research_id: str):
            data = request.get_json(force=True)
            message = data.get("message", "")
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.converse(research_id, message)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/research/<research_id>/finish", methods=["POST"])
        def api_finish_research(research_id: str):
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.finish_research(research_id)
                self._log_activity("research_finish", research_id, "research")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/research/list")
        def api_list_research():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.list_research(limit=20)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Prompts & Rules ─────────────────────────────────────────

        @app.route("/api/prompts")
        def api_prompts():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                category = request.args.get("category", "")
                return jsonify(client.get_prompts(category=category))
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/prompts", methods=["POST"])
        def api_store_prompt():
            data = request.get_json(force=True)
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.store_prompt(
                    name=data.get("name", ""),
                    content=data.get("content", ""),
                    category=data.get("category", "system"),
                    version=data.get("version", "1"),
                    tags=data.get("tags", []),
                )
                self._log_activity("store_prompt", data.get("name", ""), "prompts")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/rules")
        def api_rules():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                scope = request.args.get("scope", "")
                return jsonify(client.get_rules(scope=scope))
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Sessions ────────────────────────────────────────────────

        @app.route("/api/sessions")
        def api_sessions():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                return jsonify(client.list_sessions(limit=30))
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── NLM / NotebookLM ───────────────────────────────────────

        @app.route("/api/nlm/status")
        def api_nlm_status():
            """Check NLM service availability and readiness."""
            status: Dict[str, Any] = {"nlm_available": False, "proxy_url": "", "tiers": {}}
            try:
                cfg = get_config()
                enabled = cfg.get("notebooklm.enabled", False)
                proxy_url = cfg.get("notebooklm.proxy_url", "http://localhost:8800")
                status["enabled"] = enabled
                status["proxy_url"] = proxy_url

                # Check Tier 1: Q&A cache
                status["tiers"]["cache"] = {"available": True, "label": "Q&A Cache"}

                # Check Tier 2: FTS search
                status["tiers"]["fts"] = {"available": True, "label": "Full-Text Search"}

                # Check Tier 3: NLM proxy
                if enabled:
                    try:
                        import urllib.request
                        req = urllib.request.Request(f"{proxy_url}/health", method="GET")
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            status["tiers"]["nlm"] = {"available": resp.status == 200, "label": "NotebookLM"}
                            status["nlm_available"] = True
                    except Exception:
                        status["tiers"]["nlm"] = {"available": False, "label": "NotebookLM (offline)"}
                else:
                    status["tiers"]["nlm"] = {"available": False, "label": "NotebookLM (disabled)"}

                # v1.43.1 [2026-03-21] — Check Tier 4 via unified client
                try:
                    from engine.lmstudio.chat import is_ready
                    lms_ok = is_ready()
                    status["tiers"]["llm"] = {"available": lms_ok, "label": "LMStudio LLM" if lms_ok else "LMStudio (offline)"}
                except Exception:
                    status["tiers"]["llm"] = {"available": False, "label": "LMStudio (offline)"}

            except Exception as exc:
                logger.warning("NLM status check failed: %s", exc)
                status["error"] = str(exc)

            return jsonify(status)

        @app.route("/api/nlm/notebooks")
        def api_nlm_notebooks():
            """List live NLM notebooks from the proxy (with Nexus fallback)."""
            # Try live proxy first
            data = self._nlm_proxy_get("/notebooks")
            if data and not data.get("error"):
                return jsonify(data)
            # Fallback to Nexus client stored metadata
            client = self._get_client()
            if not client:
                return jsonify({"error": "NLM proxy offline and Nexus unavailable", "notebooks": []}), 503
            try:
                return jsonify(client.nlm_list_notebooks())
            except Exception as exc:
                return jsonify({"error": str(exc), "notebooks": []}), 500

        # ── Copilot Panel ───────────────────────────────────────────

        @app.route("/api/copilot/skills")
        def api_copilot_skills():
            """List all registered MCP skills."""
            try:
                from engine.skills.registry import SkillRegistry
                registry = SkillRegistry()
                packs = {}
                for name, skill_obj in registry._skills.items():
                    pack = getattr(skill_obj, "pack", "unknown")
                    if pack not in packs:
                        packs[pack] = []
                    packs[pack].append({
                        "name": name,
                        "description": getattr(skill_obj, "description", ""),
                        "category": str(getattr(skill_obj, "category", "")),
                        "cooldown": getattr(skill_obj, "cooldown", 0),
                        "tags": getattr(skill_obj, "tags", []),
                    })
                return jsonify(packs)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/copilot/config")
        def api_copilot_config():
            """Return Copilot-relevant config sections."""
            cfg = get_config()
            return jsonify({
                "nexus": cfg.get("nexus", {}),
                "lmstudio": {
                    "host": cfg.get("lmstudio.host", "localhost"),
                    "port": cfg.get("lmstudio.port", 1234),
                    "load_mode": cfg.get("lmstudio.load_mode", "jit"),
                },
                "scenes_registered": cfg.get("scenes", {}),
            })

        # ── Librarian Chat ──────────────────────────────────────────

        @app.route("/api/librarian/chat", methods=["POST"])
        def api_librarian_chat():
            """Chat with the Librarian — an AI assistant backed by Nexus knowledge."""
            data = request.get_json(force=True)
            message = data.get("message", "")
            if not message:
                return jsonify({"error": "No message provided"}), 400

            self._stats["librarian_chats"] += 1
            self._log_activity("librarian_chat", message[:80], "librarian")

            # The Librarian uses NLM router (4-tier) when available, else Nexus Q&A
            client = self._get_client()
            if not client or not client.is_available():
                return jsonify({
                    "response": "I'm sorry, I can't reach the Nexus knowledge base right now. "
                                "Please check that the Nexus service is running on port 8700.",
                    "source": "offline",
                })

            # Try NLM router first (tier 1: cache → tier 2: FTS → tier 3: NLM → tier 4: LLM)
            try:
                from engine.nexus.nlm_router import get_nlm_router
                router = get_nlm_router()
                result = router.route(message)
                if result and result.get("answer"):
                    self._stats["tokens_saved_est"] += 800 if result.get("source_tier") != "llm" else 0
                    return jsonify({
                        "response": result["answer"],
                        "source": result.get("source_tier", "router"),
                        "source_tier": result.get("source_tier", "router"),
                        "confidence": result.get("confidence", 0.7),
                        "sources": result.get("sources", [])[:5],
                    })
            except Exception as exc:
                logger.debug("NLM router unavailable, falling back to Q&A: %s", exc)

            # Fallback: Nexus Q&A pipeline
            try:
                qa_result = client.ask(message, depth="auto")
                answer = qa_result.get("answer", "")
                source = qa_result.get("source", "unknown")
                confidence = qa_result.get("confidence", 0)
                sources = qa_result.get("sources", [])

                if answer:
                    self._stats["tokens_saved_est"] += 800
                    return jsonify({
                        "response": answer,
                        "source": source,
                        "source_tier": source,
                        "confidence": confidence,
                        "sources": sources[:5],
                    })
            except Exception as exc:
                logger.warning("Librarian Q&A failed: %s", exc)

            # Fallback: search and synthesise
            try:
                results = client.search(message, limit=5)
                if results:
                    snippets = []
                    for r in results[:3]:
                        title = r.get("title", "")
                        content = r.get("content", "")[:200]
                        snippets.append(f"**{title}**: {content}")
                    response = (
                        "Here's what I found in the knowledge base:\n\n"
                        + "\n\n".join(snippets)
                    )
                    return jsonify({
                        "response": response,
                        "source": "search",
                        "source_tier": "fts",
                        "confidence": 0.5,
                        "sources": [r.get("title", "") for r in results[:3]],
                    })
            except Exception as exc:
                logger.warning("Librarian search failed: %s", exc)

            return jsonify({
                "response": "I couldn't find relevant information. Try rephrasing your "
                            "question or use the Knowledge Explorer to browse entries directly.",
                "source": "none",
                "source_tier": "none",
                "confidence": 0,
            })

        # ── Plugins ─────────────────────────────────────────────────

        @app.route("/api/plugins")
        def api_plugins():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                return jsonify(client.list_plugins())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── YouTube Import ──────────────────────────────────────────

        @app.route("/api/youtube", methods=["POST"])
        def api_youtube():
            data = request.get_json(force=True)
            url = data.get("url", "")
            if not url:
                return jsonify({"error": "No URL provided"}), 400
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.import_youtube(url, category=data.get("category", "youtube"))
                self._log_activity("youtube_import", url[:60], "import")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── URL Management Routes ──────────────────────────────────

        @app.route("/api/urls", methods=["GET"])
        def api_list_urls():
            limit = request.args.get("limit", 50, type=int)
            domain = request.args.get("domain", "")
            try:
                from engine.nexus.url_manager import get_url_manager
                mgr = get_url_manager()
                urls = mgr.list_urls(limit=limit, domain=domain or None)
                return jsonify([u.to_dict() for u in urls])
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/urls", methods=["POST"])
        def api_add_url():
            data = request.get_json(force=True)
            url = data.get("url", "")
            if not url:
                return jsonify({"error": "No URL provided"}), 400
            try:
                from engine.nexus.url_manager import get_url_manager
                mgr = get_url_manager()
                tags = data.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
                scrape = data.get("scrape", False)
                if scrape:
                    result = mgr.process_url(
                        url, title=data.get("title"), tags=tags, added_by="panel")
                else:
                    result = mgr.add_url(
                        url, title=data.get("title"), tags=tags, added_by="panel")
                if result is None:
                    return jsonify({"error": "Failed to add URL"}), 400
                self._log_activity("url_add", url[:60], "url")
                if isinstance(result, dict):
                    return jsonify(result)
                return jsonify({"status": "ok", "entry_id": result})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/urls/scrape", methods=["POST"])
        def api_scrape_url():
            data = request.get_json(force=True)
            url = data.get("url", "")
            if not url:
                return jsonify({"error": "No URL provided"}), 400
            try:
                from engine.nexus.url_manager import get_url_manager
                mgr = get_url_manager()
                result = mgr.process_url(url, added_by="panel")
                if result is None:
                    return jsonify({"error": "Scrape failed"}), 400
                self._log_activity("url_scrape", url[:60], "url")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/urls/stats")
        def api_url_stats():
            try:
                from engine.nexus.url_manager import get_url_manager
                mgr = get_url_manager()
                return jsonify(mgr.stats)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── NLM / Ingestion Routes ─────────────────────────────────

        @app.route("/api/ingest/har", methods=["POST"])
        def api_ingest_har():
            """Upload and preview a HAR file."""
            if "file" not in request.files:
                return jsonify({"error": "No file uploaded"}), 400
            f = request.files["file"]
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".har", delete=False) as tmp:
                f.save(tmp.name)
                tmp_path = tmp.name
            try:
                from engine.nexus.har_extractor import HARExtractor
                ext = HARExtractor()
                notebooks = ext.extract(tmp_path)
                return jsonify({
                    "notebooks": [nb.to_dict() for nb in notebooks],
                    "count": len(notebooks),
                    "tmp_path": tmp_path,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/ingest/har/commit", methods=["POST"])
        def api_ingest_har_commit():
            """Commit HAR data to Nexus (runs in background thread)."""
            data = request.get_json(force=True)
            tmp_path = data.get("tmp_path", "")
            items = data.get("items", ["sources", "documents", "notes", "conversations"])
            job_id = f"har_ingest_{int(time.time())}"
            self._ingest_jobs[job_id] = {"status": "running", "results": None, "error": None}

            def _run():
                try:
                    from engine.nexus.har_extractor import HARExtractor
                    ext = HARExtractor()
                    notebooks = ext.extract(tmp_path)
                    client = self._get_client()
                    if not client:
                        self._ingest_jobs[job_id] = {"status": "error", "results": None, "error": "Nexus unavailable"}
                        return
                    results = []
                    for nb in notebooks:
                        r = ext.ingest_to_nexus(nb, client, items=items)
                        total = len(nb.sources) + len(nb.documents) + len(nb.notes) + len(nb.conversations)
                        results.append({"name": nb.notebook_name, "stored": r.entries_created, "total": total})
                    self._log_activity("har_ingest", f"{len(notebooks)} notebooks", "ingest")
                    self._ingest_jobs[job_id] = {"status": "done", "results": results, "error": None}
                except Exception as exc:
                    self._ingest_jobs[job_id] = {"status": "error", "results": None, "error": str(exc)}

            threading.Thread(target=_run, daemon=True).start()
            return jsonify({"job_id": job_id, "status": "running"})

        @app.route("/api/ingest/har/status/<job_id>")
        def api_ingest_har_status(job_id: str):
            """Poll HAR ingestion job status."""
            job = self._ingest_jobs.get(job_id)
            if not job:
                return jsonify({"error": "Job not found"}), 404
            return jsonify(job)

        @app.route("/api/ingest/codebase", methods=["POST"])
        def api_ingest_codebase():
            """Create an NLM notebook from source files."""
            data = request.get_json(force=True)
            files = data.get("files", [])
            name = data.get("name", "Codebase Analysis")
            if not files:
                return jsonify({"error": "No files provided"}), 400
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                engine = get_nlm_engine()
                result = engine.create_from_files(files, name)
                self._log_activity("codebase_notebook", name, "create")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/notebook", methods=["POST"])
        def api_nlm_create_notebook():
            """Create a new NLM notebook."""
            data = request.get_json(force=True)
            name = data.get("name", "")
            sources = data.get("sources")
            if not name:
                return jsonify({"error": "Name required"}), 400
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                result = get_nlm_engine().create_notebook(name, sources=sources)
                self._log_activity("nlm_create", name, "create")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/notebook/<nb_id>", methods=["DELETE"])
        def api_nlm_delete_notebook(nb_id: str):
            """Delete an NLM notebook."""
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                result = get_nlm_engine().delete_notebook(nb_id)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/notebook/<nb_id>/sources", methods=["POST"])
        def api_nlm_add_source(nb_id: str):
            """Add a source to an NLM notebook."""
            data = request.get_json(force=True)
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                result = get_nlm_engine().add_source(
                    nb_id, data.get("type", "text"), data.get("value", "")
                )
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/notebook/<nb_id>/sources", methods=["GET"])
        def api_nlm_get_sources(nb_id: str):
            """Get sources for an NLM notebook from live proxy."""
            data = self._nlm_proxy_get(f"/notebooks/{nb_id}/sources")
            if data is None:
                return jsonify({"error": "NLM proxy offline or notebook not found"}), 502
            return jsonify(data)

        @app.route("/api/nlm/notebook/<nb_id>/history")
        def api_nlm_notebook_history(nb_id: str):
            """Get chat history for an NLM notebook from live proxy."""
            data = self._nlm_proxy_get(f"/notebooks/{nb_id}/history")
            if data is None:
                return jsonify({"error": "NLM proxy offline or history unavailable"}), 502
            return jsonify(data)

        @app.route("/api/nlm/ask", methods=["POST"])
        def api_nlm_ask():
            """Ask NLM via the 4-tier router."""
            data = request.get_json(force=True)
            question = data.get("question", "")
            nb_id = data.get("notebook_id", "")
            if not question:
                return jsonify({"error": "Question required"}), 400
            try:
                from engine.nexus.nlm_router import get_nlm_router
                result = get_nlm_router().route(question, notebook_id=nb_id)
                self._log_activity("nlm_ask", question[:60], "query")
                return jsonify(result.to_dict())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/ask-batch", methods=["POST"])
        def api_nlm_ask_batch():
            """Batch-ask questions via NLM router."""
            data = request.get_json(force=True)
            questions = data.get("questions", [])
            nb_id = data.get("notebook_id", "")
            if not questions:
                return jsonify({"error": "Questions required"}), 400
            try:
                from engine.nexus.nlm_router import get_nlm_router
                router = get_nlm_router()
                results = []
                for i, q in enumerate(questions):
                    r = router.route(q, notebook_id=nb_id)
                    results.append(r.to_dict())
                    self._emit_progress("batch_progress", {
                        "current": i + 1,
                        "total": len(questions),
                        "tier": r.source_tier,
                    })
                self._log_activity("nlm_batch", f"{len(questions)} questions", "query")
                return jsonify({"results": results, "count": len(results)})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/distill", methods=["POST"])
        def api_nlm_distill():
            """Distill Q&A pairs from a notebook."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            topic = data.get("topic", "")
            count = data.get("count", 20)
            if not nb_id:
                return jsonify({"error": "notebook_id required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                forge = get_knowledge_forge()
                topics = [topic] if topic else None
                result = forge.distill(nb_id, topics=topics, count=count)
                self._log_activity("nlm_distill", f"{len(result.qa_pairs)} pairs", "forge")
                return jsonify({
                    "success": result.success,
                    "qa_count": len(result.qa_pairs),
                    "qa_pairs": [p.to_dict() for p in result.qa_pairs],
                    "nexus_ids": result.nexus_ids,
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/decompose", methods=["POST"])
        def api_nlm_decompose():
            """Decompose a plan into implementation steps."""
            data = request.get_json(force=True)
            plan = data.get("plan", "")
            nb_id = data.get("notebook_id", "")
            if not plan:
                return jsonify({"error": "Plan text required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                result = get_knowledge_forge().decompose(plan, notebook_id=nb_id)
                return jsonify({
                    "success": result.success,
                    "steps": result.steps,
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/analyze", methods=["POST"])
        def api_nlm_analyze():
            """Analyze source files via NLM."""
            data = request.get_json(force=True)
            files = data.get("files", [])
            questions = data.get("questions")
            if not files:
                return jsonify({"error": "Files required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                result = get_knowledge_forge().analyze(files, questions=questions)
                return jsonify({
                    "success": result.success,
                    "notebook_id": result.notebook_id,
                    "insights": [p.to_dict() for p in result.qa_pairs],
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/solve", methods=["POST"])
        def api_nlm_solve():
            """Solve a problem via NLM."""
            data = request.get_json(force=True)
            question = data.get("question", "")
            if not question:
                return jsonify({"error": "Question required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                result = get_knowledge_forge().solve(
                    question,
                    context_files=data.get("files"),
                    notebook_id=data.get("notebook_id", ""),
                )
                return jsonify({
                    "success": result.success,
                    "solution": result.qa_pairs[0].to_dict() if result.qa_pairs else None,
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/build-topic", methods=["POST"])
        def api_nlm_build_topic():
            """End-to-end topic knowledge building."""
            data = request.get_json(force=True)
            topic = data.get("topic", "")
            if not topic:
                return jsonify({"error": "Topic required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                result = get_knowledge_forge().build_topic(
                    topic,
                    sources=data.get("sources"),
                    question_count=data.get("count", 30),
                )
                self._log_activity("nlm_build_topic", topic, "forge")
                return jsonify({
                    "success": result.success,
                    "notebook_id": result.notebook_id,
                    "qa_count": len(result.qa_pairs),
                    "nexus_ids": result.nexus_ids,
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/generate", methods=["POST"])
        def api_nlm_generate():
            """Generate a document from a notebook."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            if not nb_id:
                return jsonify({"error": "notebook_id required"}), 400
            try:
                from engine.nexus.knowledge_forge import get_knowledge_forge
                result = get_knowledge_forge().generate_doc(
                    nb_id,
                    doc_type=data.get("type", "study_guide"),
                    instructions=data.get("instructions", ""),
                )
                return jsonify({
                    "success": result.success,
                    "documents": result.documents,
                    "errors": result.errors,
                    "duration": result.duration_seconds,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/router/stats")
        def api_nlm_router_stats():
            """Get NLM router savings metrics."""
            try:
                from engine.nexus.nlm_router import get_nlm_router
                return jsonify(get_nlm_router().savings_report())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/engine/stats")
        def api_nlm_engine_stats():
            """Get NLM engine usage stats."""
            try:
                from engine.nexus.nlm_engine import get_nlm_engine
                return jsonify(get_nlm_engine().status())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Studio Extraction (Quota-Free) ─────────────────────────────────────

        @app.route("/api/nlm/studio/extract-flashcards", methods=["POST"])
        def api_nlm_studio_flashcards():
            """Extract flashcards from a notebook via quota-free Studio tile."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            if not nb_id:
                return jsonify({"error": "notebook_id required"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().extract_flashcards(
                    notebook_id=nb_id,
                    store_in_nexus=data.get("store_in_nexus", False),
                    nexus_category=data.get("nexus_category", "distillation"),
                    nexus_url=get_config().get("nexus.url", "http://localhost:8700"),
                )
                self._log_activity("studio_flashcards",
                                   f"{result.get('count', 0)} cards from {nb_id}", "studio")
                return jsonify(result)
            except Exception as exc:
                logger.exception("extract_flashcards failed")
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/studio/extract-quiz", methods=["POST"])
        def api_nlm_studio_quiz():
            """Extract quiz Q&A from a notebook via quota-free Studio tile."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            if not nb_id:
                return jsonify({"error": "notebook_id required"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().extract_quiz(
                    notebook_id=nb_id,
                    store_in_nexus=data.get("store_in_nexus", False),
                    nexus_category=data.get("nexus_category", "distillation"),
                    nexus_url=get_config().get("nexus.url", "http://localhost:8700"),
                )
                self._log_activity("studio_quiz",
                                   f"{result.get('count', 0)} questions from {nb_id}", "studio")
                return jsonify(result)
            except Exception as exc:
                logger.exception("extract_quiz failed")
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/studio/generate-report", methods=["POST"])
        def api_nlm_studio_report():
            """Generate a Studio report with a custom prompt injection."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            prompt = data.get("prompt", "")
            if not nb_id or not prompt:
                return jsonify({"error": "notebook_id and prompt required"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().generate_report_with_prompt(
                    notebook_id=nb_id,
                    custom_prompt=prompt,
                    content_type=data.get("content_type", "report"),
                )
                self._log_activity("studio_report", prompt[:60], "studio")
                return jsonify(result)
            except Exception as exc:
                logger.exception("generate_report_with_prompt failed")
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/studio/ask-multi", methods=["POST"])
        def api_nlm_studio_ask_multi():
            """Ask multiple questions in a single NLM session thread."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            questions = data.get("questions", [])
            if not nb_id or not questions:
                return jsonify({"error": "notebook_id and questions required"}), 400
            if len(questions) > 10:
                return jsonify({"error": "Maximum 10 questions per session"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().ask_multi(
                    notebook_id=nb_id,
                    questions=questions,
                    session_id=data.get("session_id", ""),
                )
                self._log_activity("ask_multi",
                                   f"{len(questions)} questions on {nb_id}", "query")
                return jsonify(result)
            except Exception as exc:
                logger.exception("ask_multi failed")
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/studio/distill", methods=["POST"])
        def api_nlm_studio_distill():
            """One-shot: flashcards + quiz → parse → store all Q&A in Nexus (quota-free)."""
            data = request.get_json(force=True)
            nb_id = data.get("notebook_id", "")
            if not nb_id:
                return jsonify({"error": "notebook_id required"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().distill_to_nexus(
                    notebook_id=nb_id,
                    nexus_category=data.get("nexus_category", "distillation"),
                    nexus_url=get_config().get("nexus.url", "http://localhost:8700"),
                )
                total = result.get("nexus_count", 0)
                self._log_activity("distill_to_nexus",
                                   f"{total} pairs stored from {nb_id}", "studio")
                self._stats["entries_added"] += total
                return jsonify(result)
            except Exception as exc:
                logger.exception("distill_to_nexus failed")
                return jsonify({"error": str(exc)}), 500

        # ── Quota & Auth ───────────────────────────────────────────────────────

        @app.route("/api/nlm/quota")
        def api_nlm_quota():
            """Get current NLM quota: tier, usage, limits."""
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                return jsonify(get_nlm_node_bridge().get_quota())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/quota/set-tier", methods=["POST"])
        def api_nlm_quota_set_tier():
            """Override quota tier (none/basic/pro/team/enterprise)."""
            data = request.get_json(force=True)
            tier = data.get("tier", "")
            if tier not in ("none", "basic", "pro", "team", "enterprise"):
                return jsonify({"error": "tier must be one of: none, basic, pro, team, enterprise"}), 400
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().set_quota_tier(tier)
                self._log_activity("set_quota_tier", tier, "admin")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/auth/status")
        def api_nlm_auth_status():
            """Get Node server health + auth state."""
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                bridge = get_nlm_node_bridge()
                health = bridge.get_health()
                return jsonify({
                    "server_running": bridge.is_running,
                    "initialized": bridge.is_initialized,
                    **health,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/auth/setup", methods=["POST"])
        def api_nlm_auth_setup():
            """Open browser for interactive NLM auth setup."""
            try:
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                result = get_nlm_node_bridge().setup_auth(show_browser=True)
                self._log_activity("auth_setup", "browser auth triggered", "admin")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/export-nexus", methods=["POST"])
        def api_nlm_export_nexus():
            """Assemble Nexus knowledge entries and upload as a source to an NLM notebook.

            Body params:
                notebook_id: Target notebook ID (null = use configured default or create).
                category: Nexus category to export (null = all).
                limit: Max entries to include (default 200).
            """
            data = request.get_json(force=True)
            nb_id: Optional[str] = data.get("notebook_id") or None
            category: Optional[str] = data.get("category") or None
            limit: int = min(int(data.get("limit", 200)), 2000)

            try:
                # Fetch entries from Nexus
                from engine.nexus.client import get_nexus_client
                client = get_nexus_client()
                if category:
                    entries = client.search(category, limit=limit)
                    if isinstance(entries, dict):
                        entries = entries.get("results", [])
                else:
                    entries = client.list_entries(limit=limit)
                    if isinstance(entries, dict):
                        entries = entries.get("data", [])

                if not entries:
                    return jsonify({"error": "No entries found to export", "ok": False}), 404

                # Assemble as markdown document
                lines: List[str] = [
                    f"# Nexus Knowledge Export",
                    f"Category: {category or 'all'} | Entries: {len(entries)} | "
                    f"Generated: {datetime.now().isoformat()}\n",
                    "---\n",
                ]
                for i, e in enumerate(entries):
                    title = e.get("title", f"Entry {i+1}")
                    content = e.get("content", "")
                    cat = e.get("category", "")
                    content_type = e.get("content_type", "note")
                    lines.append(f"## {title}")
                    lines.append(f"*Category: {cat} | Type: {content_type}*\n")
                    lines.append(content.strip())
                    lines.append("\n---\n")

                assembled = "\n".join(lines)

                # Upload as text source to NLM notebook
                from engine.mcp.nlm_node_bridge import get_nlm_node_bridge
                bridge = get_nlm_node_bridge()

                if not nb_id:
                    nb_id = get_config().get("notebooklm.librarian_notebook_id", "")

                if not nb_id:
                    return jsonify({
                        "error": "No notebook_id provided and no librarian_notebook_id configured",
                        "ok": False,
                    }), 400

                source_title = f"Nexus Export — {category or 'all'} ({len(entries)} entries)"
                result = bridge.add_source(nb_id, source_type="text", source_value=assembled)
                ok = not result.get("error")

                self._log_activity(
                    "nexus_export_to_nlm",
                    f"{len(entries)} entries → notebook {nb_id}",
                    "admin",
                )
                return jsonify({
                    "ok": ok,
                    "notebook_id": nb_id,
                    "entries_count": len(entries),
                    "source_title": source_title,
                    "message": f"Uploaded {len(entries)} entries as text source to {nb_id}",
                    **result,
                })
            except Exception as exc:
                logger.exception("export-nexus failed")
                return jsonify({"error": str(exc), "ok": False}), 500


            """Generate questions for batch asking."""
            data = request.get_json(force=True)
            topic = data.get("topic", "")
            if not topic:
                return jsonify({"error": "Topic required"}), 400
            try:
                from engine.nexus.knowledge_forge import generate_questions
                qs = generate_questions(
                    topic,
                    category=data.get("category", "topic"),
                    count=data.get("count", 10),
                    subject=data.get("subject", topic[:50]),
                )
                return jsonify({"questions": qs, "count": len(qs)})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/entry/<entry_id>", methods=["PUT"])
        def api_update_entry(entry_id: str):
            """Update an existing Nexus entry."""
            data = request.get_json(force=True)
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                result = client.update_entry(entry_id, **data)
                self._log_activity("entry_update", entry_id[:12], "update")
                return jsonify({"success": True, "result": result})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── System Metrics Routes ───────────────────────────────────

        @app.route("/api/metrics/system")
        def api_metrics_system():
            """Current system metrics snapshot (CPU, RAM, GPU, pipeline)."""
            try:
                from training.finetune_local import _collect_system_snapshot
                snap = _collect_system_snapshot()
                return jsonify(snap)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/metrics/inference")
        def api_metrics_inference():
            """Per-model inference stats from InferenceMonitor."""
            try:
                from engine.lmstudio.orchestrator import get_orchestrator
                orch = get_orchestrator()
                if orch.inference_monitor:
                    return jsonify(orch.inference_monitor.get_status())
                return jsonify({"error": "InferenceMonitor not available"}), 503
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/metrics/resources")
        def api_metrics_resources():
            """Resource manager status (VRAM, slots, strategy)."""
            try:
                from engine.lmstudio.resource_manager import get_resource_manager
                rm = get_resource_manager()
                return jsonify(rm.get_status())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/metrics/benchmarks")
        def api_metrics_benchmarks():
            """Operation timings and LLM KPIs."""
            try:
                from engine.logging.benchmark import get_benchmarks, get_llm_kpis
                return jsonify({
                    "operations": get_benchmarks(),
                    "llm_kpis": get_llm_kpis(),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/metrics/pipeline")
        def api_metrics_pipeline():
            """Pipeline summary and recent history."""
            try:
                from engine.observability.metrics_db import get_metrics_db
                db = get_metrics_db()
                seconds = int(request.args.get("seconds", 300))
                return jsonify({
                    "summary": db.get_pipeline_summary(seconds=seconds),
                    "system_history": db.get_system_history(seconds=seconds),
                    "alerts": db.get_recent_alerts(limit=20),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/metrics/training-runs")
        def api_metrics_training_runs():
            """List all training run entries from Nexus."""
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                results = client.search("training finetune run")
                runs = [r for r in results if "training" in r.get("tags", [])]
                return jsonify({"runs": runs, "count": len(runs)})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Log Streaming Routes ────────────────────────────────────

        @app.route("/api/logs/recent")
        def api_logs_recent():
            """Get recent logs from CosyLogger ring buffer."""
            try:
                from engine.logging.cosy_logger import get_logs
                level = request.args.get("level", "WARNING")
                count = int(request.args.get("count", 100))
                logs = get_logs(level=level, count=count)
                return jsonify({"logs": logs, "count": len(logs)})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/logs/store", methods=["POST"])
        def api_logs_store():
            """Flush recent ERROR+ logs to Nexus for pattern analysis."""
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                from engine.logging.cosy_logger import get_logs
                level = request.json.get("level", "ERROR") if request.json else "ERROR"
                count = int(request.json.get("count", 50)) if request.json else 50
                logs = get_logs(level=level, count=count)
                if not logs:
                    return jsonify({"stored": 0, "message": "No logs to store"})
                content = "\n".join(
                    f"[{l.get('timestamp', '?')}] {l.get('level', '?')} "
                    f"{l.get('name', '?')}: {l.get('message', '')}"
                    for l in logs
                )
                entry_id = client.add_entry(
                    title=f"System Logs: {time.strftime('%Y-%m-%d %H:%M')}",
                    content=content,
                    content_type="history",
                    category="debugging",
                    tags=["logs", "system", level.lower()],
                )
                self._log_activity("log_store", f"{len(logs)} entries", "store")
                return jsonify({"stored": len(logs), "entry_id": entry_id})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Data Export Routes ──────────────────────────────────────

        @app.route("/api/export/all")
        def api_export_all():
            """Export entire Nexus knowledge base as JSON."""
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                from flask import Response
                entries = []
                for ctype in ["note", "code", "document", "prompt",
                              "transcript", "research", "memory",
                              "history", "plan"]:
                    try:
                        results = client.list_by_type(ctype, limit=1000)
                        entries.extend(results)
                    except Exception:
                        pass
                # Also export Q&A cache
                qa_pairs = []
                try:
                    qa_results = client.search("*", limit=2000)
                    qa_pairs = [r for r in qa_results
                                if r.get("content_type") == "qa"]
                except Exception:
                    pass

                export_data = {
                    "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_count": len(entries),
                    "qa_count": len(qa_pairs),
                    "entries": entries,
                    "qa_pairs": qa_pairs,
                }
                export_json = json.dumps(export_data, indent=2, default=str)
                self._log_activity("export", f"{len(entries)} entries", "export")
                return Response(
                    export_json,
                    mimetype="application/json",
                    headers={
                        "Content-Disposition":
                            f"attachment; filename=nexus_export_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    },
                )
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/export/training")
        def api_export_training():
            """Export training-related entries as JSONL."""
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                from flask import Response
                results = client.search("training finetune run", limit=500)
                runs = [r for r in results if "training" in r.get("tags", [])]
                lines = [json.dumps(r, default=str) for r in runs]
                self._log_activity("export_training", f"{len(runs)} runs")
                return Response(
                    "\n".join(lines),
                    mimetype="application/x-ndjson",
                    headers={
                        "Content-Disposition":
                            f"attachment; filename=training_runs_{time.strftime('%Y%m%d')}.jsonl"
                    },
                )
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        # ── Backup & Restore Routes ─────────────────────────────────

        @app.route("/api/backup", methods=["POST"])
        def api_backup():
            """Create a Nexus knowledge base backup."""
            data = request.get_json(force=True) if request.is_json else {}
            label = data.get("label", "")
            try:
                from engine.nexus.self_maintenance import nexus_backup
                result = nexus_backup(label=label)
                if result.get("success"):
                    self._log_activity("backup", f"{result['entry_count']} entries", "backup")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/backup/list")
        def api_backup_list():
            """List available Nexus backups."""
            try:
                from engine.nexus.self_maintenance import nexus_list_backups
                backups = nexus_list_backups()
                return jsonify({"backups": backups, "count": len(backups)})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/backup/restore", methods=["POST"])
        def api_backup_restore():
            """Restore a Nexus backup."""
            data = request.get_json(force=True)
            backup_path = data.get("path", "")
            overwrite = data.get("overwrite", False)
            if not backup_path:
                return jsonify({"error": "path is required"}), 400
            try:
                from engine.nexus.self_maintenance import nexus_restore
                result = nexus_restore(backup_path, overwrite=overwrite)
                if result.get("success"):
                    self._log_activity(
                        "restore", f"{result['restored']} entries", "restore"
                    )
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/backup/prune", methods=["POST"])
        def api_backup_prune():
            """Prune old backups, keeping the most recent N."""
            data = request.get_json(force=True) if request.is_json else {}
            keep = int(data.get("keep", 10))
            try:
                from engine.nexus.self_maintenance import nexus_prune_backups
                result = nexus_prune_backups(keep=keep)
                self._log_activity("backup_prune", f"kept {keep}", "maintenance")
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/backup/auto", methods=["POST"])
        def api_backup_auto():
            """Start or stop auto-backup scheduler."""
            data = request.get_json(force=True) if request.is_json else {}
            action = data.get("action", "start")
            try:
                if action == "start":
                    from engine.nexus.self_maintenance import start_scheduled_maintenance
                    start_scheduled_maintenance(
                        backup_interval_hours=float(data.get("backup_hours", 24)),
                        maintenance_interval_hours=float(data.get("maintenance_hours", 12)),
                        max_backups=int(data.get("max_backups", 10)),
                    )
                    self._log_activity("auto_maintenance", "started", "maintenance")
                    return jsonify({"status": "started"})
                else:
                    from engine.nexus.self_maintenance import stop_scheduled_maintenance
                    stop_scheduled_maintenance()
                    self._log_activity("auto_maintenance", "stopped", "maintenance")
                    return jsonify({"status": "stopped"})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/import/json", methods=["POST"])
        def api_import_json():
            """Import entries from uploaded JSON."""
            data = request.get_json(force=True)
            entries = data.get("entries", [])
            if not entries:
                return jsonify({"error": "No entries to import"}), 400
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            imported = 0
            errors = 0
            for entry in entries:
                try:
                    client.add_entry(
                        title=entry.get("title", "Imported"),
                        content=entry.get("content", ""),
                        content_type=entry.get("content_type", "note"),
                        category=entry.get("category", "imported"),
                        tags=entry.get("tags", ["imported"]),
                    )
                    imported += 1
                except Exception:
                    errors += 1
            self._log_activity("import", f"{imported} entries", "import")
            return jsonify({"imported": imported, "errors": errors})

        # ── Guided NLM Distillation Routes ──────────────────────────

        @app.route("/api/nlm/guided/start", methods=["POST"])
        def api_guided_start():
            """Start a guided distillation session.

            NLM answers the initial question, then suggests 3 follow-ups
            with practical examples. Each answer is stored as a Q&A pair.
            """
            data = request.get_json(force=True)
            question = data.get("question", "")
            notebook_id = data.get("notebook_id")
            if not question:
                return jsonify({"error": "question is required"}), 400
            try:
                from engine.nexus.nlm_router import NLMRouter
                router = NLMRouter()
                result = router.route(question, notebook_id=notebook_id)
                answer = result.answer if hasattr(result, "answer") else str(result)

                # Generate 3 follow-up suggestions
                suggestions = self._generate_suggestions(question, answer, notebook_id)

                session_id = f"guided_{int(time.time())}_{hash(question) % 10000}"
                self._guided_sessions[session_id] = {
                    "history": [{"role": "user", "content": question},
                                {"role": "assistant", "content": answer}],
                    "notebook_id": notebook_id,
                    "qa_stored": 0,
                }

                # Auto-store first Q&A
                stored_qa = self._store_guided_qa(question, answer)

                return jsonify({
                    "session_id": session_id,
                    "answer": answer,
                    "suggestions": suggestions,
                    "qa_stored": 1 if stored_qa else 0,
                    "source_tier": getattr(result, "source_tier", "unknown"),
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/guided/continue", methods=["POST"])
        def api_guided_continue():
            """Continue a guided distillation session with a follow-up."""
            data = request.get_json(force=True)
            session_id = data.get("session_id", "")
            question = data.get("question", "")
            if not session_id or session_id not in self._guided_sessions:
                return jsonify({"error": "Invalid session_id"}), 400
            if not question:
                return jsonify({"error": "question is required"}), 400
            try:
                session = self._guided_sessions[session_id]
                notebook_id = session.get("notebook_id")

                from engine.nexus.nlm_router import NLMRouter
                router = NLMRouter()
                result = router.route(question, notebook_id=notebook_id)
                answer = result.answer if hasattr(result, "answer") else str(result)

                session["history"].extend([
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ])

                suggestions = self._generate_suggestions(question, answer, notebook_id)
                stored_qa = self._store_guided_qa(question, answer)
                if stored_qa:
                    session["qa_stored"] = session.get("qa_stored", 0) + 1

                return jsonify({
                    "session_id": session_id,
                    "answer": answer,
                    "suggestions": suggestions,
                    "qa_stored": session["qa_stored"],
                    "turn": len(session["history"]) // 2,
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/guided/finish", methods=["POST"])
        def api_guided_finish():
            """Finish a guided session and return summary."""
            data = request.get_json(force=True)
            session_id = data.get("session_id", "")
            if session_id not in self._guided_sessions:
                return jsonify({"error": "Invalid session_id"}), 400
            session = self._guided_sessions.pop(session_id)
            turns = len(session["history"]) // 2
            return jsonify({
                "turns": turns,
                "qa_stored": session.get("qa_stored", 0),
                "history": session["history"],
            })

        # ── Training Data Pipeline ─────────────────────────────────────

        @app.route("/api/training/status")
        def api_training_status():
            """Full training pipeline status — candidates, datasets, readiness."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify(mgr.get_pipeline_status().to_dict())

        @app.route("/api/training/candidates")
        def api_training_candidates():
            """List training candidates for review/curation."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            dataset = request.args.get("dataset")
            min_quality = float(request.args.get("min_quality", 0.0))
            exported = request.args.get("exported")
            limit = int(request.args.get("limit", 100))
            exp_flag = None
            if exported == "true":
                exp_flag = True
            elif exported == "false":
                exp_flag = False
            candidates = mgr.get_candidates(
                dataset=dataset,
                min_quality=min_quality,
                exported=exp_flag,
                limit=limit,
            )
            return jsonify({"candidates": candidates, "count": len(candidates)})

        @app.route("/api/training/candidates/<int:candidate_id>/quality", methods=["PUT"])
        def api_training_update_quality(candidate_id: int):
            """Update quality score for a candidate (user review)."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            result = mgr.update_candidate_quality(
                candidate_id=candidate_id,
                quality_score=float(data.get("quality_score", 0.5)),
                notes=data.get("notes", ""),
            )
            return jsonify({"action": result.action, "affected": result.affected,
                            "details": result.details})

        @app.route("/api/training/candidates/bulk", methods=["PUT"])
        def api_training_bulk_quality():
            """Bulk approve/reject candidates."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            result = mgr.bulk_update_quality(
                candidate_ids=data.get("ids", []),
                quality_score=float(data.get("quality_score", 1.0)),
                notes=data.get("notes", "bulk_update"),
            )
            return jsonify({"action": result.action, "affected": result.affected,
                            "details": result.details})

        @app.route("/api/training/candidates/<int:candidate_id>", methods=["DELETE"])
        def api_training_delete_candidate(candidate_id: int):
            """Delete a training candidate."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            result = mgr.delete_candidate(candidate_id)
            return jsonify({"action": result.action, "affected": result.affected})

        @app.route("/api/training/candidates", methods=["POST"])
        def api_training_add_manual():
            """Manually add a training example (gold data)."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            result = mgr.add_manual_example(
                dataset=data.get("dataset", ""),
                input_text=data.get("input_text", ""),
                output_text=data.get("output_text", ""),
                quality_score=float(data.get("quality_score", 1.0)),
                notes=data.get("notes", "manual"),
            )
            return jsonify({"action": result.action, "affected": result.affected,
                            "details": result.details})

        @app.route("/api/training/capture", methods=["POST"])
        def api_training_capture_toggle():
            """Enable or disable live training data capture."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            enabled = data.get("enabled", True)
            success = mgr.set_capture_enabled(enabled)
            return jsonify({"enabled": enabled, "success": success})

        @app.route("/api/training/seed", methods=["POST"])
        def api_training_seed():
            """Generate synthetic seed data for datasets."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            results = mgr.seed_datasets(
                datasets=data.get("datasets"),
                force=data.get("force", False),
            )
            return jsonify(results)

        @app.route("/api/training/export-live", methods=["POST"])
        def api_training_export_live():
            """Export pending candidates from DB to live JSONL files."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True) if request.is_json else {}
            mgr = get_data_manager()
            results = mgr.export_live_candidates(
                dataset=data.get("dataset"),
                min_quality=float(data.get("min_quality", 0.7)),
            )
            return jsonify(results)

        @app.route("/api/training/merge", methods=["POST"])
        def api_training_merge():
            """Merge synthetic + live datasets into combined files."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True) if request.is_json else {}
            mgr = get_data_manager()
            results = mgr.merge_datasets(dataset=data.get("dataset"))
            return jsonify(results)

        @app.route("/api/training/augment/nexus", methods=["POST"])
        def api_training_augment_nexus():
            """Augment training data from Nexus Q&A."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify(mgr.augment_from_nexus())

        @app.route("/api/training/augment/nlm", methods=["POST"])
        def api_training_augment_nlm():
            """Augment training data from NLM distillation."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True)
            mgr = get_data_manager()
            results = mgr.augment_from_nlm(
                notebook_id=data.get("notebook_id", ""),
                topics=data.get("topics"),
                count=int(data.get("count", 50)),
            )
            return jsonify(results)

        @app.route("/api/training/validate")
        def api_training_validate():
            """Validate all datasets for quality and completeness."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify(mgr.validate_datasets())

        @app.route("/api/training/combine", methods=["POST"])
        def api_training_combine():
            """Create the final combined multi-task dataset."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify(mgr.create_combined_dataset())

        @app.route("/api/training/prepare", methods=["POST"])
        def api_training_prepare():
            """Run the full preparation pipeline end-to-end."""
            from training.data_manager import get_data_manager
            data = request.get_json(force=True) if request.is_json else {}
            mgr = get_data_manager()
            results = mgr.prepare_for_training(
                min_quality=float(data.get("min_quality", 0.7)),
                augment_nexus=data.get("augment_nexus", False),
                augment_nlm=data.get("augment_nlm", False),
                nlm_notebook_id=data.get("nlm_notebook_id", ""),
            )
            return jsonify(results)

        @app.route("/api/training/config")
        def api_training_config():
            """Get the current training configuration."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify(mgr.get_training_config())

        @app.route("/api/training/files")
        def api_training_files():
            """List all dataset files with sizes and counts."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            return jsonify({"files": mgr.get_dataset_files()})

        @app.route("/api/training/download/<filename>")
        def api_training_download(filename: str):
            """Download a dataset file."""
            from training.data_manager import get_data_manager
            mgr = get_data_manager()
            path = mgr.download_dataset(filename)
            if not path:
                return jsonify({"error": "File not found"}), 404
            from flask import send_file
            return send_file(str(path), as_attachment=True,
                             download_name=filename, mimetype="application/jsonl")

        # ──── Router Training Data ────

        @app.route("/api/router-data/stats")
        def router_data_stats():
            """Get router training data collection stats."""
            try:
                from engine.lmstudio.router_data import get_router_data_collector
                collector = get_router_data_collector()
                stats = collector.get_stats()
                return jsonify(stats)
            except Exception as e:
                return jsonify({"error": str(e), "records": 0})

        @app.route("/api/router-data/export", methods=["POST"])
        def router_data_export():
            """Export router training data as JSONL."""
            try:
                from engine.lmstudio.router_data import get_router_data_collector
                collector = get_router_data_collector()
                body = request.get_json(silent=True) or {}
                path = body.get("path", "training/datasets/router_live.jsonl")
                count = collector.export_jsonl(path)
                return jsonify({"exported": count, "path": path})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/router-data/readiness")
        def router_data_readiness():
            """Check if we have enough data to start training."""
            try:
                from engine.lmstudio.router_data import get_router_data_collector
                collector = get_router_data_collector()
                stats = collector.get_stats()
                total = stats.get("total_records", 0)
                success_rate = stats.get("success_rate", 0)
                ready = total >= 100 and success_rate > 0.5
                return jsonify({
                    "ready": ready,
                    "total_records": total,
                    "success_rate": success_rate,
                    "min_required": 100,
                    "recommendation": "Ready for training!" if ready else f"Need {max(0, 100 - total)} more records",
                })
            except Exception as e:
                return jsonify({"ready": False, "error": str(e)})

        # ── Training Pipeline v0.64 ───────────────────────────────────────────

        @app.route("/api/nexus/router-stats")
        def api_nexus_router_stats():
            """Alias for /api/nlm/router/stats — finetuned router + NLM savings."""
            try:
                from engine.nexus.nlm_router import get_nlm_router
                stats = get_nlm_router().savings_report()
                try:
                    from engine.lmstudio.finetuned_router import get_finetuned_router
                    fr = get_finetuned_router()
                    stats["finetuned_active"] = fr.get_active_models()
                except Exception:
                    stats["finetuned_active"] = {}
                return jsonify(stats)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/model-registry")
        def api_finetune_registry():
            """List all registered fine-tuned models."""
            try:
                from training.model_registry import get_model_registry
                reg = get_model_registry()
                return jsonify({"models": reg.list_models(), "summary": reg.summary()})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/leaderboard")
        def api_finetune_leaderboard():
            """Benchmark leaderboard — best score per model type."""
            try:
                from training.benchmark_runner import get_benchmark_runner
                return jsonify(get_benchmark_runner().get_leaderboard())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/promote", methods=["POST"])
        def api_finetune_promote():
            """Promote a fine-tuned model to active."""
            try:
                data = request.get_json(force=True) or {}
                model_type = data.get("model_type", "")
                model_id = data.get("model_id", "")
                if not model_type or not model_id:
                    return jsonify({"error": "model_type and model_id required"}), 400
                from training.model_registry import get_model_registry
                reg = get_model_registry()
                reg.promote(model_type, model_id)
                return jsonify({"status": "promoted", "model_type": model_type, "model_id": model_id})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/jobs")
        def api_finetune_jobs():
            """List all fine-tune jobs."""
            try:
                from training.finetune_orchestrator import get_finetune_orchestrator
                return jsonify({"jobs": get_finetune_orchestrator().list_jobs()})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/jobs/run-next", methods=["POST"])
        def api_finetune_run_next():
            """Run the next pending fine-tune job."""
            try:
                from training.finetune_orchestrator import get_finetune_orchestrator
                job = get_finetune_orchestrator().run_next()
                if job is None:
                    return jsonify({"status": "empty", "message": "No pending jobs"})
                return jsonify({"status": "started", "job_id": job.job_id, "model_type": job.model_type})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/submit-job", methods=["POST"])
        def api_finetune_submit():
            """Submit a new fine-tune job."""
            try:
                data = request.get_json(force=True) or {}
                model_type = data.get("model_type", "qa_evaluator")
                base_model = data.get("base_model", "qwen-270m")
                from training.finetune_orchestrator import get_finetune_orchestrator
                job = get_finetune_orchestrator().submit(model_type, base_model=base_model)
                return jsonify({"status": "queued", "job_id": job.job_id, "model_type": job.model_type})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/training/build-dataset", methods=["POST"])
        def api_finetune_build_dataset():
            """Build/refresh dataset for a model type."""
            try:
                data = request.get_json(force=True) or {}
                model_type = data.get("model_type", "qa_evaluator")
                from training.micro_datasets import MicroDatasetManager
                mgr = MicroDatasetManager()
                result = mgr.build(model_type)
                return jsonify(result)
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/scheduler/trigger", methods=["POST"])
        def api_scheduler_trigger():
            """Manually trigger a scheduler task by ID."""
            try:
                data = request.get_json(force=True) or {}
                task_id = data.get("task_id", "")
                if not task_id:
                    return jsonify({"error": "task_id required"}), 400
                from engine.nexus.scheduler_daemon import get_scheduler_daemon
                daemon = get_scheduler_daemon()
                result = daemon.run_task(task_id)
                return jsonify({"status": "triggered", "task_id": task_id, "result": result})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/scheduler/recent")
        def api_scheduler_recent():
            """Get recent scheduler task run history (tasks with last_run set)."""
            try:
                from engine.nexus.scheduler_daemon import get_scheduler_daemon
                daemon = get_scheduler_daemon()
                tasks = daemon.list_tasks()
                # Return tasks that have run at least once, sorted by last_run desc
                run_tasks = [t for t in tasks if t.get("last_run")]
                run_tasks.sort(key=lambda t: t.get("last_run", ""), reverse=True)
                limit = int(request.args.get("limit", 20))
                return jsonify({"history": run_tasks[:limit]})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

    def _generate_suggestions(
        self, question: str, answer: str, notebook_id: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Generate 3 follow-up suggestions based on the Q&A context.

        Each suggestion has a 'question' (the follow-up) and a 'label'
        (short human-readable tag like 'Practical Example').
        """
        suggestions = []
        try:
            from engine.nexus.knowledge_forge import KnowledgeForge
            forge = KnowledgeForge()
            context = f"Question: {question}\nAnswer: {answer[:500]}"
            qs = forge.generate_questions(
                context=context,
                category="follow_up",
                count=3,
            )
            labels = ["Dive Deeper", "Practical Example", "Related Topic"]
            for i, q in enumerate(qs[:3]):
                suggestions.append({
                    "question": q,
                    "label": labels[i] if i < len(labels) else "Follow-up",
                })
        except Exception as exc:
            logger.debug("Suggestion generation failed: %s", exc)
            # Fallback: generate generic follow-ups from the question
            suggestions = [
                {"question": f"Can you show a practical code example for: {question}",
                 "label": "Code Example"},
                {"question": f"What are common pitfalls when implementing this?",
                 "label": "Pitfalls"},
                {"question": f"How does this integrate with the rest of the system?",
                 "label": "Integration"},
            ]
        return suggestions

    def _store_guided_qa(self, question: str, answer: str) -> Optional[str]:
        """Store a guided distillation Q&A pair in Nexus."""
        client = self._get_client()
        if not client:
            return None
        try:
            return client.add_qa(question, answer, category="distillation")
        except Exception as exc:
            logger.debug("Failed to store guided Q&A: %s", exc)
            return None

    # ── Lifecycle ───────────────────────────────────────────────────────

    # v1.51.0 [2026-03-22] — Lifecycle delegated to FlaskScene

    def on_before_serve(self) -> None:
        """Hook: log activity and check NLM proxy health before serving."""
        self._log_activity("panel_start", f"port={self.port}")
        self._check_nlm_proxy_health()

    def _check_nlm_proxy_health(self) -> None:
        """Warn at startup if NLM proxy is unreachable."""
        import urllib.request
        proxy_url = self._nlm_proxy_url()
        try:
            req = urllib.request.Request(f"{proxy_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    logger.info("NLM proxy online at %s — NLM intelligence active", proxy_url)
                    return
        except Exception:
            pass
        logger.warning(
            "NLM proxy OFFLINE at %s — NLM Lab features will degrade to cache/FTS only. "
            "Start it with: python -m engine.mcp.nlm_live_proxy  "
            "Or launch with: python launcher.py nlm_proxy",
            proxy_url,
        )

    def on_shutdown(self) -> None:
        """Hook: log activity on shutdown."""
        self._log_activity("panel_stop")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return scene metadata for hub discovery."""
        return {
            "name": SCENE_ID,
            "title": _MODULE_METADATA["title"],
            "description": _MODULE_METADATA["description"],
            "port": self.port,
            "type": "admin",
            "features": _MODULE_METADATA["features"],
        }
