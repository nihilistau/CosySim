"""
Assistant Platform — Flask Application Factory
================================================

Creates the Flask + SocketIO app with all blueprints registered.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial app factory
"""
from __future__ import annotations

import logging
from typing import Tuple

from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from apps.assistant.config import APP_DIR, APP_NAME, MAX_UPLOAD_MB, SECRET_KEY
from apps.assistant.models import init_db

logger = logging.getLogger(__name__)


def create_app() -> Tuple[Flask, SocketIO]:
    """Create and configure the Flask application.

    Returns:
        (app, socketio) tuple ready for socketio.run().
    """
    app = Flask(
        __name__,
        static_folder=str(APP_DIR / "static"),
        template_folder=str(APP_DIR / "templates"),
    )
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

    CORS(app)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # ── Mount CosySim shared assets at /shared/ ──────────────────
    try:
        from content.shared import register_shared_assets
        register_shared_assets(app)
    except ImportError:
        logger.debug("[Assistant] Shared assets not available — running standalone")

    # ── Init database ────────────────────────────────────────────
    init_db()

    # ── Register blueprints ──────────────────────────────────────
    from apps.assistant.routes.views import views_bp
    from apps.assistant.routes.api import api_bp, register_socketio_events
    from apps.assistant.routes.openai_compat import openai_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(openai_bp)

    register_socketio_events(socketio)

    # ── Health endpoint ──────────────────────────────────────────
    @app.route("/health")
    def health():
        from apps.assistant.services.router import get_model_count
        return jsonify({"status": "ok", "app": APP_NAME, "models": get_model_count()})

    logger.info("[Assistant] App created — blueprints: views, api, openai_compat")
    return app, socketio
