"""CosySim shared assets — design tokens, JS utilities, Streamlit theme."""

from pathlib import Path as _Path

SHARED_STATIC_DIR = str(_Path(__file__).parent / "static")


def register_shared_assets(app):
    """Register the shared static Blueprint on a Flask app.

    After calling this, templates can reference shared assets via::

        <link href="/shared/css/design_tokens.css" rel="stylesheet">
        <script src="/shared/js/cosysim-core.js"></script>
        <script src="/shared/js/cosysim-stream.js"></script>

    Safe to call multiple times — silently skips if already registered.
    """
    if "shared" in app.blueprints:
        return
    from flask import Blueprint

    shared_bp = Blueprint(
        "shared",
        __name__,
        static_folder=SHARED_STATIC_DIR,
        static_url_path="/shared",
    )
    app.register_blueprint(shared_bp)
