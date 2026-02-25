"""
Command Center Scene — War-room dashboard for real-time CosySim monitoring.

Displays:
- System metrics (CPU, RAM, GPU) with live charts
- Pipeline metrics (latency, TPS, kills, pre-warms)
- Alert status per node (green/yellow/red)
- Activity bus (current + recent history)
- Training data capture stats
- Live event feed
- **Live scene monitor** — cycle through all scenes, see chats/state/turns
- **Scene controls** — pause, resume, inject events, broadcast directives
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from engine.scenes.base_scene import BaseScene, get_all_active_scenes, get_active_scene
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

log = logging.getLogger(__name__)

SCENE_ID = "command_center"
DEFAULT_PORT = 5566


class CommandCenterScene(BaseScene, MCPSceneMixin, mcp_scene_id=SCENE_ID):
    """Real-time system observatory dashboard with live scene monitoring and control."""

    SCENE_METADATA = {
        "title": "Command Center",
        "description": "System observatory dashboard showing real-time metrics, pipeline status, "
                       "cross-scene activity, live scene monitoring, and remote scene control.",
        "genre": "system_monitoring",
        "max_characters": 0,
        "features": ["metrics_dashboard", "pipeline_monitoring", "cross_scene_view",
                     "alert_system", "event_feed", "scene_monitor", "scene_control",
                     "character_viewer"],
    }

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        scene_dir = Path(__file__).parent
        self.app = Flask(
            __name__,
            template_folder=str(scene_dir / "templates"),
            static_folder=str(scene_dir / "static"),
        )
        register_shared_assets(self.app)
        CORS(self.app)
        self.socketio = SocketIO(
            self.app, cors_allowed_origins="*", async_mode="threading"
        )

        super().__init__(name="command_center", host=host, port=port)

        self._collector = None
        self._metrics_db = None
        self._activity_bus = None
        self._ticker_thread: Optional[threading.Thread] = None
        self._running = False
        self._tick_interval = 1.0

        self._register_routes()
        self._register_scene_routes()
        self._register_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

        # Register monitoring rules
        try:
            from content.scenes.command_center.command_center_rules import register_command_center_rules
            register_command_center_rules()
        except Exception as exc:
            log.warning("Failed to register command center rules: %s", exc)

    # ------------------------------------------------------------------
    # Lazy accessors for singletons
    # ------------------------------------------------------------------

    def _get_collector(self):
        if self._collector is None:
            try:
                from engine.observability.metrics_collector import get_metrics_collector
                self._collector = get_metrics_collector()
            except Exception:
                log.debug("MetricsCollector not available")
        return self._collector

    def _get_metrics_db(self):
        if self._metrics_db is None:
            try:
                from engine.observability.metrics_db import get_metrics_db
                self._metrics_db = get_metrics_db()
            except Exception:
                log.debug("MetricsDB not available")
        return self._metrics_db

    def _get_activity_bus(self):
        if self._activity_bus is None:
            try:
                from engine.services.activity_bus import get_activity_bus
                self._activity_bus = get_activity_bus()
            except Exception:
                log.debug("ActivityBus not available")
        return self._activity_bus

    # ------------------------------------------------------------------
    # Data retrieval helpers
    # ------------------------------------------------------------------

    def _system_snapshot(self) -> Dict[str, Any]:
        """Current system metrics."""
        collector = self._get_collector()
        if collector and hasattr(collector, "last_system_snapshot"):
            snap = collector.last_system_snapshot
            if snap:
                return snap
        try:
            from engine.logging.monitor import get_system_monitor
            mon = get_system_monitor()
            return mon.snapshot() if mon else {}
        except Exception:
            return {}

    def _pipeline_snapshot(self) -> Dict[str, Any]:
        """Current pipeline metrics summary."""
        collector = self._get_collector()
        if collector and hasattr(collector, "last_pipeline_summary"):
            return collector.last_pipeline_summary or {}
        return {}

    def _alert_status(self) -> Dict[str, str]:
        """Node → green/yellow/red map."""
        collector = self._get_collector()
        if collector and hasattr(collector, "alert_engine"):
            eng = collector.alert_engine
            if eng:
                return eng.get_status_map()
        return {}

    def _recent_alerts(self, limit: int = 20) -> List[Dict]:
        """Recent alert history."""
        db = self._get_metrics_db()
        if db:
            try:
                return db.get_recent_alerts(limit=limit)
            except Exception:
                pass
        return []

    def _activity_snapshot(self) -> Dict[str, Any]:
        """Current + recent activity bus state."""
        bus = self._get_activity_bus()
        if bus:
            try:
                return bus.snapshot()
            except Exception:
                pass
        return {"current": [], "history": []}

    def _pipeline_history(self, seconds: int = 60, limit: int = 100) -> List[Dict]:
        """Recent pipeline metric records."""
        db = self._get_metrics_db()
        if db:
            try:
                since = time.time() - seconds
                return db.get_pipeline_history(since=since, limit=limit)
            except Exception:
                pass
        return []

    def _system_history(self, seconds: int = 60) -> List[Dict]:
        """Recent system metric records."""
        db = self._get_metrics_db()
        if db:
            try:
                since = time.time() - seconds
                return db.get_system_history(since=since)
            except Exception:
                pass
        return []

    def _training_stats(self) -> Dict[str, Any]:
        """Training data capture stats."""
        try:
            from engine.observability.training_capture import TrainingCapture
            cap = TrainingCapture.__dict__.get("_instance")
            if cap and hasattr(cap, "get_stats"):
                return cap.get_stats()
        except Exception:
            pass
        db = self._get_metrics_db()
        if db:
            try:
                candidates = db.get_training_candidates(limit=0)
                return {"total": 0, "datasets": {}}
            except Exception:
                pass
        return {"total": 0, "datasets": {}}

    def _benchmark_stats(self) -> Dict[str, Any]:
        """LLM KPI benchmarks."""
        try:
            from engine.logging.benchmark import get_benchmarks, get_llm_kpis
            return {
                "benchmarks": get_benchmarks(),
                "llm_kpis": get_llm_kpis(),
            }
        except Exception:
            return {"benchmarks": {}, "llm_kpis": {}}

    def _full_dashboard(self) -> Dict[str, Any]:
        """Complete dashboard state for initial load."""
        return {
            "system": self._system_snapshot(),
            "pipeline": self._pipeline_snapshot(),
            "alerts": self._alert_status(),
            "alert_history": self._recent_alerts(limit=10),
            "activity": self._activity_snapshot(),
            "training": self._training_stats(),
            "benchmarks": self._benchmark_stats(),
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _register_routes(self):
        app = self.app

        @app.route("/")
        def index():
            return render_template("command_center.html")

        @app.route("/api/dashboard")
        def api_dashboard():
            return jsonify(self._full_dashboard())

        @app.route("/api/system")
        def api_system():
            return jsonify(self._system_snapshot())

        @app.route("/api/pipeline")
        def api_pipeline():
            return jsonify(self._pipeline_snapshot())

        @app.route("/api/alerts")
        def api_alerts():
            return jsonify({
                "status": self._alert_status(),
                "history": self._recent_alerts(limit=20),
            })

        @app.route("/api/activity")
        def api_activity():
            return jsonify(self._activity_snapshot())

        @app.route("/api/pipeline/history")
        def api_pipeline_history():
            seconds = request.args.get("seconds", 60, type=int)
            limit = request.args.get("limit", 100, type=int)
            return jsonify(self._pipeline_history(seconds=seconds, limit=limit))

        @app.route("/api/system/history")
        def api_system_history():
            seconds = request.args.get("seconds", 60, type=int)
            return jsonify(self._system_history(seconds=seconds))

        @app.route("/api/benchmarks")
        def api_benchmarks():
            return jsonify(self._benchmark_stats())

        @app.route("/api/training")
        def api_training():
            return jsonify(self._training_stats())

        @app.route("/api/training/candidates")
        def api_training_candidates():
            db = self._get_metrics_db()
            if not db:
                return jsonify([])
            dataset = request.args.get("dataset")
            min_quality = request.args.get("min_quality", 0.0, type=float)
            limit = request.args.get("limit", 50, type=int)
            try:
                rows = db.get_training_candidates(
                    dataset=dataset,
                    min_quality=min_quality,
                    limit=limit,
                )
                return jsonify(rows)
            except Exception:
                return jsonify([])

        @app.route("/api/training/export", methods=["POST"])
        def api_training_export():
            """Export training candidates to JSONL."""
            data = request.get_json(silent=True) or {}
            dataset = data.get("dataset")
            min_quality = data.get("min_quality", 0.7)
            try:
                from training.prepare_from_live import prepare_dataset
                count = prepare_dataset(
                    dataset_name=dataset,
                    min_quality=min_quality,
                )
                return jsonify({"exported": count, "dataset": dataset})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

    # ------------------------------------------------------------------
    # Scene Monitoring + Control Routes
    # ------------------------------------------------------------------

    def _get_scene_summary(self, scene_id: str, scene_obj) -> Dict[str, Any]:
        """Build a compact status summary for a scene."""
        info: Dict[str, Any] = {
            "id": scene_id,
            "running": True,
            "port": getattr(scene_obj, "port", None),
        }

        # Metadata
        meta = getattr(scene_obj, "SCENE_METADATA", None)
        if meta:
            info["title"] = meta.get("title", scene_id)
            info["genre"] = meta.get("genre", "unknown")
        else:
            info["title"] = scene_id
            info["genre"] = "unknown"

        # Characters
        chars = []
        if hasattr(scene_obj, "characters"):
            chars = list(scene_obj.characters.keys()) if isinstance(scene_obj.characters, dict) else []
        elif hasattr(scene_obj, "_characters"):
            c = scene_obj._characters
            chars = list(c.keys()) if isinstance(c, dict) else []
        info["characters"] = chars
        info["character_count"] = len(chars)

        # State snapshot — extract key stats from scene state
        state_snap = {}
        state = getattr(scene_obj, "state", None) or getattr(scene_obj, "_state", None)
        if state:
            for attr in ("phase", "current_phase", "heat", "round_num", "turn",
                         "game_phase", "escalation_level", "score", "suspicion"):
                val = getattr(state, attr, None)
                if val is not None:
                    state_snap[attr] = val
            # Dict-like state
            if hasattr(state, "to_dict"):
                try:
                    d = state.to_dict()
                    for k in ("phase", "heat", "round", "turn", "score"):
                        if k in d and k not in state_snap:
                            state_snap[k] = d[k]
                except Exception:
                    pass
        info["state"] = state_snap

        # Heat from framework
        try:
            fw = get_framework()
            heat_data = fw.get_state(scene_id, "conversation_heat")
            if heat_data:
                info["heat"] = heat_data.get("level", 0)
        except Exception:
            pass

        # Last activity
        info["last_activity"] = time.time()
        return info

    def _get_scene_chat_feed(self, scene_id: str, limit: int = 10) -> List[Dict]:
        """Get recent chat messages from a scene via MCP framework narratives."""
        messages = []
        try:
            fw = get_framework()
            narratives = fw.get_state(scene_id, "narratives")
            if narratives and isinstance(narratives, list):
                for n in narratives[-limit:]:
                    messages.append({
                        "speaker": n.get("speaker", "system"),
                        "text": n.get("text", "")[:200],
                        "ts": n.get("ts", 0),
                    })
        except Exception:
            pass

        # Try EventChain as fallback
        if not messages:
            try:
                from content.simulation.database.events import get_event_chain
                ec = get_event_chain()
                events = ec.get_events(scene_id=scene_id, limit=limit)
                for e in events:
                    messages.append({
                        "speaker": e.get("actor", "system"),
                        "text": e.get("description", "")[:200],
                        "ts": e.get("timestamp", 0),
                    })
            except Exception:
                pass

        return messages

    def _get_character_details(self, char_id: str) -> Dict[str, Any]:
        """Get detailed character state from registry + database."""
        details: Dict[str, Any] = {"id": char_id}

        # From CharacterRegistry (live state)
        try:
            from engine.mcp.framework import get_framework
            fw = get_framework()
            char_state = fw.get_character_state(char_id)
            if char_state:
                details["mood"] = char_state.get("mood", "neutral")
                details["energy"] = char_state.get("energy", 100)
                details["stats"] = char_state.get("stats", {})
                details["flags"] = char_state.get("flags", [])
        except Exception:
            pass

        # From Database (persistent data)
        try:
            from content.simulation.database.db import Database
            db = Database()
            char = db.get_character(char_id)
            if char:
                details["name"] = char.get("name", char_id)
                details["age"] = char.get("age")
                details["sex"] = char.get("sex")
                details["personality_id"] = char.get("personality_id")
        except Exception:
            pass

        # From CharacterStateCoordinator
        try:
            from engine.mcp.character_state_coordinator import get_coordinator
            coord = get_coordinator()
            state = coord.get_state(char_id)
            if state:
                details.update({
                    "mood": state.get("mood", details.get("mood", "neutral")),
                    "energy": state.get("energy", details.get("energy", 100)),
                    "arousal": state.get("arousal", 0),
                    "inhibition": state.get("inhibition", 50),
                })
        except Exception:
            pass

        # Relationships
        try:
            from content.simulation.database.db import Database
            db = Database()
            rels = db.get_relationships(char_id)
            if rels:
                details["relationships"] = [
                    {"target": r.get("target_id"), "trust": r.get("trust", 0),
                     "attraction": r.get("attraction", 0)}
                    for r in rels[:10]
                ]
        except Exception:
            pass

        return details

    def _register_scene_routes(self):
        app = self.app

        @app.route("/api/scenes")
        def api_scenes():
            """List all active scenes with status summaries."""
            scenes = get_all_active_scenes()
            result = []
            for sid, sobj in scenes.items():
                if sid == SCENE_ID:
                    continue  # Skip self
                try:
                    result.append(self._get_scene_summary(sid, sobj))
                except Exception as exc:
                    result.append({"id": sid, "running": True, "error": str(exc)})
            return jsonify(result)

        @app.route("/api/scenes/<scene_id>")
        def api_scene_detail(scene_id: str):
            """Get detailed state for a specific scene."""
            scene = get_active_scene(scene_id)
            if not scene:
                return jsonify({"error": f"Scene '{scene_id}' not active"}), 404
            return jsonify(self._get_scene_summary(scene_id, scene))

        @app.route("/api/scenes/<scene_id>/feed")
        def api_scene_feed(scene_id: str):
            """Get recent chat messages from a scene."""
            limit = request.args.get("limit", 20, type=int)
            return jsonify(self._get_scene_chat_feed(scene_id, limit=limit))

        @app.route("/api/scenes/<scene_id>/characters")
        def api_scene_characters(scene_id: str):
            """Get character details for all characters in a scene."""
            scene = get_active_scene(scene_id)
            if not scene:
                return jsonify({"error": f"Scene '{scene_id}' not active"}), 404

            chars = []
            char_ids = []
            if hasattr(scene, "characters") and isinstance(scene.characters, dict):
                char_ids = list(scene.characters.keys())
            elif hasattr(scene, "_characters") and isinstance(scene._characters, dict):
                char_ids = list(scene._characters.keys())

            for cid in char_ids:
                chars.append(self._get_character_details(cid))
            return jsonify(chars)

        @app.route("/api/characters/<char_id>")
        def api_character_detail(char_id: str):
            """Get detailed state for a specific character."""
            return jsonify(self._get_character_details(char_id))

        @app.route("/api/characters/<char_id>/conversations")
        def api_character_conversations(char_id: str):
            """Get conversation history for a character."""
            limit = request.args.get("limit", 30, type=int)
            conversations = []
            try:
                from content.simulation.database.db import Database
                db = Database()
                convs = db.get_conversations(char_id, limit=limit)
                for c in (convs or []):
                    conversations.append({
                        "role": c.get("role", "unknown"),
                        "content": c.get("content", "")[:300],
                        "ts": c.get("timestamp", 0),
                    })
            except Exception:
                pass
            return jsonify(conversations)

        @app.route("/api/scenes/<scene_id>/inject", methods=["POST"])
        def api_scene_inject(scene_id: str):
            """Inject a narrative event or directive into a scene."""
            scene = get_active_scene(scene_id)
            if not scene:
                return jsonify({"error": f"Scene '{scene_id}' not active"}), 404

            data = request.get_json(silent=True) or {}
            event_type = data.get("type", "narrative")
            content = data.get("content", "")

            if not content:
                return jsonify({"error": "Missing 'content' field"}), 400

            try:
                fw = get_framework()
                if event_type == "narrative":
                    fw.emit_event(scene_id, "director_injection", {
                        "text": content, "source": "command_center"
                    })
                elif event_type == "directive":
                    from engine.mcp.dialog_system import get_dialog_system
                    ds = get_dialog_system()
                    ds.add_directive(scene_id, content, priority=10, ttl=60)
                elif event_type == "broadcast":
                    fw.emit_event(scene_id, "system_broadcast", {
                        "text": content, "source": "command_center"
                    })
                else:
                    return jsonify({"error": f"Unknown event type: {event_type}"}), 400

                log.info("Injected %s into %s: %s", event_type, scene_id, content[:80])
                return jsonify({"ok": True, "type": event_type, "scene": scene_id})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

        @app.route("/api/characters/<char_id>/edit_stats", methods=["POST"])
        def api_edit_character_stats(char_id: str):
            """Live-edit character stats."""
            data = request.get_json(silent=True) or {}
            if not data:
                return jsonify({"error": "No stats provided"}), 400

            try:
                from engine.mcp.character_state_coordinator import get_coordinator
                coord = get_coordinator()
                for key, value in data.items():
                    coord.update(char_id, key, value, persist=True)
                log.info("Edited stats for %s: %s", char_id, data)
                return jsonify({"ok": True, "char_id": char_id, "updated": data})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500

    def _register_socketio(self):
        @self.socketio.on("connect")
        def on_connect():
            emit("dashboard_state", self._full_dashboard())

        @self.socketio.on("request_refresh")
        def on_refresh():
            emit("dashboard_state", self._full_dashboard())

    # ------------------------------------------------------------------
    # Background ticker — broadcasts metrics via SocketIO
    # ------------------------------------------------------------------

    def _start_ticker(self):
        if self._ticker_thread and self._ticker_thread.is_alive():
            return
        self._running = True
        self._ticker_thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="cc-ticker"
        )
        self._ticker_thread.start()

    def _stop_ticker(self):
        self._running = False
        if self._ticker_thread:
            self._ticker_thread.join(timeout=3)
            self._ticker_thread = None

    def _tick_loop(self):
        """Broadcast metrics every tick_interval seconds."""
        tick_count = 0
        while self._running:
            try:
                self.socketio.emit("metric_system", self._system_snapshot())
                self.socketio.emit("metric_pipeline", self._pipeline_snapshot())
                self.socketio.emit("metric_alerts", self._alert_status())

                bus = self._get_activity_bus()
                if bus:
                    try:
                        snap = bus.snapshot()
                        self.socketio.emit("metric_activity", snap)
                    except Exception:
                        pass

                # Broadcast scene summaries every 3 ticks
                tick_count += 1
                if tick_count % 3 == 0:
                    try:
                        scenes = get_all_active_scenes()
                        summaries = []
                        for sid, sobj in scenes.items():
                            if sid == SCENE_ID:
                                continue
                            try:
                                summaries.append(self._get_scene_summary(sid, sobj))
                            except Exception:
                                summaries.append({"id": sid, "running": True})
                        self.socketio.emit("scene_updates", summaries)
                    except Exception:
                        pass

            except Exception as exc:
                log.debug("Command center tick error: %s", exc)

            time.sleep(self._tick_interval)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.register_health_route(self.app)

        # Wire MetricsCollector emit_fn to our SocketIO
        collector = self._get_collector()
        if collector and hasattr(collector, "emit_fn"):
            collector.emit_fn = lambda event, data: self.socketio.emit(event, data)

        self._start_ticker()
        log.info("Command Center starting on %s:%s", self.host, self.port)
        self.socketio.run(
            self.app,
            host=self.host,
            port=self.port,
            allow_unsafe_werkzeug=True,
        )

    def stop(self):
        self._stop_ticker()
        self._mcp_deregister_scene()
        log.info("Command Center stopped")

    def get_plugin_info(self) -> Dict[str, Any]:
        return {
            "name": "Command Center",
            "description": "Real-time system observatory — metrics, pipeline, alerts, "
                           "scene monitoring, character viewer, live control",
            "version": "2.0.0",
            "author": "CosySim",
            "port": self.port,
            "tags": ["dashboard", "metrics", "observatory", "training",
                     "scene_monitor", "scene_control", "character_viewer"],
            "skill_packs": ["command_center"],
        }
