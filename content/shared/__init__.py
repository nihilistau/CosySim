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
    from flask import Blueprint

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
    app.register_blueprint(shared_bp)

    # Auto-mount assistant API on this app
    try:
        from engine.assistant.assistant_bp import mount_assistant
        mount_assistant(app)
    except Exception:
        pass  # Assistant not available (e.g., during tests)

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
