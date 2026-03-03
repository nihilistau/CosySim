"""
BaseScene — Abstract base for all CosySim scenes.
==================================================

Provides a standard contract every scene inherits:

* **Character management** — load / unload / list from asset system
* **Scene persistence** — save_scene / load_scene
* **Discovery** — get_plugin_info(), get_health(), get_skill_packs()
* **Lifecycle hooks** — on_scene_loaded, on_character_added, on_character_removed

Concrete scenes must implement ``start()``, ``stop()``, and
``get_plugin_info()`` at minimum.

Usage::

    class MyScene(BaseScene):
        def start(self):   ...
        def stop(self):    ...
        def get_plugin_info(self): return {...}
"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Any
from pathlib import Path
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from content.simulation.character_system.character import Character

import sys
from engine.paths import ROOT as _proj_root
sys.path.insert(0, str(_proj_root))

from engine.assets import AssetManager, CharacterAsset, SceneAsset

import logging as _logging
_bslogger = _logging.getLogger(__name__)

# ── In-process scene instance registry ──
# Skills and other subsystems can look up the running scene instance via
# ``get_active_scene("realm")`` without needing a singleton pattern.
_ACTIVE_SCENES: Dict[str, "BaseScene"] = {}


def get_active_scene(scene_name: str) -> Optional["BaseScene"]:
    """Return the running scene instance for *scene_name*, or ``None``."""
    return _ACTIVE_SCENES.get(scene_name)


def get_all_active_scenes() -> Dict[str, "BaseScene"]:
    """Return a snapshot of all currently registered scene instances."""
    return dict(_ACTIVE_SCENES)


class BaseScene(ABC):
    """
    Abstract base class for all scenes
    
    Provides:
    - Asset management integration
    - Character loading from assets
    - Scene save/load functionality
    - Common scene lifecycle methods
    """
    
    def __init__(self, scene_name: str, host: str = "0.0.0.0", port: int = 5000):
        """
        Initialize base scene
        
        Args:
            scene_name: Unique name for this scene
            host: Host to bind to
            port: Port to listen on
        """
        self.scene_name = scene_name
        self.host = host
        self.port = port
        
        # Asset manager for all assets
        self.asset_manager = AssetManager()
        
        # Active characters in this scene
        self.active_characters: Dict[str, CharacterAsset] = {}
        
        # Scene configuration
        self.scene_config: Dict[str, Any] = {
            'name': scene_name,
            'created_at': datetime.now().isoformat(),
            'characters': [],
            'settings': {}
        }
        
        # Scene asset ID (if loaded from asset)
        self.scene_asset_id: Optional[str] = None
        
        # v2.7: streaming support
        self.streaming_enabled: bool = True
        self._active_streams: int = 0
        self._total_stream_tokens: int = 0

        # Scene metadata — subclasses override SCENE_METADATA for rich description
        self.scene_metadata: Dict[str, Any] = getattr(self.__class__, "SCENE_METADATA", {
            "title": scene_name.replace("_", " ").title(),
            "description": "",
            "genre": "general",
            "max_characters": 5,
            "features": [],
        })

        # Register this scene with MCPFramework (best-effort)
        self._mcp_register_scene()

        # Register in the in-process lookup table
        _ACTIVE_SCENES[scene_name] = self
    
    def load_character(self, character_id: str) -> CharacterAsset:
        """
        Load a character from assets and fire on_character_added hook.
        """
        character = self.asset_manager.load('character', character_id)
        self.active_characters[character_id] = character
        
        if character_id not in self.scene_config['characters']:
            self.scene_config['characters'].append(character_id)
        
        # Fire lifecycle hook
        self.on_character_added(character)
        return character
    
    def unload_character(self, character_id: str) -> None:
        """Remove character from scene and fire on_character_removed hook."""
        if character_id in self.active_characters:
            del self.active_characters[character_id]
            if character_id in self.scene_config['characters']:
                self.scene_config['characters'].remove(character_id)
            self.on_character_removed(character_id)
    
    def get_character(self, character_id: str) -> Optional[CharacterAsset]:
        """Get active character by ID"""
        return self.active_characters.get(character_id)
    
    def list_characters(self) -> List[CharacterAsset]:
        """Get all active characters"""
        return list(self.active_characters.values())
    
    def save_scene(self, name: Optional[str] = None) -> str:
        """
        Save current scene state as an asset
        
        Args:
            name: Optional scene name (defaults to scene_name)
            
        Returns:
            Scene asset ID
        """
        scene_name = name or self.scene_name
        
        # Create scene asset
        scene_data = {
            'name': scene_name,
            'type': self.__class__.__name__,
            'host': self.host,
            'port': self.port,
            'characters': list(self.active_characters.keys()),
            'config': self.scene_config.get('settings', {}),
            'template': None,
            'dependencies': list(self.active_characters.keys())
        }
        
        # Create or update scene asset
        scene_asset = SceneAsset(**scene_data)
        scene_asset_id = self.asset_manager.save(scene_asset)
        
        self.scene_asset_id = scene_asset_id
        return scene_asset_id
    
    def load_scene(self, scene_id: str) -> None:
        """
        Load scene from asset
        
        Args:
            scene_id: Scene asset ID
        """
        scene_asset = self.asset_manager.load('scene', scene_id)
        
        # Load all characters
        for char_id in scene_asset.characters:
            try:
                self.load_character(char_id)
            except Exception as e:
                logger.warning(f"Could not load character {char_id}: {e}", exc_info=True)

        # Apply scene configuration
        self.scene_config['settings'] = scene_asset.config
        self.scene_asset_id = scene_id

        # Register with MCPFramework
        try:
            from engine.mcp.framework import get_framework
            get_framework().get_scene(scene_asset.name)
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

        # Call scene-specific load logic
        self.on_scene_loaded(scene_asset)
    
    def export_scene(self, export_path: Path) -> None:
        """
        Export scene and all dependencies
        
        Args:
            export_path: Directory to export to
        """
        raise NotImplementedError(
            "Scene export is not yet implemented. "
            "AssetManager needs export_asset() method — see plan Phase 1.8."
        )
    
    def import_scene(self, import_path: Path) -> str:
        """
        Import scene from export
        
        Args:
            import_path: Path to scene JSON file
            
        Returns:
            Imported scene asset ID
        """
        raise NotImplementedError(
            "Scene import is not yet implemented. "
            "AssetManager needs import_asset() method — see plan Phase 1.8."
        )

    def _asset_to_character(self, char_asset: CharacterAsset) -> 'Character':
        """
        Convert a CharacterAsset to a Character DB object.

        Uses the CharacterAsset.to_character() bridge (Phase 3) which:
        - Tries to load an existing DB row by asset ID
        - Creates a new row seeded from asset attributes if none found
        - Returns the loaded Character instance

        Requires the scene to have a ``self.db`` attribute (Database instance).
        Falls back gracefully if db is not yet available.

        Args:
            char_asset: CharacterAsset to convert

        Returns:
            Character instance ready for services / LLM calls
        """
        db = getattr(self, 'db', None)
        return char_asset.to_character(db)

    # ============= ABSTRACT METHODS =============

    @abstractmethod
    def start(self) -> None:
        """Start the scene (Flask app, Streamlit, etc.)"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the scene and persist character state to database."""
        try:
            from engine.mcp.character_registry import get_character_registry
            get_character_registry().persist_to_db()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)

    @abstractmethod
    def get_plugin_info(self) -> Dict[str, Any]:
        """
        Return scene metadata consumed by the admin panel and launcher.

        Every concrete scene **must** implement this to be discoverable.

        Returns a dict with at minimum::

            {
                "name":        str,          # human-readable scene name
                "description": str,          # one-line description
                "version":     str,          # semver string, e.g. "1.0.0"
                "author":      str,
                "port":        int,          # HTTP port this scene binds to
                "tags":        List[str],    # e.g. ["phone", "character", "chat"]
                "skill_packs": List[str],    # skill pack names the scene uses
                "routes":      List[Dict],   # [{"path": "/api/...", "methods": [...], "description": "..."}]
            }

        The admin panel calls ``get_plugin_info()`` on each loaded scene to
        populate the scene registry and skill-pack cross-reference table.
        """
        pass

    # ============= PLUGIN HOOKS =============

    def get_skill_packs(self) -> List[str]:
        """
        Return the list of skill pack names this scene exposes.

        Override in subclass to advertise skills.  Defaults to empty list
        (scene uses no tools).  The base implementation reads
        ``get_plugin_info()["skill_packs"]`` when available.

        Returns:
            List of pack name strings understood by SKILL_REGISTRY.
        """
        try:
            return self.get_plugin_info().get("skill_packs", [])
        except NotImplementedError:
            return []

    def get_health(self) -> Dict[str, Any]:
        """
        Return a health-check dict for the admin panel and hub.

        Includes system metrics from the monitor when available.
        Subclasses can override to add service-level checks.
        """
        health = {
            "ok": True,
            "scene": self.scene_name,
            "port": self.port,
            "characters": len(self.active_characters),
            "streaming_enabled": self.streaming_enabled,
            "active_streams": self._active_streams,
            "total_stream_tokens": self._total_stream_tokens,
        }
        try:
            from engine.logging import get_system_monitor
            monitor = get_system_monitor()
            health["system"] = monitor.snapshot()
        except Exception:
            logger.debug("Suppressed exception", exc_info=True)
        return health

    def register_health_route(self, app) -> None:
        """Register ``/api/health`` on a Flask app.

        Also automatically registers character info routes
        (``/api/character/relationship/<name>`` and
        ``/api/character/backstory/<name>``) so the portrait overlay works
        without additional scene-level wiring.

        Call this in ``start()`` after creating the Flask app::

            self.register_health_route(self.app)
        """
        import json as _json
        from flask import Response

        @app.route("/api/health")
        def _health():
            return Response(
                _json.dumps(self.get_health()),
                mimetype="application/json",
            )

        # Auto-wire portrait overlay character routes
        self.register_character_routes(app)

    def register_character_routes(self, app) -> None:
        """Register character info API routes used by the portrait overlay.

        Routes registered:
        * ``GET /api/character/relationship/<name>`` — returns tier + score for
          the named character from PlayerProfile.
        * ``GET /api/character/backstory/<name>`` — returns backstory text (if any).

        Call this in ``start()`` alongside ``register_health_route``::

            self.register_character_routes(self.app)
        """
        import json as _json
        from flask import Response

        @app.route("/api/character/relationship/<path:char_name>")
        def _char_relationship(char_name: str):
            data: dict = {"name": char_name, "tier": "STRANGER", "score": 0.0}
            try:
                from engine.characters.player_profile import get_player_profile
                from engine.agents.relationship_interceptor import _relationship_tier
                profile = get_player_profile()
                rel = profile.relationships.get(char_name.lower())
                if rel is not None:
                    tier = _relationship_tier(rel.score)
                    data["tier"] = tier
                    data["score"] = rel.score
            except Exception as _exc:
                _bslogger.debug("character/relationship unavailable: %s", _exc)
            return Response(_json.dumps(data), mimetype="application/json")

        @app.route("/api/character/backstory/<path:char_name>")
        def _char_backstory(char_name: str):
            data: dict = {"name": char_name, "backstory": ""}
            try:
                from engine.mcp.character_registry import get_character_registry
                char = get_character_registry().get_character(char_name.lower())
                if char and hasattr(char, "backstory"):
                    data["backstory"] = char.backstory or ""
            except Exception as _exc:
                _bslogger.debug("character/backstory unavailable: %s", _exc)
            return Response(_json.dumps(data), mimetype="application/json")

    def register_hud_route(self, app) -> None:
        """Register ``/api/hud/state`` on a Flask app.

        Returns player state, world time, active events, and weather —
        everything the Neon HUD needs in a single round-trip.

        Call this in ``start()`` after creating the Flask app::

            self.register_hud_route(self.app)
        """
        import json as _json
        import time as _time
        from flask import Response

        scene_ref = self

        @app.route("/api/hud/state")
        def _hud_state():
            data: dict = {}

            # Player state
            try:
                from engine.world.player_state import get_player_state
                ps = get_player_state()
                data.update(ps.to_dict())
            except Exception as _exc:
                _bslogger.debug("HUD: player_state unavailable: %s", _exc)
                data.setdefault("credits", 5000)
                data.setdefault("reputation", 50)
                data.setdefault("heat", 0)
                data.setdefault("faction_standings", {})
                data.setdefault("active_location", "NEON CITY")

            # World time
            try:
                from engine.world.world_state import get_world_state
                ws = get_world_state()
                wt = ws.get_time()
                data["world_time"] = f"Day {wt.game_day}  {wt.game_hour:02d}:00"
                data["time_of_day"] = wt.time_of_day
                # Weather for current scene
                weather = ws.get_weather(scene_ref.scene_name)
                if weather and hasattr(weather, "value"):
                    data["weather"] = weather.value
            except Exception as _exc:
                _bslogger.debug("HUD: world_state unavailable: %s", _exc)
                data.setdefault("world_time", "Day 1  00:00")

            # Active world events (up to 3)
            try:
                from engine.world.world_state import get_world_state
                ws = get_world_state()
                active = [
                    {"id": e.id, "title": e.name, "type": e.event_type, "scene": e.scene}
                    for e in ws.get_active_events()[:3]
                ]
                data["active_events"] = active
            except Exception as _exc:
                _bslogger.debug("HUD: active_events unavailable: %s", _exc)
                data.setdefault("active_events", [])

            data["scene"] = scene_ref.scene_name
            data["updated_at"] = int(_time.time() * 1000)
            return Response(_json.dumps(data), mimetype="application/json")

    def register_bench_route(self, app, socketio=None) -> None:
        """Register ``/api/bench/metrics`` on a Flask app.

        Provides live benchmark data for the Benchmark HUD (cosysim-bench.js).
        Call this in ``start()`` after creating the Flask app.
        If *socketio* is provided, also sets up ``bench:update`` emission
        after each agent reply so the HUD gets real-time pushes.
        """
        import json as _json
        import time as _time
        from flask import Response

        scene_ref = self

        # Guard: only register the route once per Flask app instance
        if not getattr(app, "_bench_route_registered", False):
            app._bench_route_registered = True  # type: ignore[attr-defined]

            @app.route("/api/bench/metrics")
            def _bench_metrics():
                data = scene_ref._collect_bench_metrics()
                return Response(_json.dumps(data), mimetype="application/json")

        if socketio:
            # Expose a helper so scenes can push updates after agent replies
            def _emit_bench(data: dict) -> None:
                try:
                    socketio.emit("bench:update", data)
                except Exception:
                    pass
            scene_ref._emit_bench = _emit_bench

    def _collect_bench_metrics(self) -> dict:
        """Collect current benchmark metrics for the HUD endpoint."""
        import time as _time

        metrics: dict = {
            "response_ms": getattr(self, "_last_response_ms", 0),
            "model_id": getattr(self, "_last_model_id", None),
            "tts_ms": getattr(self, "_last_tts_ms", 0),
            "nexus_tier": getattr(self, "_last_nexus_tier", "none"),
            "tokens_in": getattr(self, "_last_tokens_in", 0),
            "tokens_out": getattr(self, "_last_tokens_out", 0),
            "consequences_pending": 0,
            "economy_balance": None,
            "world_time": None,
            "active_events": [],
            "scene": getattr(self, "scene_name", None),
            "updated_at": int(_time.time() * 1000),
        }

        # Economy balance
        try:
            from engine.economy.economy import get_economy_manager
            mgr = get_economy_manager()
            metrics["economy_balance"] = mgr.get_balance("player")
        except Exception:
            pass

        # Consequences pending
        try:
            from engine.mechanics.consequences import get_consequence_store
            store = get_consequence_store()
            due = store.poll(scene=getattr(self, "scene_name", None), peek=True)
            metrics["consequences_pending"] = len(due)
        except Exception:
            pass

        # World time
        try:
            from engine.world.world_state import get_world_state
            ws = get_world_state()
            wt = ws.get_time()
            metrics["world_time"] = f"D{wt.day} {wt.hour:02d}:{wt.minute:02d}"
            metrics["active_events"] = [
                {"id": e.id, "title": e.title}
                for e in ws.get_active_events()[:3]
            ]
        except Exception:
            pass

        return metrics

    def record_bench(
        self,
        response_ms: int = 0,
        model_id: str = None,
        tts_ms: int = 0,
        nexus_tier: str = "none",
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record benchmark data from an agent reply.

        Call this after processing an agent response to feed the Benchmark HUD.
        Then push via Socket.IO if registered::

            self.record_bench(response_ms=420, model_id='qwen3-4b', nexus_tier='cache')
        """
        self._last_response_ms = response_ms
        if model_id:
            self._last_model_id = model_id
        if tts_ms:
            self._last_tts_ms = tts_ms
        if nexus_tier:
            self._last_nexus_tier = nexus_tier
        if tokens_in:
            self._last_tokens_in = tokens_in
        if tokens_out:
            self._last_tokens_out = tokens_out

        if hasattr(self, "_emit_bench"):
            try:
                self._emit_bench(self._collect_bench_metrics())
            except Exception:
                pass

    def inject_navbar_context(self) -> Dict[str, Any]:
        """Return template context variables for navbar_v2.html.

        Call inside a Flask ``render_template`` invocation to provide the
        universal navbar with scene identity information::

            return render_template(
                "my_scene.html",
                **self.inject_navbar_context(),
                ...scene-specific vars...
            )

        Returns:
            Dict with keys ``current_scene``, ``scene_name``, and
            ``scene_accent``.  All values have safe defaults so the method
            is safe to call even on a bare ``BaseScene`` instance.
        """
        metadata: Dict[str, Any] = getattr(self.__class__, "SCENE_METADATA", {})
        return {
            "current_scene": getattr(self, "scene_name", ""),
            "scene_name": metadata.get("display_name", "CosySim"),
            "scene_accent": metadata.get("accent_color", "#00e5ff"),
        }

    def mount_overlay(self, app, socketio=None) -> None:
        """Auto-mount the control overlay Blueprint on a Flask scene.

        Call in ``start()`` after creating the Flask app, or let
        ``register_health_route`` do it automatically.
        """
        try:
            from engine.overlay import mount_overlay
            mount_overlay(app, socketio)
        except Exception as _exc:
            _bslogger.debug("BaseScene.mount_overlay failed: %s", _exc)

    def mount_skills_server(self, app) -> None:
        """Mount the MCP skills server blueprint on a Flask app.

        Exposes ``/mcp/skills/*`` routes for tool discovery and execution.
        Also records the app port so ``get_skills_integration()`` works.
        """
        try:
            from engine.mcp.skills_server import skills_bp, set_skills_server_port
            app.register_blueprint(skills_bp)
            set_skills_server_port(self.port)
            _bslogger.debug("BaseScene: skills server mounted on port %d", self.port)
        except Exception as _exc:
            _bslogger.debug("BaseScene.mount_skills_server failed: %s", _exc)

    def register_tts_route(self, app) -> None:
        """Register TTS/speech endpoints on a Flask app.

        Routes added:

        - ``POST /api/tts/speak``   — synthesize text and return audio URL
        - ``GET  /api/tts/voices``  — list available voice/backend profiles
        - ``GET  /api/tts/audio/<file_id>`` — serve a cached WAV file

        Call in ``start()`` after creating the Flask app::

            self.register_tts_route(self.app)

        Request body for ``/api/tts/speak``::

            {
                "text":    "Hello!",
                "char_id": "luna",      # optional — used for voice lookup
                "backend": "piper",     # optional — piper|orpheus|qwen3|auto
                "speed":   1.0,         # optional — 0.5–2.0
                "pitch":   1.0,         # optional — reserved
            }

        Response::

            {
                "audio_url":   "/api/tts/audio/<uuid>",
                "duration_ms": 1200,
                "text":        "Hello!"
            }
        """
        import uuid as _uuid
        import json as _json
        from pathlib import Path as _Path
        from flask import request, Response, send_file

        _cache_dir = _Path(__file__).resolve().parents[2] / "data" / "tts_cache"
        _cache_dir.mkdir(parents=True, exist_ok=True)

        @app.route("/api/tts/speak", methods=["POST"])
        def _tts_speak():
            try:
                # Lazy import to avoid startup errors if TTS deps are missing
                from engine.tts.tts_manager import get_tts_manager

                data: Dict[str, Any] = request.get_json(silent=True) or {}
                text: str = str(data.get("text", "")).strip()
                if not text:
                    return Response(
                        _json.dumps({"error": "text is required"}),
                        status=400,
                        mimetype="application/json",
                    )

                char_id: Optional[str] = data.get("char_id")
                backend: str = str(data.get("backend", "auto"))
                speed: float = float(data.get("speed", 1.0))

                # Resolve character → voice via Nexus (best-effort)
                voice: str = "default"
                if char_id:
                    try:
                        from engine.nexus.client import get_nexus_client
                        nexus = get_nexus_client()
                        if nexus.is_available():
                            answer = nexus.ask(
                                f"What voice does {char_id} use?",
                                category="character",
                            )
                            resolved = (answer or {}).get("answer", "")
                            if resolved and resolved.lower() not in ("unknown", "none", ""):
                                voice = resolved
                    except Exception:
                        pass  # Nexus miss is non-fatal

                mgr = get_tts_manager()
                result = mgr.synthesize(text, backend=backend, voice=voice)

                # Persist WAV to cache
                file_id: str = str(_uuid.uuid4())
                wav_path: _Path = _cache_dir / f"{file_id}.wav"
                wav_path.write_bytes(result.audio_bytes)

                duration_ms: int = int(result.duration * 1000)

                return Response(
                    _json.dumps({
                        "audio_url":   f"/api/tts/audio/{file_id}",
                        "duration_ms": duration_ms,
                        "text":        text,
                    }),
                    mimetype="application/json",
                )
            except Exception as exc:
                _bslogger.warning("TTS speak endpoint failed: %s", exc)
                return Response(
                    _json.dumps({"error": "TTS unavailable"}),
                    status=503,
                    mimetype="application/json",
                )

        @app.route("/api/tts/voices", methods=["GET"])
        def _tts_voices():
            try:
                from engine.tts.tts_manager import get_tts_manager

                mgr = get_tts_manager()
                return Response(
                    _json.dumps({"voices": mgr.list_backends()}),
                    mimetype="application/json",
                )
            except Exception as exc:
                _bslogger.warning("TTS voices endpoint failed: %s", exc)
                return Response(
                    _json.dumps({"voices": [], "error": str(exc)}),
                    mimetype="application/json",
                )

        @app.route("/api/tts/audio/<file_id>", methods=["GET"])
        def _tts_audio(file_id: str):
            # Sanitise: only hex UUIDs (no path traversal)
            safe = "".join(c for c in file_id if c.isalnum() or c == "-")
            wav_path: _Path = _cache_dir / f"{safe}.wav"
            if not wav_path.exists():
                return Response(
                    _json.dumps({"error": "audio not found"}),
                    status=404,
                    mimetype="application/json",
                )
            return send_file(str(wav_path), mimetype="audio/wav")
    
    # ============= LIFECYCLE HOOKS =============
    # Override these in subclasses to react to scene events.
    
    def on_scene_loaded(self, scene_asset: SceneAsset) -> None:
        """Called after a saved scene is restored from an asset.
        Override to apply scene-specific configuration from the asset."""
        self._mcp_register_scene()

    # ── MCP helpers ──────────────────────────────────────────────────

    def _mcp_register_scene(self) -> None:
        """Register (or re-register) this scene with MCPFramework.  Best-effort."""
        try:
            from engine.mcp.framework import get_framework
            get_framework().get_scene(self.scene_name)   # auto-creates MCPSceneNode
            _bslogger.debug("BaseScene: MCPFramework registered scene '%s'", self.scene_name)
        except Exception as _exc:
            _bslogger.debug("BaseScene._mcp_register_scene failed: %s", _exc)
        self._wire_event_cascade()

    def _wire_event_cascade(self) -> None:
        """Subscribe this scene to EventCascade using its default event types.

        Reads DEFAULT_SCENE_SUBSCRIPTIONS for the scene's registered event
        interests and calls get_event_cascade().subscribe().  Best-effort —
        silently skips if EventCascade is not available or scene has no defaults.
        """
        try:
            from engine.world.event_cascade import (
                get_event_cascade,
                DEFAULT_SCENE_SUBSCRIPTIONS,
            )
            event_types = DEFAULT_SCENE_SUBSCRIPTIONS.get(self.scene_name)
            if event_types:
                get_event_cascade().subscribe(self.scene_name, event_types)
                _bslogger.debug(
                    "BaseScene: %s subscribed to EventCascade types: %s",
                    self.scene_name, event_types,
                )
        except Exception as _exc:
            _bslogger.debug("BaseScene._wire_event_cascade failed: %s", _exc)

    def _mcp_deregister_scene(self) -> None:
        """Broadcast scene stop to ActivityBus.  Call from subclass stop()."""
        # Remove from in-process lookup
        _ACTIVE_SCENES.pop(self.scene_name, None)
        try:
            from engine.services.activity_bus import get_activity_bus
            get_activity_bus().publish(
                activity_type="scene_stopped",
                description=f"Scene '{self.scene_name}' stopped",
                agent_id="system",
                scene=self.scene_name,
                data={"scene": self.scene_name, "port": self.port},
            )
        except Exception as _exc:
            _bslogger.debug("BaseScene._mcp_deregister_scene failed: %s", _exc)
    
    def on_character_added(self, character: CharacterAsset) -> None:
        """Called after a character is loaded into the scene.
        Override to initialise character-specific resources (e.g. 3D model, SocketIO room)."""
        # MCP: ensure character is tracked in CharacterRegistry + MCPFramework
        try:
            char_id = getattr(character, "id", None) or getattr(character, "asset_id", None)
            if char_id:
                from engine.mcp.character_registry import get_character_registry
                reg = get_character_registry()
                reg.ensure(char_id, display_name=getattr(character, "name", char_id))
                from engine.mcp.framework import get_framework
                fw_char = get_framework().get_character(char_id)
                fw_char.enter_scene(self.scene_name)
                _bslogger.debug("BaseScene: MCP registered character %s → %s", char_id, self.scene_name)
        except Exception as _exc:
            _bslogger.debug("BaseScene.on_character_added MCP sync failed: %s", _exc)

    def on_character_removed(self, character_id: str) -> None:
        """Called after a character is removed from the scene.
        Override to clean up character-specific resources."""
        # MCP: remove character from scene node
        try:
            from engine.mcp.framework import get_framework
            get_framework().get_character(character_id).leave_scene()
            _bslogger.debug("BaseScene: MCP character %s left %s", character_id, self.scene_name)
        except Exception as _exc:
            _bslogger.debug("BaseScene.on_character_removed MCP sync failed: %s", _exc)
        pass
