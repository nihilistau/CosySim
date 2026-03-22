"""
FlaskScene — Unified base class for all CosySim Flask/SocketIO scenes.
======================================================================

Every interactive scene in CosySim should inherit from ``FlaskScene``
instead of manually wiring Flask, SocketIO, MCP, Nexus, and shared
assets.  This eliminates 6 different inheritance patterns and ensures
consistent startup, health checking, and shutdown across all scenes.

**Provides automatically:**
- Flask app + SocketIO (always ``async_mode="threading"``)
- Jinja2 ChoiceLoader for shared templates
- All standard routes (health, hud, announcer, inventory, shop, etc.)
- MCP framework registration (lazy, in ``start()``)
- Nexus integration (non-blocking background probe)
- World event subscriptions (after daemons are ready)
- Background ticker support
- Graceful shutdown with Nexus flush

**Subclass contract:**

.. code-block:: python

    class TavernScene(FlaskScene):
        SCENE_METADATA = {
            "name": "tavern",
            "display_name": "THE RUSTY ANCHOR",
            "port": 5558,
            "type": "adventure",
            "accent_color": "#92400e",
            "description": "Cheap ale. Cheaper lies.",
        }

        def __init__(self, host="0.0.0.0", port=5558):
            super().__init__(host=host, port=port)
            self.tavern_state = TavernState()
            self._register_tavern_routes()
            self._register_tavern_socketio()

        def on_before_serve(self):
            self._seed_quests()

Version: v1.51.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-22] — Initial FlaskScene: unified scene base class
                            replacing 6 inconsistent inheritance patterns
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
import jinja2

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)


# ──── FlaskScene ─────────────────────────────────────────────────────────

class FlaskScene(BaseScene, NexusSceneMixin):
    """Unified base class for all CosySim Flask/SocketIO scenes.

    CONNECTS: Flask, SocketIO, MCPFramework, NexusKMS, WorldSim
    CALLED BY: launcher.py _run_single(), TUI _start_one()
    EMITS: /health, /api/status, SocketIO events
    """

    # Subclasses MUST override with scene-specific metadata
    SCENE_METADATA: Dict[str, Any] = {}

    # ── Construction ─────────────────────────────────────────────────

    def __init__(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
        """Initialize the Flask scene.

        Creates Flask app, SocketIO, registers shared assets and all
        standard routes.  Subclasses should call ``super().__init__()``
        first, then register their own routes and SocketIO handlers.

        Args:
            host: Bind address (default ``0.0.0.0``).
            port: Bind port.  Falls back to ``SCENE_METADATA["port"]``
                  if not provided.
        """
        meta = self.__class__.SCENE_METADATA
        if not meta:
            raise ValueError(
                f"{self.__class__.__name__} must define SCENE_METADATA dict"
            )

        scene_name = meta["name"]
        if port is None:
            port = meta.get("port", 5555)

        super().__init__(scene_name=scene_name, host=host, port=port)

        # ── Auto-detect template/static dirs from scene file location ──
        try:
            scene_file = inspect.getfile(self.__class__)
            scene_dir = Path(scene_file).parent
        except (OSError, TypeError):
            # Fallback for dynamically defined classes (tests, REPL)
            scene_dir = Path.cwd()
        template_dir = scene_dir / "templates"
        static_dir = scene_dir / "static"

        # v1.51.0 — Flask app with SocketIO (always async_mode="threading")
        self.app = Flask(
            self.__class__.__module__,
            template_folder=str(template_dir) if template_dir.is_dir() else None,
            static_folder=str(static_dir) if static_dir.is_dir() else None,
        )
        CORS(self.app)

        # Jinja2 ChoiceLoader — scene templates + shared templates
        shared_tmpl = Path(__file__).resolve().parents[2] / "content" / "shared" / "templates"
        loaders = []
        if self.app.jinja_loader:
            loaders.append(self.app.jinja_loader)
        if shared_tmpl.is_dir():
            loaders.append(jinja2.FileSystemLoader(str(shared_tmpl)))
        if loaders:
            self.app.jinja_loader = jinja2.ChoiceLoader(loaders)

        # SocketIO — always threading mode for werkzeug compat in daemon threads
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins="*",
            async_mode="threading",
        )

        # Shared CSS/JS injection, navbar, assistant API, Nexus routes, etc.
        register_shared_assets(self.app)

        # Standard routes from BaseSceneRoutesMixin
        self._register_standard_routes()

        # Ticker support
        self._ticker_running: bool = False
        self._ticker_thread: Optional[threading.Thread] = None
        self._ticker_interval: float = 30.0

        logger.info(
            "%s created (FlaskScene) on %s:%d",
            meta.get("display_name", scene_name), host, port,
        )

    # ── Standard route registration ──────────────────────────────────
    # v1.51.0 [2026-03-22] — Registers all routes every scene needs

    def _register_standard_routes(self) -> None:
        """Register health, hud, and other standard API routes."""
        self.register_health_route(self.app)
        self.register_hud_route(self.app)
        self.register_inventory_route(self.app)
        self.register_tts_route(self.app)

    # ── Lifecycle: start() ───────────────────────────────────────────
    # v1.51.0 [2026-03-22] — Template method: connect → hook → serve

    def start(self) -> None:
        """Start the scene server.

        Sequence:
        1. Connect to MCP framework (lazy, non-blocking)
        2. Connect to Nexus KMS (background probe, non-blocking)
        3. Subscribe to world events (EventBus)
        4. Call ``on_before_serve()`` subclass hook
        5. Start optional ticker thread
        6. Run SocketIO server (blocking)
        """
        # v1.49.4 [2026-03-22] — Oracle: auto-initialize observability stack
        try:
            from engine.observability.oracle import ensure_initialized
            ensure_initialized()
        except Exception:
            pass  # Never block scene startup

        self._connect_mcp()
        self._connect_nexus()
        self._subscribe_world_events()

        # Subclass setup hook
        self.on_before_serve()

        # Optional background ticker
        if self._ticker_interval > 0 and hasattr(self, '_tick'):
            self._start_ticker()

        meta = self.__class__.SCENE_METADATA
        logger.info(
            "%s starting on %s:%d",
            meta.get("display_name", self.scene_name), self.host, self.port,
        )
        self.socketio.run(
            self.app,
            host=self.host,
            port=self.port,
            debug=False,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
        )

    def on_before_serve(self) -> None:
        """Subclass hook — called after MCP/Nexus/world are wired, before serve.

        Override to seed data, register MCP rules, start game timers, etc.
        """
        pass

    # ── Lifecycle: stop() ────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the scene gracefully."""
        self._stop_event.set()
        self._stop_ticker()
        self.on_shutdown()
        self.nexus_flush()
        self._mcp_deregister_scene()
        logger.info("%s stopped", self.scene_name)

    def on_shutdown(self) -> None:
        """Subclass hook — called during shutdown before Nexus flush.

        Override for scene-specific cleanup (cancel timers, save state, etc.).
        """
        pass

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return scene metadata for admin panel and hub discovery."""
        meta = self.__class__.SCENE_METADATA
        return {
            "name": meta.get("display_name", self.scene_name),
            "description": meta.get("description", ""),
            "version": meta.get("version", "1.0.0"),
            "author": "CosySim Team",
            "port": self.port,
            "type": meta.get("type", "scene"),
            "accent_color": meta.get("accent_color", "#06b6d4"),
            "tags": meta.get("tags", []),
            "skill_packs": meta.get("skill_packs", []),
            "url": f"http://localhost:{self.port}",
            "health_url": f"http://localhost:{self.port}/health",
        }

    # ── MCP connection (lazy, non-blocking) ──────────────────────────
    # v1.51.0 [2026-03-22] — Replaces MCPSceneMixin._mcp_init()

    def _connect_mcp(self) -> None:
        """Register with MCP framework.  Non-fatal if framework unavailable."""
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            self._mcp_scene_node = fw.get_scene(self.scene_name)
            fw.record_scene_visit(self.scene_name)
            logger.debug("FlaskScene: MCP wired for '%s'", self.scene_name)
        except Exception as exc:
            logger.debug("FlaskScene: MCP connection skipped: %s", exc)

    @property
    def mcp(self):
        """Lazy access to the MCP scene node."""
        node = getattr(self, "_mcp_scene_node", None)
        if node is None:
            self._connect_mcp()
            node = getattr(self, "_mcp_scene_node", None)
        return node

    # ── Nexus connection (non-blocking background probe) ─────────────
    # v1.51.0 [2026-03-22] — Background thread probe, zero blocking

    def _connect_nexus(self) -> None:
        """Start background Nexus availability probe.

        Sets ``self._nexus_available`` to True/False when the probe
        completes.  Meanwhile all ``nexus_*`` methods gracefully return
        empty results.
        """
        self._nexus_scene_id = self.scene_name
        self._nexus_client = None
        self._nexus_available = False
        self._nexus_event_buffer = []
        self._nexus_buffer_lock = threading.Lock()
        self._nexus_last_flush = 0.0
        self._nexus_flush_interval = 60.0

        def _probe():
            try:
                from engine.nexus.client import get_nexus_client
                import urllib.request
                import json as _json

                client = get_nexus_client()
                base = client._base_url
                req = urllib.request.Request(f"{base}/api/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = _json.loads(resp.read().decode())
                    if data.get("ok"):
                        self._nexus_client = client
                        self._nexus_available = True
                        logger.info("Nexus online for '%s'", self.scene_name)
                        return
            except Exception:
                pass
            self._nexus_available = False
            logger.debug("Nexus offline for '%s' — running without knowledge layer", self.scene_name)

        t = threading.Thread(target=_probe, daemon=True, name=f"nexus-probe-{self.scene_name}")
        t.start()

    # ── World event subscriptions ────────────────────────────────────

    def _subscribe_world_events(self) -> None:
        """Subscribe to standard world events via EventBus.

        Override ``on_world_tick()`` and ``on_time_change()`` in subclass
        to handle events.  Safe to call before WorldSim is running —
        subscriptions are registered and will fire when daemons start.
        """
        try:
            from engine.world.state import get_event_bus
            bus = get_event_bus()
            bus.subscribe("world.tick", self._on_world_tick_wrapper)
            bus.subscribe("world.time_change", self._on_time_change_wrapper)
            logger.debug("FlaskScene: %s subscribed to world events", self.scene_name)
        except Exception as exc:
            logger.debug("FlaskScene: world event subscription skipped: %s", exc)

        # v1.52.0 [2026-03-22] — Cross-scene arrival notifications
        # Subscribe to player_travel events to detect arrivals
        try:
            from engine.events.event_bus import get_event_bus as get_eb
            eb = get_eb()
            eb.subscribe("player_travel", self._on_player_travel_wrapper)
            logger.debug("FlaskScene: %s subscribed to player_travel", self.scene_name)
        except Exception as exc:
            logger.debug("FlaskScene: player_travel subscription skipped: %s", exc)

    # v1.52.0 [2026-03-22] — Cross-scene arrival notification
    # CONNECTS: city_map.travel(), EventBus player_travel
    # CALLED BY: EventBus when player travels to any scene

    def _on_player_travel_wrapper(self, data: Dict[str, Any]) -> None:
        """Handle player_travel event — call on_player_arrival if destination matches."""
        destination = (data or {}).get("to", "")
        display_name = (self.SCENE_METADATA or {}).get("display_name", "")
        if destination == display_name:
            from_location = data.get("from", "Unknown")
            try:
                self.on_player_arrival(from_location, data)
                # Also broadcast to all connected Socket.IO clients
                if hasattr(self, "socketio"):
                    self.socketio.emit("player_arrived", {
                        "from": from_location,
                        "to": destination,
                        "energy_cost": data.get("energy_cost", 0),
                        "heat_add": data.get("heat_add", 0),
                    })
            except Exception as exc:
                logger.debug("%s.on_player_arrival error: %s", self.scene_name, exc)

    def on_player_arrival(self, from_location: str, travel_data: Dict[str, Any]) -> None:
        """Subclass hook — called when a player arrives at this scene via travel.

        Override to greet the player, update NPC proximity, sync state, etc.

        Args:
            from_location: The scene the player traveled from.
            travel_data: Full travel event data (energy_cost, heat_add, etc.).
        """
        logger.info("%s: player arrived from %s", self.scene_name, from_location)

    def _on_world_tick_wrapper(self, data: Dict[str, Any]) -> None:
        """Internal wrapper — calls subclass on_world_tick if defined."""
        if hasattr(self, "on_world_tick"):
            try:
                self.on_world_tick(data)
            except Exception as exc:
                logger.debug("%s.on_world_tick error: %s", self.scene_name, exc)

    def _on_time_change_wrapper(self, data: Dict[str, Any]) -> None:
        """Internal wrapper — calls subclass on_time_change if defined."""
        if hasattr(self, "on_time_change"):
            try:
                self.on_time_change(data)
            except Exception as exc:
                logger.debug("%s.on_time_change error: %s", self.scene_name, exc)

    # ── Background ticker ────────────────────────────────────────────

    def _start_ticker(self) -> None:
        """Start the background ticker thread (calls ``self._tick()`` on interval)."""
        if self._ticker_running:
            return
        self._ticker_running = True
        self._ticker_thread = threading.Thread(
            target=self._ticker_loop, daemon=True,
            name=f"ticker-{self.scene_name}",
        )
        self._ticker_thread.start()

    def _ticker_loop(self) -> None:
        """Main ticker loop — runs until ``_stop_event`` is set."""
        import time
        while not self._stop_event.is_set():
            self._stop_event.wait(self._ticker_interval)
            if self._stop_event.is_set():
                break
            try:
                self._tick()
            except Exception as exc:
                logger.debug("%s ticker error: %s", self.scene_name, exc)

    def _tick(self) -> None:
        """Override in subclass for periodic background work."""
        pass

    def _stop_ticker(self) -> None:
        """Stop the background ticker."""
        self._ticker_running = False
        self._stop_event.set()
