"""CosySim shared assets — design tokens, JS utilities, Streamlit theme."""

import logging as _logging
from pathlib import Path as _Path

logger = _logging.getLogger(__name__)

SHARED_STATIC_DIR = str(_Path(__file__).parent / "static")
_PORTRAIT_TEMPLATE_PATH = _Path(__file__).parent / "templates" / "portrait_overlay.html"
_PORTRAITS_DIR = _Path(__file__).parent / "static" / "img" / "portraits"

# Script/CSS tags auto-injected into every HTML response
_INJECT_TAGS = (
    '\n<!-- CosySim Shared -->'
    '\n<link rel="stylesheet" href="/shared/css/cosysim-navbar.css">'
    '\n<script src="/shared/js/cosysim-navbar.js" defer></script>'
    '\n<script src="/shared/js/cosysim-assistant.js" defer></script>'
    '\n<link rel="stylesheet" href="/shared/css/cosysim-assistant.css">'
    '\n<link rel="stylesheet" href="/shared/css/cosysim-phone-panel.css">'
    '\n<script src="/shared/js/cosysim-phone-panel.js" defer></script>'
    '\n<link rel="stylesheet" href="/shared/css/portrait.css">'
    '\n<script src="/shared/js/portrait.js" defer></script>'
    '\n<link rel="stylesheet" href="/shared/css/cosysim-stt.css">'
    '\n<script src="/shared/js/cosysim-stt.js" defer></script>'
    '\n<link rel="stylesheet" href="/shared/css/cosysim-ambient.css">'
    '\n<script src="/shared/js/cosysim-ambient.js" defer></script>'
    '\n<link rel="stylesheet" href="/shared/css/reputation.css">'
    '\n<script src="/shared/js/reputation.js" defer></script>'
)


def register_shared_assets(app):
    """Register the shared static Blueprint on a Flask app.

    After calling this, templates can reference shared assets via::

        <link href="/shared/css/design_tokens.css" rel="stylesheet">
        <script src="/shared/js/cosysim-core.js"></script>
        <script src="/shared/js/cosysim-stream.js"></script>

    Also auto-injects the navigation bar and system assistant overlay
    into every HTML response via an ``after_request`` hook.

    Enables CORS for cross-scene health checks from the navbar.

    Safe to call multiple times — silently skips if already registered.
    """
    if "shared" in app.blueprints:
        return
    from flask import Blueprint, jsonify, request

    # Enable CORS so cross-port navbar health checks work
    try:
        from flask_cors import CORS
        CORS(app)
    except ImportError:
        pass

    shared_bp = Blueprint(
        "shared",
        __name__,
        static_folder=SHARED_STATIC_DIR,
        static_url_path="/shared",
    )

    # ── Nexus API routes (v0.71) ──────────────────────────────────

    @shared_bp.route("/api/nexus/status")
    def nexus_status_api() -> "Response":
        """Return live Nexus health and stats."""
        try:
            from engine.nexus.client import get_nexus_client
            client = get_nexus_client()
            result = client.stats()
            stats = result.get("data", {}) if result.get("ok") else {}
            return jsonify({
                "connected": True,
                "status": "online",
                "entries": stats.get("total_entries", stats.get("entries", "unknown")),
                "qa_pairs": stats.get("qa_pairs", stats.get("qa_count", "unknown")),
                "cache_hits": stats.get("cache_hits", "unknown"),
                "router_hits": stats.get("router_hits", "unknown"),
            })
        except Exception as exc:
            return jsonify({"connected": False, "status": str(exc)})

    @shared_bp.route("/api/nexus/search")
    def nexus_search_api() -> "Response":
        """Search Nexus knowledge base. Query param: q."""
        try:
            from engine.nexus.client import get_nexus_client
            q = request.args.get("q", "")
            if not q:
                return jsonify({"error": "Missing required query parameter: q"}), 400
            client = get_nexus_client()
            results = client.search(q, limit=10)
            return jsonify({"results": results})
        except Exception as exc:
            return jsonify({"results": [], "error": str(exc)})

    @shared_bp.route("/api/nexus/store", methods=["POST"])
    def nexus_store_api() -> "Response":
        """Store a knowledge entry. Body: {title, content, type}."""
        try:
            from engine.nexus.client import get_nexus_client
            data = request.get_json(force=True) or {}
            title = data.get("title", "Untitled")
            content = data.get("content", "")
            content_type = data.get("type", "note")
            client = get_nexus_client()
            entry_id = client.add_entry(title, content, content_type=content_type)
            if entry_id:
                return jsonify({"ok": True, "id": entry_id})
            return jsonify({"ok": False, "error": "Store failed"})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    # ── Metrics API routes (v0.72) ───────────────────────────────────

    @shared_bp.route("/api/metrics")
    def api_metrics() -> "Response":
        """Return in-process metrics summary. Query param: window (seconds)."""
        from engine.monitoring.metrics_collector import get_metrics_collector
        window = request.args.get("window", 3600, type=int)
        return jsonify(get_metrics_collector().get_summary(window_seconds=window))

    @shared_bp.route("/api/metrics/reset", methods=["POST"])
    def api_metrics_reset() -> "Response":
        """Clear all recorded metrics samples."""
        from engine.monitoring.metrics_collector import get_metrics_collector
        get_metrics_collector().reset()
        return jsonify({"reset": True})

    # ── Art / Portrait API routes (v0.72) ──────────────────────────

    @shared_bp.route("/api/art/portrait")
    def art_portrait_api() -> "Response":
        """Generate or retrieve a character portrait.

        Query params:
            char_id (str): Character identifier (required).
            mood    (str): Mood key (default: neutral).
            scene   (str): Scene slug for context (optional).
        """
        try:
            from engine.art.scene_art import get_scene_art_manager
            from engine.art.portrait_cache import get_portrait_cache
            char_id = request.args.get("char_id", "")
            if not char_id:
                return jsonify({"error": "char_id required"}), 400
            mood  = request.args.get("mood", "neutral")
            scene = request.args.get("scene", "")
            result = get_scene_art_manager().get_character_portrait(
                char_id, mood=mood, scene=scene
            )
            get_portrait_cache().set_url(char_id, mood, result.url)
            return jsonify({
                "ok": True,
                "char_id": char_id,
                "mood": mood,
                "url": result.url,
                "cached": result.cached,
                "generation_ms": result.generation_ms,
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    @shared_bp.route("/api/art/portraits")
    def art_portraits_api() -> "Response":
        """Return all cached portrait URLs as {char_id:mood → url}."""
        from engine.art.portrait_cache import get_portrait_cache
        return jsonify({"portraits": get_portrait_cache().get_all()})

    @shared_bp.route("/api/art/background")
    def art_background_api() -> "Response":
        """Generate or retrieve a scene background.

        Query params:
            scene       (str): Scene slug (required).
            time_of_day (str): dawn/morning/afternoon/dusk/night/midnight.
            mood        (str): Dramatic mood (default: neutral).
        """
        try:
            from engine.art.scene_art import get_scene_art_manager
            scene = request.args.get("scene", "")
            if not scene:
                return jsonify({"error": "scene required"}), 400
            time_of_day = request.args.get("time_of_day", "night")
            mood        = request.args.get("mood", "neutral")
            result = get_scene_art_manager().get_scene_bg(
                scene, time_of_day=time_of_day, mood=mood
            )
            return jsonify({
                "ok": True,
                "scene": scene,
                "time_of_day": time_of_day,
                "url": result.url,
                "cached": result.cached,
                "generation_ms": result.generation_ms,
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    # ── Admin Portrait API routes (v0.72) ──────────────────────────

    @shared_bp.route("/api/admin/portraits")
    def admin_portraits_api() -> "Response":
        """Return list of portrait image files from the portraits directory."""
        _PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            f.name for f in _PORTRAITS_DIR.iterdir()
            if f.is_file() and not f.name.startswith(".")
        )
        return jsonify({"portraits": files})

    @shared_bp.route("/api/admin/portrait/generate", methods=["POST"])
    def admin_portrait_generate_api() -> "Response":
        """Generate a portrait via the art_skills generate_portrait function.

        Body: {char_id: str, emotion: str}
        """
        try:
            from engine.skills.builtin.art_skills import generate_portrait
            data = request.get_json(force=True) or {}
            char_id = data.get("char_id", "")
            if not char_id:
                return jsonify({"ok": False, "error": "char_id required"}), 400
            emotion = data.get("emotion", data.get("mood", "neutral"))
            result = generate_portrait(char_id=char_id, emotion=emotion)
            return jsonify({"ok": True, "result": str(result)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    app.register_blueprint(shared_bp)

    # Auto-mount assistant API on this app
    try:
        from engine.assistant.assistant_bp import mount_assistant
        mount_assistant(app)
    except Exception:
        pass  # Assistant not available (e.g., during tests)

    # Backstory API — used by portrait hover panel
    try:
        from flask import jsonify

        @app.route("/api/character/backstory/<character_id>")
        def character_backstory(character_id: str):
            from engine.skills.builtin.npc_backstory_skills import get_npc_backstory
            return jsonify({"character_id": character_id, "backstory": get_npc_backstory(character_id)})
    except Exception:
        pass  # Flask not available (e.g., during tests)

    # Auto-inject navbar + assistant into HTML responses
    @app.after_request
    def _inject_shared_assets(response):
        if (
            response.content_type
            and "text/html" in response.content_type
            and response.status_code == 200
        ):
            try:
                data = response.get_data(as_text=True)
                # Read portrait overlay HTML (lazy, once per request — cheap file read)
                try:
                    _portrait_html = _PORTRAIT_TEMPLATE_PATH.read_text(encoding="utf-8")
                except OSError:
                    _portrait_html = ""
                # Inject before </body> if present, otherwise before </html>
                if "</body>" in data:
                    inject = _INJECT_TAGS
                    if _portrait_html:
                        inject = _portrait_html + inject
                    data = data.replace("</body>", inject + "\n</body>", 1)
                    response.set_data(data)
                elif "</html>" in data:
                    inject = _INJECT_TAGS
                    if _portrait_html:
                        inject = _portrait_html + inject
                    data = data.replace("</html>", inject + "\n</html>", 1)
                    response.set_data(data)
            except Exception:
                pass  # Don't break responses on injection failure
        return response
