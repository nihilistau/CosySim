"""
Assistant Platform — View Routes
==================================

Serves the single-page app.

Version: v1.0.0 [2026-03-23]
"""
from __future__ import annotations

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    return render_template("index.html")
