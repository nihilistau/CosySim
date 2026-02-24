"""
Command Center Scene — War-room dashboard for real-time CosySim monitoring.

Displays:
- System metrics (CPU, RAM, GPU) with live charts
- Pipeline metrics (latency, TPS, kills, pre-warms)
- Alert status per node (green/yellow/red)
- Activity bus (current + recent history)
- Training data capture stats
- Live event feed
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

from engine.scenes.base_scene import BaseScene
from engine.mcp.framework import MCPSceneMixin
from content.shared import register_shared_assets
from engine.mcp.scene_state import get_scene_state_manager
from engine.mcp.tag_registry import TagRegistry

log = logging.getLogger(__name__)

SCENE_ID = "command_center"
DEFAULT_PORT = 5566


class CommandCenterScene(BaseScene, MCPSceneMixin, mcp_scene_id=SCENE_ID):
    """Real-time system observatory dashboard."""

    SCENE_METADATA = {
        "title": "Command Center",
        "description": "System observatory dashboard showing real-time metrics, pipeline status, "
                       "and cross-scene activity.",
        "genre": "system_monitoring",
        "max_characters": 0,
        "features": ["metrics_dashboard", "pipeline_monitoring", "cross_scene_view",
                     "alert_system", "event_feed"],
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
        self._register_socketio()

        # Framework integration
        self._state_mgr = get_scene_state_manager()
        self._tag_registry = TagRegistry.get()

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
    # SocketIO
    # ------------------------------------------------------------------

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
            "description": "Real-time system observatory — metrics, pipeline, alerts, training",
            "version": "1.0.0",
            "author": "CosySim",
            "port": self.port,
            "tags": ["dashboard", "metrics", "observatory", "training"],
            "skill_packs": [],
        }
