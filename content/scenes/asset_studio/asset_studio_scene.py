"""Asset Studio scene — standalone and CosySim-integrated asset generation hub.

A full asset creation system with 9 tabs:
    LIBRARY | IMAGES | PORTRAITS | VOICE | VIDEO | ITEMS | SVG | AUDIO | SETTINGS

Can run standalone (``python launcher.py --scene asset_studio``) or be accessed
from the CosySim hub.  Feeds PortraitCache, emits ``asset_generated`` socket
events, and registers with MCPFramework for full system integration.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

from engine.scenes.base_scene import BaseScene
from engine.scenes.nexus_mixin import NexusSceneMixin
from engine.mcp.framework import MCPSceneMixin, get_framework
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

SCENE_ID = "asset_studio"
DEFAULT_PORT = 5568


class AssetStudioScene(BaseScene, MCPSceneMixin, NexusSceneMixin, mcp_scene_id="asset_studio"):
    """The Asset Studio — unified asset creation and management hub."""

    SCENE_METADATA = {
        "name": "asset_studio",
        "display_name": "ASSET STUDIO",
        "port": 5568,
        "type": "system",
        "accent_color": "#f59e0b",
        "accent_rgb": "245 158 11",
        "description": "Generate, manage, and export all CosySim assets in one place.",
        "features": [
            "image_generation", "portrait_generation", "voice_synthesis",
            "video_generation", "item_creation", "svg_generation",
            "audio_generation", "asset_library", "style_presets",
        ],
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        """Initialise the Asset Studio Flask app."""
        super().__init__(scene_name=SCENE_ID, host=host, port=port)
        self._mcp_init()

        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self.app.config["SECRET_KEY"] = "asset_studio_v1"
        CORS(self.app)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        register_shared_assets(self.app)

        self.mount_overlay(self.app, self.socketio)
        self.mount_skills_server(self.app)
        self.register_health_route(self.app)
        self.register_bench_route(self.app, self.socketio)
        self.register_tts_route(self.app)

        self._register_routes()
        self._register_socket_events()

    # ── Routes ────────────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register all HTTP routes."""
        app = self.app

        @app.route("/")
        def index() -> str:
            return render_template("asset_studio.html", scene_meta=self.SCENE_METADATA)

        # ── Asset generation endpoints ─────────────────────────────────────

        @app.route("/api/generate", methods=["POST"])
        def api_generate():
            data = request.get_json(force=True) or {}
            asset_type = data.pop("asset_type", "image")
            try:
                from engine.asset_studio import get_studio_core  # noqa: PLC0415
                result = get_studio_core().generate(asset_type, data)
                return jsonify(result)
            except Exception as exc:
                logger.exception("Generate endpoint error: %s", exc)
                return jsonify({"error": str(exc)}), 500

        # ── Asset library endpoints ────────────────────────────────────────

        @app.route("/api/library")
        def api_library():
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            lib = get_asset_library()
            asset_type = request.args.get("type")
            scene = request.args.get("scene")
            character_id = request.args.get("character_id")
            favorites = request.args.get("favorites") == "1"
            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))
            search = request.args.get("search")
            assets = lib.list_assets(
                asset_type=asset_type or None,
                scene=scene or None,
                character_id=character_id or None,
                favorites_only=favorites,
                limit=limit,
                offset=offset,
                search=search or None,
            )
            stats = lib.stats()
            return jsonify({"assets": assets, "stats": stats, "offset": offset})

        @app.route("/api/library/<asset_id>", methods=["DELETE"])
        def api_delete_asset(asset_id: str):
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            deleted = get_asset_library().delete(asset_id)
            return jsonify({"deleted": deleted})

        @app.route("/api/library/<asset_id>/favorite", methods=["POST"])
        def api_favorite_asset(asset_id: str):
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            new_state = get_asset_library().toggle_favorite(asset_id)
            return jsonify({"favorite": new_state})

        # ── Preset endpoints ───────────────────────────────────────────────

        @app.route("/api/presets")
        def api_presets():
            from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
            return jsonify({"presets": get_preset_manager().list_all()})

        @app.route("/api/presets", methods=["POST"])
        def api_save_preset():
            data = request.get_json(force=True) or {}
            from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
            try:
                preset = get_preset_manager().save_custom(data)
                return jsonify({"preset": preset.to_dict()})
            except Exception as exc:
                return jsonify({"error": str(exc)}), 400

        @app.route("/api/presets/<preset_id>", methods=["DELETE"])
        def api_delete_preset(preset_id: str):
            from engine.asset_studio.preset_manager import get_preset_manager  # noqa: PLC0415
            deleted = get_preset_manager().delete_custom(preset_id)
            return jsonify({"deleted": deleted})

        # ── Voice endpoints ────────────────────────────────────────────────

        @app.route("/api/voices")
        def api_voices():
            from engine.asset_studio.generators.voice_gen import VoiceGenerator  # noqa: PLC0415
            return jsonify(VoiceGenerator().list_voices())

        @app.route("/api/voices/design", methods=["POST"])
        def api_save_voice_design():
            data = request.get_json(force=True) or {}
            from engine.asset_studio.generators.voice_gen import VoiceGenerator  # noqa: PLC0415
            ok = VoiceGenerator().save_voice_design(
                character_id=data.get("character_id", ""),
                description=data.get("description", ""),
                model_size=data.get("model_size", "1.7b"),
            )
            return jsonify({"saved": ok})

        # ── Feature flags endpoint ─────────────────────────────────────────

        @app.route("/api/flags")
        def api_flags():
            from engine.asset_studio import get_studio_core  # noqa: PLC0415
            return jsonify(get_studio_core().get_flags())

        @app.route("/api/flags", methods=["POST"])
        def api_set_flags():
            data = request.get_json(force=True) or {}
            from engine.asset_studio import get_studio_core  # noqa: PLC0415
            core = get_studio_core()
            results = {}
            for key, val in data.items():
                results[key] = core.set_flag(key, bool(val))
            return jsonify(results)

        # ── Health ─────────────────────────────────────────────────────────

        @app.route("/api/studio/health")
        def api_studio_health():
            from engine.asset_studio import get_studio_core  # noqa: PLC0415
            return jsonify(get_studio_core().health())

        # ── Workflow endpoints ─────────────────────────────────────────────

        @app.route("/api/workflows")
        def api_workflows():
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            return jsonify({"workflows": wm.list_workflows()})

        @app.route("/api/models")
        def api_models():
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            return jsonify({
                "checkpoints": wm.get_models("checkpoints"),
                "loras": wm.get_models("loras"),
                "vae": wm.get_models("vae"),
                "upscale_models": wm.get_models("upscale_models"),
                "available": wm.is_available(),
            })

        @app.route("/api/upscale", methods=["POST"])
        def api_upscale():
            data = request.get_json(force=True) or {}
            if not data.get("image_path"):
                return jsonify({"error": "image_path required"}), 400
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            from engine.config import get_config as _cfg_fn  # noqa: PLC0415
            _cfg2 = _cfg_fn()
            save_dir = Path(_cfg2.get("art.output_dir", "data/art/output"))
            save_dir.mkdir(parents=True, exist_ok=True)
            result = get_workflow_manager().generate(
                "upscale_enhance", data, save_dir=save_dir, filename_prefix="upscaled"
            )
            return jsonify(result)

        @app.route("/api/studio/nodes")
        def api_studio_nodes():
            from engine.asset_studio.workflow_manager import get_workflow_manager  # noqa: PLC0415
            wm = get_workflow_manager()
            nodes = list(wm.get_available_nodes().keys()) if wm.is_available() else []
            return jsonify({"nodes": nodes, "count": len(nodes), "available": wm.is_available()})

        # ── Tuning endpoints ───────────────────────────────────────────────

        @app.route("/api/tuning/profiles")
        def api_tuning_profiles():
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            return jsonify({"profiles": get_tuning_engine().get_profiles()})

        @app.route("/api/tuning/profiles/<profile_id>")
        def api_tuning_profile(profile_id: str):
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            p = get_tuning_engine().get_profile(profile_id)
            if not p:
                return jsonify({"error": "Profile not found"}), 404
            return jsonify({"profile": p})

        @app.route("/api/tuning/profiles", methods=["POST"])
        def api_save_tuning_profile():
            data = request.get_json(force=True) or {}
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            try:
                profile = get_tuning_engine().save_profile(
                    profile_id=data["profile_id"],
                    label=data.get("label", data["profile_id"]),
                    workflow_id=data["workflow_id"],
                    description=data.get("description", ""),
                    params=data.get("params", {}),
                    vl_score=data.get("vl_score"),
                    gen_time_ms=data.get("gen_time_ms"),
                )
                return jsonify({"profile": profile})
            except KeyError as exc:
                return jsonify({"error": f"Missing field: {exc}"}), 400

        @app.route("/api/tuning/profiles/<profile_id>", methods=["DELETE"])
        def api_delete_tuning_profile(profile_id: str):
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            deleted = get_tuning_engine().delete_profile(profile_id)
            return jsonify({"deleted": deleted})

        @app.route("/api/tuning/run", methods=["POST"])
        def api_tuning_run():
            data = request.get_json(force=True) or {}
            workflow_id = data.get("workflow_id", "portrait_fast")
            prompt = data.get("prompt", "masterpiece, best quality, portrait photograph")
            base_params = data.get("base_params", {})
            sweep = data.get("sweep", {})
            use_vl_qc = data.get("use_vl_qc", True)

            # Limit variants to prevent runaway jobs
            from engine.asset_studio.tuning_engine import get_tuning_engine, TuningEngine  # noqa: PLC0415
            engine = get_tuning_engine()
            variants = TuningEngine.build_variants(base_params, sweep)
            if len(variants) > 20:
                return jsonify({"error": "Max 20 variants per run (got {})".format(len(variants))}), 400

            def _push(job_dict: dict) -> None:
                self.socketio.emit("tuning_progress", job_dict)

            job_id = engine.submit_benchmark(
                workflow_id=workflow_id,
                prompt=prompt,
                base_params=base_params,
                sweep=sweep,
                use_vl_qc=use_vl_qc,
                progress_callback=_push,
            )
            return jsonify({"job_id": job_id, "variants": len(variants)})

        @app.route("/api/tuning/status")
        def api_tuning_status():
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            status = get_tuning_engine().get_job_status()
            return jsonify(status or {"status": "idle"})

        @app.route("/api/tuning/cancel", methods=["POST"])
        def api_tuning_cancel():
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            cancelled = get_tuning_engine().cancel_job()
            return jsonify({"cancelled": cancelled})

        @app.route("/api/tuning/metrics")
        def api_tuning_metrics():
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            workflow_id = request.args.get("workflow_id") or None
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
            min_score = float(request.args.get("min_score")) if request.args.get("min_score") else None
            return jsonify(get_tuning_engine().get_metrics(workflow_id, limit, offset, min_score))

        @app.route("/api/tuning/best")
        def api_tuning_best():
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            workflow_id = request.args.get("workflow_id", "portrait_fast")
            top_n = int(request.args.get("top_n", 5))
            return jsonify({"results": get_tuning_engine().get_best_settings(workflow_id, top_n)})

        @app.route("/api/inject_to_scene", methods=["POST"])
        def api_inject_to_scene():
            """Inject a generated asset into a scene's static folder.

            Expects JSON: {scene, asset_url, image_type, filename (optional)}
            Copies the asset to content/scenes/{scene}/static/img/{filename}
            and emits scene_asset_updated via SocketIO.
            """
            data = request.get_json() or {}
            scene = data.get("scene", "")
            asset_url = data.get("asset_url", "")
            image_type = data.get("image_type", "background")
            filename = data.get("filename", f"{image_type}_injected.png")

            if not scene or not asset_url:
                return jsonify({"status": "error", "message": "scene and asset_url are required"}), 400

            # Resolve source file from URL
            # asset_url could be /asset_studio/output/image.png or a relative path
            output_dir = Path("data/asset_studio/images")
            source_filename = Path(asset_url).name
            source_path = output_dir / source_filename

            if not source_path.exists():
                return jsonify({"status": "error", "message": f"Asset not found: {source_filename}"}), 404

            # Ensure target dir exists
            target_dir = Path(f"content/scenes/{scene}/static/img")
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / filename

            import shutil
            shutil.copy2(str(source_path), str(target_path))

            flask_url = f"/scenes/{scene}/static/img/{filename}"

            # Emit scene_asset_updated for live reload
            try:
                self.socketio.emit("scene_asset_updated", {
                    "scene": scene,
                    "image_type": image_type,
                    "url": flask_url,
                    "filename": filename,
                })
            except Exception:
                pass

            logger.info("Injected %s → %s", source_filename, target_path)
            return jsonify({
                "status": "ok",
                "scene": scene,
                "url": flask_url,
                "filename": filename,
            })

        @app.route("/api/scenes/list")
        def api_scenes_list():
            """List available scenes for inject-to-scene dropdown."""
            scenes = [
                {"id": "bedroom", "name": "THE PENTHOUSE", "port": 5555},
                {"id": "phone", "name": "SIGNAL", "port": 5556},
                {"id": "lounge", "name": "THE VELVET PIT", "port": 5557},
                {"id": "tavern", "name": "THE RUSTY ANCHOR", "port": 5558},
                {"id": "casino", "name": "CLUB NOIR", "port": 5559},
                {"id": "gallery", "name": "THE OBSCURA", "port": 5560},
                {"id": "arena", "name": "THE COLOSSEUM", "port": 5561},
                {"id": "realm", "name": "THE SHATTERED THRONE", "port": 5562},
                {"id": "neoncity", "name": "NEON CITY", "port": 5563},
            ]
            return jsonify({"status": "ok", "scenes": scenes})


        @app.route("/asset_studio/voice/<path:filename>")
        def serve_voice(filename: str):
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
            d = Path(cfg.get("asset_studio.voice_output_dir", "data/asset_studio/voice"))
            return send_from_directory(str(d), filename)

        @app.route("/asset_studio/svg/<path:filename>")
        def serve_svg(filename: str):
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
            d = Path(cfg.get("asset_studio.svg_output_dir", "data/asset_studio/svg"))
            return send_from_directory(str(d), filename)

        @app.route("/asset_studio/audio/<path:filename>")
        def serve_audio(filename: str):
            from engine.config import get_config  # noqa: PLC0415
            cfg = get_config()
            d = Path(cfg.get("asset_studio.audio_output_dir", "data/asset_studio/audio"))
            return send_from_directory(str(d), filename)

    # ── Socket events ─────────────────────────────────────────────────────────

    def _register_socket_events(self) -> None:
        """Register SocketIO event handlers."""
        sio = self.socketio

        @sio.on("connect")
        def on_connect():
            logger.debug("Asset Studio client connected")
            from engine.asset_studio import get_studio_core  # noqa: PLC0415
            sio.emit("studio_health", get_studio_core().health())

        @sio.on("generate_asset")
        def on_generate_asset(data: Dict[str, Any]):
            asset_type = data.pop("asset_type", "image")
            try:
                from engine.asset_studio import get_studio_core  # noqa: PLC0415
                result = get_studio_core().generate(asset_type, data)
                sio.emit("asset_generated", result)
            except Exception as exc:
                sio.emit("asset_error", {"error": str(exc)})

        @sio.on("request_library")
        def on_request_library(data: Dict[str, Any]):
            from engine.asset_studio.asset_library import get_asset_library  # noqa: PLC0415
            lib = get_asset_library()
            assets = lib.list_assets(
                asset_type=data.get("type"),
                limit=data.get("limit", 100),
                offset=data.get("offset", 0),
            )
            sio.emit("library_data", {"assets": assets, "stats": lib.stats()})

        @sio.on("cancel_benchmark")
        def on_cancel_benchmark(_data: Any = None):
            from engine.asset_studio.tuning_engine import get_tuning_engine  # noqa: PLC0415
            get_tuning_engine().cancel_job()
            sio.emit("tuning_progress", {"status": "cancelled"})

    # ── BaseScene interface ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the Asset Studio Flask server."""
        try:
            from engine.mcp.framework import get_framework  # noqa: PLC0415
            fw = get_framework()
            fw.get_or_create(f"scenes.{SCENE_ID}")
        except Exception as exc:
            logger.warning("MCP framework not available: %s", exc)
        try:
            from content.scenes.asset_studio import asset_studio_skills  # noqa: PLC0415, F401
        except Exception as exc:
            logger.debug("Could not import asset_studio_skills: %s", exc)
        logger.info("Asset Studio starting on port %d", self.port)
        self.socketio.run(self.app, host=self.host, port=self.port,
                          allow_unsafe_werkzeug=True)

    def stop(self) -> None:
        """Stop the scene."""
        logger.info("Asset Studio stopped")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return plugin metadata for hub discovery."""
        return {
            **self.SCENE_METADATA,
            "url": f"http://localhost:{self.port}",
            "health_url": f"http://localhost:{self.port}/health",
        }
