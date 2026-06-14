"""
Dashboard Scene — Flask migration
==================================

Character & system management dashboard.  Replaces the Streamlit
``dashboard_v2.py`` with a FlaskScene subclass serving a Jinja2 +
vanilla-JS frontend over REST API routes.

Manages characters, personalities, roles, and memories through the
existing simulation database and RAG memory system.

Version: v1.49.2 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.2 [2026-03-22] — Initial Flask migration from Streamlit dashboard_v2.py
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from flask import jsonify, render_template, request

from engine.config import get_config
from engine.scenes.flask_scene import FlaskScene
from engine.port_registry import get_port
from content.simulation.database.db import Database
from content.simulation.database.rag import RAGMemory
from content.simulation.character_system.character import Character
from content.simulation.character_system.personality import Personality
from content.simulation.character_system.role import Role

logger = logging.getLogger(__name__)


# ──── DashboardScene ──────────────────────────────────────────────────────

class DashboardScene(FlaskScene):
    """Character & system management dashboard.

    CONNECTS: Database, RAGMemory, Character, Personality, Role
    CALLED BY: launcher.py, TUI
    EMITS: REST JSON responses
    """

    SCENE_METADATA = {
        "name": "dashboard",
        "display_name": "DASHBOARD",
        "port": 8501,
        "type": "tool",
        "accent_color": "#667eea",
        "description": "Character & system management dashboard",
        "tags": ["admin", "management"],
    }

    # ── Construction ──────────────────────────────────────────────────

    # v1.49.2 [2026-03-22] — FlaskScene init, wire DB + RAG + managers
    def __init__(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
        """Initialize the dashboard scene.

        Args:
            host: Bind address.
            port: Bind port.  Falls back to port registry / SCENE_METADATA.
        """
        if port is None:
            port = get_port("dashboard", 8501)
        super().__init__(host=host, port=port)

        # Core data services
        self._db = Database()
        self._rag = RAGMemory()
        self._personality_mgr = Personality(self._db)
        self._role_mgr = Role(self._db)

        self._register_routes()
        logger.info("DashboardScene routes registered")

    # ── Route Registration ────────────────────────────────────────────

    # v1.49.2 [2026-03-22] — All REST API routes for dashboard CRUD
    # CONNECTS: Database, RAGMemory, Personality, Role, Character
    # CALLED BY: dashboard.js fetch() calls
    # EMITS: JSON responses
    def _register_routes(self) -> None:
        """Register all dashboard API and page routes."""
        app = self.app

        # ── Page route ────────────────────────────────────────────────

        @app.route("/")
        def index():
            """Render the dashboard UI."""
            meta = self.SCENE_METADATA
            return render_template(
                "dashboard_ui.html",
                scene_key="dashboard",
                scene_display_name=meta["display_name"],
                scene_accent=meta["accent_color"],
                scene_accent_rgb="102 126 234",
                scene_version="v1.49.2",
            )

        # ── Stats ─────────────────────────────────────────────────────

        @app.route("/api/dashboard/stats")
        def api_stats():
            """Return aggregate counts for dashboard overview.

            Returns:
                JSON with character, personality, role, and memory counts.
            """
            try:
                characters = self._db.get_all_characters()
                personalities = self._db.get_all_personalities()
                roles = self._db.get_all_roles()
                memory_count = self._rag.get_memory_count()
                return jsonify({
                    "characters": len(characters),
                    "personalities": len(personalities),
                    "roles": len(roles),
                    "memories": memory_count,
                })
            except Exception as exc:
                logger.error("Failed to fetch dashboard stats: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Characters ────────────────────────────────────────────────

        @app.route("/api/characters", methods=["GET"])
        def api_characters_list():
            """List all characters."""
            try:
                characters = self._db.get_all_characters()
                return jsonify(characters)
            except Exception as exc:
                logger.error("Failed to list characters: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters", methods=["POST"])
        def api_characters_create():
            """Create a new character.

            Expects JSON body with at least ``name``.  Optional fields:
            ``age``, ``sex``, ``hair_color``, ``eye_color``, ``height``,
            ``body_type``, ``personality_id``, ``tags``.
            """
            try:
                data = request.get_json(force=True)
                if not data or not data.get("name"):
                    return jsonify({"error": "name is required"}), 400

                name = data.pop("name")
                personality_id = data.pop("personality_id", None)
                char = Character.create(
                    name=name,
                    personality_id=personality_id,
                    db=self._db,
                    **data,
                )
                logger.info("Created character %s (%s)", char.name, char.id)
                return jsonify(char.to_dict()), 201
            except Exception as exc:
                logger.error("Failed to create character: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>", methods=["GET"])
        def api_characters_get(char_id: str):
            """Get a single character by ID."""
            try:
                char = Character.load(char_id, db=self._db)
                if not char:
                    return jsonify({"error": "Character not found"}), 404
                return jsonify(char.to_dict())
            except Exception as exc:
                logger.error("Failed to get character %s: %s", char_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>", methods=["PUT"])
        def api_characters_update(char_id: str):
            """Update an existing character.

            Accepts any combination of character fields in the JSON body.
            State fields (mood, energy, etc.) are routed to character_states;
            core fields to the characters table; extras to metadata.
            """
            try:
                data = request.get_json(force=True)
                if not data:
                    return jsonify({"error": "JSON body required"}), 400

                char = Character.load(char_id, db=self._db)
                if not char:
                    return jsonify({"error": "Character not found"}), 404

                char.save(**data)
                # Reload to return fresh data
                char = Character.load(char_id, db=self._db)
                logger.info("Updated character %s", char_id)
                return jsonify(char.to_dict())
            except Exception as exc:
                logger.error("Failed to update character %s: %s", char_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>", methods=["DELETE"])
        def api_characters_delete(char_id: str):
            """Delete a character."""
            try:
                existing = self._db.get_character(char_id)
                if not existing:
                    return jsonify({"error": "Character not found"}), 404

                success = self._db.delete_character(char_id)
                if success:
                    logger.info("Deleted character %s", char_id)
                    return jsonify({"ok": True})
                return jsonify({"error": "Delete failed"}), 500
            except Exception as exc:
                logger.error("Failed to delete character %s: %s", char_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Personalities ─────────────────────────────────────────────

        @app.route("/api/personalities", methods=["GET"])
        def api_personalities_list():
            """List all personalities."""
            try:
                return jsonify(self._personality_mgr.list_all())
            except Exception as exc:
                logger.error("Failed to list personalities: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/personalities", methods=["POST"])
        def api_personalities_create():
            """Create a custom personality.

            Expects JSON with ``name``, ``system_prompt``.  Optional:
            ``traits`` (list), ``communication_style`` (dict),
            ``sexual_openness`` (float), ``values`` (list).
            """
            try:
                data = request.get_json(force=True)
                if not data or not data.get("name") or not data.get("system_prompt"):
                    return jsonify({"error": "name and system_prompt are required"}), 400

                pers_id = self._personality_mgr.create_custom(
                    name=data["name"],
                    system_prompt=data["system_prompt"],
                    traits=data.get("traits", []),
                    communication_style=data.get("communication_style", {}),
                    sexual_openness=data.get("sexual_openness", 0.5),
                    values=data.get("values", []),
                )
                logger.info("Created personality %s (%s)", data["name"], pers_id)
                personality = self._personality_mgr.get(pers_id)
                return jsonify(personality), 201
            except Exception as exc:
                logger.error("Failed to create personality: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/personalities/init", methods=["POST"])
        def api_personalities_init():
            """Initialize all default personality templates."""
            try:
                created = self._personality_mgr.initialize_defaults()
                logger.info("Initialized %d default personalities", len(created))
                return jsonify({"created": len(created), "ids": created})
            except Exception as exc:
                logger.error("Failed to initialize personalities: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Roles ─────────────────────────────────────────────────────

        @app.route("/api/roles", methods=["GET"])
        def api_roles_list():
            """List all roles."""
            try:
                return jsonify(self._role_mgr.list_all())
            except Exception as exc:
                logger.error("Failed to list roles: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/roles", methods=["POST"])
        def api_roles_create():
            """Create a custom role.

            Expects JSON with ``name``, ``description``.  Optional:
            ``required_traits`` (list), ``context`` (str), ``scenario`` (str).
            """
            try:
                data = request.get_json(force=True)
                if not data or not data.get("name") or not data.get("description"):
                    return jsonify({"error": "name and description are required"}), 400

                role_id = self._role_mgr.create_custom(
                    name=data["name"],
                    description=data["description"],
                    required_traits=data.get("required_traits", []),
                    context=data.get("context", ""),
                    scenario=data.get("scenario", ""),
                )
                logger.info("Created role %s (%s)", data["name"], role_id)
                role = self._role_mgr.get(role_id)
                return jsonify(role), 201
            except Exception as exc:
                logger.error("Failed to create role: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/roles/init", methods=["POST"])
        def api_roles_init():
            """Initialize all default role templates."""
            try:
                created = self._role_mgr.initialize_defaults()
                logger.info("Initialized %d default roles", len(created))
                return jsonify({"created": len(created), "ids": created})
            except Exception as exc:
                logger.error("Failed to initialize roles: %s", exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        # ── Memories ──────────────────────────────────────────────────

        @app.route("/api/characters/<char_id>/memories", methods=["GET"])
        def api_memories_list(char_id: str):
            """List memories for a character."""
            try:
                limit = request.args.get("limit", 100, type=int)
                memories = self._db.get_character_memories(char_id, limit=limit)
                return jsonify(memories)
            except Exception as exc:
                logger.error("Failed to list memories for %s: %s", char_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>/memories", methods=["POST"])
        def api_memories_add(char_id: str):
            """Add a memory for a character.

            Expects JSON with ``content``.  Optional: ``importance`` (float),
            ``emotion`` (str).
            """
            try:
                data = request.get_json(force=True)
                if not data or not data.get("content"):
                    return jsonify({"error": "content is required"}), 400

                mem_id = self._db.add_memory(
                    char_id,
                    data["content"],
                    importance=data.get("importance", 0.5),
                    emotion=data.get("emotion"),
                )
                # Also add to RAG for semantic search
                try:
                    self._rag.add_memory(
                        char_id,
                        data["content"],
                        importance=data.get("importance", 0.5),
                        emotion=data.get("emotion"),
                        scene_id="dashboard",
                    )
                except Exception as rag_exc:
                    logger.warning("RAG memory add failed (DB succeeded): %s", rag_exc)

                logger.info("Added memory %s for character %s", mem_id, char_id)
                return jsonify({"id": mem_id, "ok": True}), 201
            except Exception as exc:
                logger.error("Failed to add memory for %s: %s", char_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/memories/<mem_id>", methods=["PUT"])
        def api_memories_update(mem_id: str):
            """Update an existing memory.

            Accepts ``content``, ``importance``, ``emotion`` in JSON body.
            """
            try:
                data = request.get_json(force=True)
                if not data:
                    return jsonify({"error": "JSON body required"}), 400

                success = self._db.update_memory(mem_id, **data)
                if success:
                    logger.info("Updated memory %s", mem_id)
                    return jsonify({"ok": True})
                return jsonify({"error": "Update failed"}), 500
            except Exception as exc:
                logger.error("Failed to update memory %s: %s", mem_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/memories/<mem_id>", methods=["DELETE"])
        def api_memories_delete(mem_id: str):
            """Delete a memory."""
            try:
                success = self._db.delete_memory(mem_id)
                if success:
                    logger.info("Deleted memory %s", mem_id)
                    return jsonify({"ok": True})
                return jsonify({"error": "Delete failed"}), 500
            except Exception as exc:
                logger.error("Failed to delete memory %s: %s", mem_id, exc, exc_info=True)
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>/memories/search", methods=["GET"])
        def api_memories_search(char_id: str):
            """Semantic search memories for a character.

            Args (query params):
                q: Search query string.
                n: Number of results (default 5).
            """
            try:
                query = request.args.get("q", "")
                n_results = request.args.get("n", 5, type=int)
                if not query:
                    return jsonify({"error": "q parameter required"}), 400

                results = self._rag.query_memories(
                    char_id, query, n_results=n_results,
                    scene_id="dashboard",
                )
                return jsonify(results)
            except Exception as exc:
                logger.error(
                    "Failed to search memories for %s: %s", char_id, exc, exc_info=True
                )
                return jsonify({"error": str(exc)}), 500


# ──── Standalone Entry Point ──────────────────────────────────────────────

if __name__ == "__main__":
    scene = DashboardScene()
    scene.start()
