"""THE TERMINAL — Flask hub for CosySim. v0.68 Dark Renaissance.

Main navigation hub connecting all scenes. Port 8500, accent #3b82f6.

Usage:
    python launcher.py --mode hub
"""
from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2
from flask import Flask, jsonify, render_template

from engine.scenes.base_scene import BaseScene
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

SCENE_ID = "hub"
DEFAULT_PORT = 8500

_SCENE_DIR = Path(__file__).parent

# ── Scene catalogue ──────────────────────────────────────────────────
# Groups: "neon_world" | "action" | "system"
SCENE_CATALOGUE: List[Dict[str, Any]] = [
    # 🏙️ NEON WORLD
    {"id": "bedroom",   "port": 5556, "label": "THE PENTHOUSE",     "subtitle": "Desire & Danger",      "icon": "🏙️", "group": "neon_world", "accent": "#ec4899", "desc": "Intimate roleplay with emotional AI companions"},
    {"id": "neoncity",  "port": 5563, "label": "NEON CITY",         "subtitle": "Streets Never Sleep",   "icon": "🌃", "group": "neon_world", "accent": "#06b6d4", "desc": "Cyberpunk city exploration and noir stories"},
    {"id": "lounge",    "port": 5557, "label": "THE PIT",           "subtitle": "Underground Jazz",      "icon": "🎵", "group": "neon_world", "accent": "#a855f7", "desc": "Jazz bar with NPCs, drinks, and mood contagion"},
    {"id": "tavern",    "port": 5558, "label": "RUSTY ANCHOR",      "subtitle": "Last Round Standing",   "icon": "⚓", "group": "neon_world", "accent": "#d97706", "desc": "Gritty dockside tavern with quests and barkeep wisdom"},
    {"id": "casino",    "port": 5559, "label": "CLUB NOIR",         "subtitle": "High-Stakes Shadows",   "icon": "🎴", "group": "neon_world", "accent": "#f97316", "desc": "Blackjack, poker, and a dealer who never blinks"},
    {"id": "phone",     "port": 5555, "label": "SIGNAL",            "subtitle": "Dark Net Comms",        "icon": "📡", "group": "neon_world", "accent": "#22c55e", "desc": "Encrypted messaging, calls, photo/video sharing"},
    # ⚔️ ACTION
    {"id": "arena",     "port": 5568, "label": "THE COLOSSEUM",     "subtitle": "Blood Sport Circuit",   "icon": "⚔️", "group": "action",     "accent": "#ef4444", "desc": "Tactical arena combat with betting and AI fighters"},
    {"id": "heist",     "port": 5565, "label": "THE SCORE",         "subtitle": "One Last Job",          "icon": "🔓", "group": "action",     "accent": "#f59e0b", "desc": "Plan and execute elaborate heists with your AI crew"},
    {"id": "realm",     "port": 5562, "label": "SHATTERED THRONE",  "subtitle": "Kingdoms in Ruin",      "icon": "🏰", "group": "action",     "accent": "#8b5cf6", "desc": "Open-world RPG with quest chains and exploration"},
    {"id": "gallery",   "port": 5560, "label": "THE OBSCURA",       "subtitle": "Forbidden Visions",     "icon": "🎨", "group": "action",     "accent": "#e879f9", "desc": "AI-generated art exhibition and dark curation"},
    # 🖥️ SYSTEM
    {"id": "coders",    "port": 5564, "label": "THE LAB",           "subtitle": "Code & Chaos",          "icon": "🧪", "group": "system",     "accent": "#10b981", "desc": "Multi-agent programming collaboration"},
    {"id": "games",     "port": 5567, "label": "THE ARCADE",        "subtitle": "Play to Win",           "icon": "🎮", "group": "system",     "accent": "#3b82f6", "desc": "Mystery investigation and truth-or-dare with AI GameMaster"},
    {"id": "command_center", "port": 5566, "label": "ADMIN",        "subtitle": "System Override",       "icon": "📡", "group": "system",     "accent": "#64748b", "desc": "Real-time system monitoring and control"},
    {"id": "nexus_panel",    "port": 5570, "label": "NEXUS PANEL",  "subtitle": "Knowledge Engine",      "icon": "🧠", "group": "system",     "accent": "#7c3aed", "desc": "Knowledge management, Librarian AI, workflows"},
    {"id": "intel_hub",      "port": 5580, "label": "INTEL HUB",   "subtitle": "All Seeing Eye",        "icon": "◆",  "group": "system",     "accent": "#0ea5e9", "desc": "Unified control: Nexus, Copilot, NLM, fine-tuning, scheduler"},
]

# Group metadata for section headers
SCENE_GROUPS: List[Dict[str, str]] = [
    {"id": "neon_world", "label": "NEON WORLD",  "icon": "🏙️"},
    {"id": "action",     "label": "ACTION",       "icon": "⚔️"},
    {"id": "system",     "label": "SYSTEM",       "icon": "🖥️"},
]


def _port_open(port: int) -> bool:
    """Check if a TCP port is listening on localhost."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class HubScene(BaseScene):
    """Flask-based CosySim hub — THE TERMINAL navigation centre. v0.68."""

    SCENE_METADATA = {
        "name": "hub",
        "display_name": "THE TERMINAL",
        "port": DEFAULT_PORT,
        "type": "hub",
        "accent_color": "#3b82f6",
        "accent_rgb": "59 130 246",
        "description": "Every door leads somewhere. Not all of them come back.",
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self.app = Flask(
            __name__,
            template_folder=str(_SCENE_DIR / "templates"),
            static_folder=str(_SCENE_DIR / "static"),
            static_url_path="/hub/static",
        )
        register_shared_assets(self.app)
        self.register_health_route(self.app)

        # ChoiceLoader: scene templates first, then shared (for navbar_v2.html)
        _shared_tpl = _SCENE_DIR.parent.parent / "shared" / "templates"
        self.app.jinja_loader = jinja2.ChoiceLoader([
            jinja2.FileSystemLoader(str(_SCENE_DIR / "templates")),
            jinja2.FileSystemLoader(str(_shared_tpl)),
        ])

        # Optional: news feed blueprint
        try:
            from engine.nexus.news_feed_api import create_news_blueprint
            self.app.register_blueprint(create_news_blueprint(), url_prefix="/api/news")
        except Exception as exc:
            logger.debug("News feed API not available: %s", exc)

        self._setup_routes()
        logger.info("HubScene (THE TERMINAL) created on port %d", port)

    # ── Routes ──────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        """Register all Flask routes."""
        app = self.app

        @app.route("/")
        def index() -> str:
            return render_template(
                "hub.html",
                **self.inject_navbar_context(),
                scene_groups=SCENE_GROUPS,
            )

        @app.route("/api/scenes")
        def api_scenes() -> Any:
            """Return scene catalogue with live health status."""
            scenes = []
            for s in SCENE_CATALOGUE:
                online = _port_open(s["port"])
                scenes.append({**s, "status": "online" if online else "offline"})
            return jsonify(scenes)

        @app.route("/api/world_state")
        def api_world_state() -> Any:
            """Return current world time, active events, and faction data."""
            try:
                from engine.world.world_state import get_world_state
                ws = get_world_state()
                summary = ws.get_world_summary()
                return jsonify({
                    "ok": True,
                    "time": summary.get("time", {}),
                    "events": summary.get("active_events", []),
                    "weather": summary.get("weather", {}),
                    "npc_availability": summary.get("npc_availability", {}),
                })
            except Exception as exc:
                logger.warning("world_state unavailable: %s", exc)
                return jsonify({"ok": False, "error": str(exc), "time": {}, "events": []})

        @app.route("/api/economy")
        def api_economy() -> Any:
            """Return player credit balance and recent transactions."""
            try:
                from engine.economy.economy import get_economy_manager
                em = get_economy_manager()
                balance = em.get_balance("player")
                history = em.get_history("player", limit=5)
                txns = [
                    {
                        "amount": t.amount,
                        "type": t.type,
                        "scene": t.scene,
                        "description": t.description,
                        "balance_after": t.balance_after,
                    }
                    for t in history
                ]
                return jsonify({"ok": True, "balance": balance, "transactions": txns})
            except Exception as exc:
                logger.warning("economy unavailable: %s", exc)
                return jsonify({"ok": False, "balance": 0, "transactions": []})

        @app.route("/api/system")
        def api_system() -> Any:
            """Return system summary (agents, VRAM, active scenes)."""
            try:
                from engine.assistant.system_assistant import get_assistant
                return jsonify(get_assistant().get_system_summary())
            except Exception:
                return jsonify({"active_scenes": [], "vram_used_mb": 0, "agent_count": 0})

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start THE TERMINAL Flask server."""
        logger.info("THE TERMINAL opening on %s:%d", self.host, self.port)
        try:
            from engine.events.event_bus import get_event_bus
            get_event_bus().emit("scene_started", {"scene_id": SCENE_ID, "port": self.port})
        except Exception:
            pass
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        """Stop THE TERMINAL."""
        logger.info("THE TERMINAL shutting down")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return plugin metadata for admin discovery."""
        return {
            "name": "THE TERMINAL",
            "display_name": "THE TERMINAL",
            "description": "v0.68 Dark Renaissance — navigation hub. Every door leads somewhere.",
            "version": "0.68",
            "port": self.port,
            "accent_color": "#3b82f6",
            "tags": ["hub", "navigation", "system", "terminal"],
            "skill_packs": ["hub"],
            "routes": ["/", "/api/scenes", "/api/world_state", "/api/economy", "/api/system", "/api/health"],
        }


def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> HubScene:
    """Factory for the launcher.

    Args:
        host: Bind address.
        port: Port number.

    Returns:
        Configured HubScene instance.
    """
    return HubScene(host=host, port=port)
