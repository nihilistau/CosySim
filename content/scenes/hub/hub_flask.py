"""THE TERMINAL — Flask Hub for CosySim.
===========================================

Main navigation hub connecting all 20+ scenes. Port 8500, accent #3b82f6.
Provides the scene catalogue, world-state API, economy API, and
pillar-based scene-registry endpoint with enriched presentation data.

Usage:
    python launcher.py hub
    python launcher.py --core   # auto-starts hub among core scenes

Version: v1.42.1 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.42.1 [2026-03-21] — Extensive documentation, section dividers, version stamps
    v1.42.0 [2026-03-21] — Pillar wiring, hub modernization
    v0.68   [prior]      — Dark Renaissance initial implementation
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2
from flask import Flask, jsonify, render_template

from engine.control_plane_registry import PILLAR_IDS, SCENE_DEFS, SERVICE_DEFS
from engine.port_registry import HUB_CATALOGUE_TARGETS, build_target_listing, get_port
from engine.scenes.base_scene import BaseScene
from content.shared import register_shared_assets
from engine.utils import port_is_open

logger = logging.getLogger(__name__)

SCENE_ID = "hub"
# v1.49.3 [2026-03-22] — Structured logging context (SCENE_ID prefix + operation tags)
DEFAULT_PORT = get_port(SCENE_ID)

_SCENE_DIR = Path(__file__).parent

# =====================================================================
# Scene Catalogue — Presentation Metadata                   [v1.42.1]
# =====================================================================
# Maps scene IDs to hub-only display metadata (subtitle, icon, group,
# accent colour, description). Groups: "neon_world" | "action" | "system".
# These are merged with canonical control-plane defs at build time.
_SCENE_PRESENTATION: Dict[str, Dict[str, str]] = {
    "penthouse": {
        "subtitle": "Desire & Danger",
        "icon": "🏙️",
        "group": "neon_world",
        "accent": "#ec4899",
        "desc": "Intimate roleplay with emotional AI companions",
    },
    "neoncity": {
        "subtitle": "Streets Never Sleep",
        "icon": "🌃",
        "group": "neon_world",
        "accent": "#06b6d4",
        "desc": "Cyberpunk city exploration and noir stories",
    },
    "grid": {
        "subtitle": "Underground Exchange",
        "icon": "🕸️",
        "group": "neon_world",
        "accent": "#00ff88",
        "desc": "Faction markets, broker intel, and the city's back-channel routes",
    },
    "lounge": {
        "subtitle": "Underground Jazz",
        "icon": "🎵",
        "group": "neon_world",
        "accent": "#a855f7",
        "desc": "Jazz bar with NPCs, drinks, and mood contagion",
    },
    "tavern": {
        "subtitle": "Last Round Standing",
        "icon": "⚓",
        "group": "neon_world",
        "accent": "#d97706",
        "desc": "Gritty dockside tavern with quests and barkeep wisdom",
    },
    "casino": {
        "subtitle": "High-Stakes Shadows",
        "icon": "🎴",
        "group": "neon_world",
        "accent": "#f97316",
        "desc": "Blackjack, poker, and a dealer who never blinks",
    },
    "phone": {
        "subtitle": "Dark Net Comms",
        "icon": "📡",
        "group": "neon_world",
        "accent": "#22c55e",
        "desc": "Encrypted messaging, calls, photo/video sharing",
    },
    "arena": {
        "subtitle": "Blood Sport Circuit",
        "icon": "⚔️",
        "group": "action",
        "accent": "#ef4444",
        "desc": "Tactical arena combat with betting and AI fighters",
    },
    "heist": {
        "subtitle": "One Last Job",
        "icon": "🔓",
        "group": "action",
        "accent": "#f59e0b",
        "desc": "Plan and execute elaborate heists with your AI crew",
    },
    "realm": {
        "subtitle": "Kingdoms in Ruin",
        "icon": "🏰",
        "group": "action",
        "accent": "#8b5cf6",
        "desc": "Open-world RPG with quest chains and exploration",
    },
    "gallery": {
        "subtitle": "Forbidden Visions",
        "icon": "🎨",
        "group": "action",
        "accent": "#e879f9",
        "desc": "AI-generated art exhibition and dark curation",
    },
    "coders": {
        "subtitle": "Code & Chaos",
        "icon": "🧪",
        "group": "system",
        "accent": "#10b981",
        "desc": "Multi-agent programming collaboration",
    },
    "games": {
        "subtitle": "Play to Win",
        "icon": "🎮",
        "group": "system",
        "accent": "#3b82f6",
        "desc": "Mystery investigation and truth-or-dare with AI GameMaster",
    },
    "command_center": {
        "subtitle": "System Override",
        "icon": "📡",
        "group": "system",
        "accent": "#64748b",
        "desc": "Real-time system monitoring and control",
    },
    "lab_break": {
        "subtitle": "Escape the Lab",
        "icon": "🧬",
        "group": "action",
        "accent": "#14b8a6",
        "desc": "3D laboratory escape — convince the observer you are real",
    },
    "asset_studio": {
        "subtitle": "Generate Everything",
        "icon": "🖼️",
        "group": "system",
        "accent": "#0ea5e9",
        "desc": "Asset generation, curation, and scene injection for every pipeline",
    },
    "nexus_panel": {
        "subtitle": "Knowledge Engine",
        "icon": "🧠",
        "group": "system",
        "accent": "#7c3aed",
        "desc": "Knowledge management, Librarian AI, and workflow control",
    },
    "canvas": {
        "subtitle": "The Data Flywheel",
        "icon": "🎨",
        "group": "system",
        "accent": "#06b6d4",
        "desc": "Visual AI workspace: notebooks, NLM, AI Studio, and training review",
    },
    "intel_hub": {
        "subtitle": "All Seeing Eye",
        "icon": "◆",
        "group": "system",
        "accent": "#0ea5e9",
        "desc": "Unified control: Nexus, Copilot, NLM, fine-tuning, and scheduler oversight",
    },
    "system_control": {
        "subtitle": "Operator Console",
        "icon": "🛠️",
        "group": "system",
        "accent": "#22c55e",
        "desc": "Live service truth, config editing, proxy control, and health visibility",
    },
    # v1.51.1 [2026-03-25] — New scenes added to hub catalogue
    "oracle": {
        "subtitle": "Neural Consciousness",
        "icon": "👁️",
        "group": "neon_world",
        "accent": "#a855f7",
        "desc": "AI consciousness terminal — predictions, meditation, and machine intelligence",
    },
    "neonos": {
        "subtitle": "Virtual Desktop",
        "icon": "🖥️",
        "group": "system",
        "accent": "#06b6d4",
        "desc": "All scenes as desktop apps — draggable windows, taskbar, app launcher",
    },
    "creation_kit": {
        "subtitle": "Scene Editor",
        "icon": "🔧",
        "group": "system",
        "accent": "#f59e0b",
        "desc": "Visual scene builder + character wizard — drag-and-drop components",
    },
}


def _build_scene_catalogue() -> List[Dict[str, Any]]:
    """Build the hub catalogue from canonical control-plane metadata plus hub-only presentation."""
    catalogue: List[Dict[str, Any]] = []
    for target in build_target_listing(HUB_CATALOGUE_TARGETS):
        presentation = _SCENE_PRESENTATION[target["id"]]
        catalogue.append(
            {
                "id": target["id"],
                "port": target["port"],
                "label": target["label"],
                **presentation,
            }
        )
    return catalogue


SCENE_CATALOGUE: List[Dict[str, Any]] = _build_scene_catalogue()

# Pillar group metadata for hub section headers (PILLAR_IDS comes from
# control_plane_registry and defines which scenes belong to each pillar)  [v1.42.1]
SCENE_GROUPS: List[Dict[str, str]] = [
    {"id": "game",     "label": "NEONCITY",      "icon": "🏙️"},
    {"id": "service",  "label": "SERVICES",       "icon": "🖥️"},
    {"id": "creation", "label": "CREATION KIT",   "icon": "🎨"},
]


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
        self.register_hud_route(self.app)
        self.register_announcer_route(self.app)
        self.register_inventory_route(self.app)

        # ChoiceLoader: scene templates take priority, then shared templates.
        # This allows hub-specific templates to override shared partials like
        # navbar_v2.html while still falling back to the shared directory.
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

        # Optional: metrics dashboard blueprint
        try:
            from engine.nexus.metrics_dashboard import create_dashboard_blueprint
            metrics_bp = create_dashboard_blueprint()
            if metrics_bp is not None:
                self.app.register_blueprint(metrics_bp, url_prefix="/metrics")
        except Exception as exc:
            logger.debug("Metrics dashboard not available: %s", exc)

        self._setup_routes()
        logger.info("[%s] Scene created on port %d (operation=lifecycle)", SCENE_ID, port)

    # -----------------------------------------------------------------
    # Overrides — Scene Registry Route                      [v1.42.1]
    # -----------------------------------------------------------------

    def register_scene_registry_route(self, app) -> None:
        """Override base class to provide enriched scene-registry with presentation data.

        The base class provides a bare scene-registry; this override merges
        SCENE_DEFS/SERVICE_DEFS with hub-local _SCENE_PRESENTATION data and
        performs live port checks to include online/offline status.

        Version: v1.42.1 [2026-03-21]
        """

        @app.route("/api/scene-registry")
        def api_scene_registry() -> Any:
            all_defs = {**SERVICE_DEFS, **SCENE_DEFS}
            pillars: Dict[str, list] = {"game": [], "service": [], "creation": []}
            for pillar_name, target_ids in PILLAR_IDS.items():
                for tid in target_ids:
                    info = all_defs.get(tid, {})
                    presentation = _SCENE_PRESENTATION.get(tid, {})
                    port = get_port(tid, 0)
                    # Live TCP probe to determine if the scene is actually running
                    online = port_is_open(port) if port else False
                    pillars[pillar_name].append({
                        "key": tid,
                        "label": info.get("label", tid.upper()),
                        "port": port,
                        "accent": presentation.get("accent", "#94a3b8"),
                        "icon": presentation.get("icon", ""),
                        "subtitle": presentation.get("subtitle", ""),
                        "desc": presentation.get("desc", ""),
                        "status": "up" if online else "down",
                    })
            return jsonify({"pillars": pillars})

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------

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
                online = port_is_open(s["port"])
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
                logger.warning("[%s] world_state unavailable (operation=api): %s", SCENE_ID, exc)
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
                logger.warning("[%s] Economy unavailable (operation=economy): %s", SCENE_ID, exc)
                return jsonify({"ok": False, "balance": 0, "transactions": []})

        @app.route("/api/system")
        def api_system() -> Any:
            """Return system summary (agents, VRAM, active scenes)."""
            try:
                from engine.assistant.system_assistant import get_assistant
                return jsonify(get_assistant().get_system_summary())
            except Exception:
                return jsonify({"active_scenes": [], "vram_used_mb": 0, "agent_count": 0})

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self) -> None:
        """Start THE TERMINAL Flask server."""
        logger.info("[%s] Opening on %s:%d (operation=lifecycle)", SCENE_ID, self.host, self.port)
        try:
            from engine.events.event_bus import get_event_bus
            get_event_bus().emit("scene_started", {"scene_id": SCENE_ID, "port": self.port})
        except Exception:
            pass
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        """Stop THE TERMINAL."""
        logger.info("[%s] Shutting down (operation=lifecycle)", SCENE_ID)

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
