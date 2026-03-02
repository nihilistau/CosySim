"""CosySim shared assets — design tokens, JS utilities, Streamlit theme."""

from pathlib import Path as _Path

SHARED_STATIC_DIR = str(_Path(__file__).parent / "static")

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
                return jsonify({"results": []})
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
                # Inject before </body> if present, otherwise before </html>
                if "</body>" in data:
                    data = data.replace("</body>", _INJECT_TAGS + "\n</body>")
                    response.set_data(data)
                elif "</html>" in data:
                    data = data.replace("</html>", _INJECT_TAGS + "\n</html>")
                    response.set_data(data)
            except Exception:
                pass  # Don't break responses on injection failure
        return response
