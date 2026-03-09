"""CosySim shared assets — design tokens, JS utilities, Streamlit theme."""

import logging as _logging
from pathlib import Path as _Path

logger = _logging.getLogger(__name__)

SHARED_STATIC_DIR = str(_Path(__file__).parent / "static")
_PORTRAIT_TEMPLATE_PATH = _Path(__file__).parent / "templates" / "portrait_overlay.html"
_PORTRAITS_DIR = _Path(__file__).parent / "static" / "img" / "portraits"

# Script/CSS tags auto-injected into every HTML response.
# NOTE: Legacy cosysim-navbar.js/css REMOVED in v0.93b — navbar_v2.html
# is the standard nav include.  cosysim-assistant.js kept until Aria v3.
_INJECT_TAGS = (
    '\n<!-- CosySim Shared -->'
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

    @shared_bp.route("/api/perf/metrics")
    def api_metrics() -> "Response":
        """Return in-process metrics summary. Query param: window (seconds)."""
        from engine.monitoring.metrics_collector import get_metrics_collector
        window = request.args.get("window", 3600, type=int)
        return jsonify(get_metrics_collector().get_summary(window_seconds=window))

    @shared_bp.route("/api/perf/metrics/reset", methods=["POST"])
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

    # ── Admin Profile API route (v0.72) ───────────────────────────

    @shared_bp.route("/api/admin/profile")
    def admin_profile_api() -> "Response":
        """Return player profile data as JSON."""
        try:
            from engine.characters.player_profile import get_player_profile
            profile = get_player_profile()
            return jsonify(profile.to_dict())
        except Exception as exc:
            return jsonify({"error": str(exc)})

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

    @shared_bp.route("/api/admin/npcs")
    def admin_npcs() -> "Response":
        """Return all active NPC states as a JSON list."""
        try:
            from engine.world.npc_state import get_npc_state
            state = get_npc_state()
            return jsonify({"npcs": [n.to_dict() for n in state.list_all()]})
        except Exception as exc:
            logger.error("admin_npcs error: %s", exc)
            return jsonify({"npcs": [], "error": str(exc)})

    # ── Admin Training API routes (v0.78) ──────────────────────────

    @shared_bp.route("/api/admin/training/stats")
    def admin_training_stats() -> "Response":
        """Return training dataset stats for all ModelZoo types."""
        try:
            from training.data_collector import get_data_collector
            collector = get_data_collector()
            stats = collector.get_stats()
            return jsonify(stats)
        except Exception as exc:
            logger.error("admin_training_stats error: %s", exc)
            return jsonify({"error": str(exc)})

    @shared_bp.route("/api/admin/training/seed", methods=["POST"])
    def admin_training_seed() -> "Response":
        """Trigger Nexus content seeding for knowledge base."""
        try:
            from engine.nexus.bridge import run_seed
            result = run_seed("all")
            return jsonify({"ok": True, "result": str(result)[:200]})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    @shared_bp.route("/api/admin/training/prune", methods=["POST"])
    def admin_training_prune() -> "Response":
        """Prune low-quality training examples from collected datasets."""
        try:
            from training.data_collector import get_data_collector
            collector = get_data_collector()
            pruned = collector.prune_low_quality(min_quality=0.3)
            return jsonify({"ok": True, "pruned": pruned})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    @shared_bp.route("/api/admin/training/trigger/<model_type>", methods=["POST"])
    def admin_training_trigger(model_type: str) -> "Response":
        """Trigger a training job for the given model type."""
        try:
            import threading
            from training.auto_train import check_and_train_all_zoo
            from training.data_collector import get_data_collector

            def _run_single(mt: str) -> None:
                """Force-train a single model type by temporarily faking threshold met."""
                try:
                    check_and_train_all_zoo()
                except Exception as exc:
                    logger.warning("Training trigger failed for %s: %s", mt, exc)

            threading.Thread(
                target=_run_single,
                args=(model_type,),
                daemon=True,
                name=f"train-{model_type}",
            ).start()
            return jsonify({"ok": True, "queued": True, "model_type": model_type})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    # ── Compute / Tunnel API routes ───────────────────────────────────

    @shared_bp.route("/api/compute/status")
    def compute_status() -> "Response":
        """Return status of all compute backends and usage."""
        from engine.integrations.compute_router import get_compute_router
        return jsonify(get_compute_router().get_status())

    @shared_bp.route("/api/compute/tunnel/deploy", methods=["POST"])
    def deploy_tunnel() -> "Response":
        """Deploy a Colab tunnel server. Body: {account_name, tunnel_type}."""
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        data = request.get_json() or {}
        account_name = data.get("account_name", "")
        tunnel_type = data.get("tunnel_type", "cloudflare")
        try:
            server = get_tunnel_server()
            server._tunnel_type = tunnel_type
            session = server.deploy(account_name=account_name or None)
            return jsonify({
                "tunnel_url": session.tunnel_url,
                "hardware": session.hardware,
                "kernel_id": session.kernel_id,
                "status": "ok",
            })
        except Exception as exc:
            return jsonify({"error": str(exc), "status": "error"}), 500

    @shared_bp.route("/api/compute/tunnel/list")
    def list_tunnels() -> "Response":
        """List all active tunnel sessions."""
        from engine.integrations.colab_tunnel_server import get_tunnel_server
        sessions = get_tunnel_server().get_active_sessions()
        return jsonify([{
            "account_name": s.account_name,
            "tunnel_url": s.tunnel_url,
            "hardware": s.hardware,
            "healthy": s.healthy,
            "started_at": s.started_at,
            "tunnel_type": s.tunnel_type,
        } for s in sessions])

    @shared_bp.route("/api/compute/accounts/configure", methods=["POST"])
    def configure_compute_account() -> "Response":
        """Configure features or limits for a Google account.

        Body: {account_name, feature?, enabled?, service?, limit?}
        """
        from engine.integrations.compute_router import get_compute_router
        data = request.get_json() or {}
        router = get_compute_router()
        account_name = data.get("account_name", "")
        if not account_name:
            return jsonify({"error": "account_name required"}), 400
        if "feature" in data:
            feature = data["feature"]
            enabled = data.get("enabled", True)
            existing = router._feature_config.get(account_name, {}).get(
                "unlocked_features", []
            )
            if enabled and feature not in existing:
                existing.append(feature)
            elif not enabled and feature in existing:
                existing.remove(feature)
            router.set_feature_config(account_name, existing)
        if "service" in data and "limit" in data:
            limit = (
                float("inf") if data["limit"] == "unlimited" else float(data["limit"])
            )
            router.configure_limits(account_name, data["service"], limit)
        return jsonify({"status": "ok"})

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
