"""Nexus Control Panel — Full-featured knowledge management dashboard.

Provides real-time monitoring, Librarian agent chat, maintenance controls,
workflow management, training data curation, and Copilot integration panel.
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

from flask import Flask, jsonify, render_template, request

from engine.config import get_config
from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin

logger = logging.getLogger(__name__)

SCENE_ID = "nexus_panel"
DEFAULT_PORT = 5570

SCENE_METADATA = {
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


class NexusPanelScene(BaseScene, NexusSceneMixin):
    """Nexus knowledge management control panel."""

    SCENE_METADATA = SCENE_METADATA

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        cfg = get_config()
        port = cfg.get(f"scenes.{SCENE_ID}.port", port)
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self._template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self._static_dir = os.path.join(os.path.dirname(__file__), "static")
        self.app = Flask(
            __name__,
            template_folder=self._template_dir,
            static_folder=self._static_dir,
        )
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

        self._register_routes()
        self.nexus_init(SCENE_ID)
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

    # ── Nexus Proxy Helpers ─────────────────────────────────────────────

    def _get_client(self):
        """Get NexusClient, lazy import."""
        try:
            from engine.nexus.client import get_nexus_client
            return get_nexus_client()
        except Exception:
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
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                return jsonify(client.nlm_status())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/nlm/notebooks")
        def api_nlm_notebooks():
            client = self._get_client()
            if not client:
                return jsonify({"error": "Nexus unavailable"}), 503
            try:
                return jsonify(client.nlm_list_notebooks())
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

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

            # The Librarian uses Nexus knowledge to answer
            client = self._get_client()
            if not client or not client.is_available():
                return jsonify({
                    "response": "I'm sorry, I can't reach the Nexus knowledge base right now. "
                                "Please check that the Nexus service is running on port 8700.",
                    "source": "offline",
                })

            # Try Q&A pipeline first
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
                        "confidence": 0.5,
                        "sources": [r.get("title", "") for r in results[:3]],
                    })
            except Exception as exc:
                logger.warning("Librarian search failed: %s", exc)

            return jsonify({
                "response": "I couldn't find relevant information. Try rephrasing your "
                            "question or use the Knowledge Explorer to browse entries directly.",
                "source": "none",
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

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Nexus Control Panel."""
        self._log_activity("panel_start", f"port={self.port}")
        logger.info("Starting Nexus Control Panel on port %s", self.port)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        """Stop the panel and flush Nexus events."""
        self._log_activity("panel_stop")
        self.nexus_flush()
        logger.info("Nexus Control Panel stopped")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return scene metadata for hub discovery."""
        return {
            "name": SCENE_ID,
            "title": SCENE_METADATA["title"],
            "description": SCENE_METADATA["description"],
            "port": self.port,
            "type": "admin",
            "features": SCENE_METADATA["features"],
        }
