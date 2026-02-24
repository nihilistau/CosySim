"""engine.overlay — Control Overlay system for CosySim

The overlay is a Flask Blueprint that can be mounted on any scene's Flask app.
It provides a floating, draggable panel with real-time system monitoring,
agent inspection, config editing, and interactive controls.

Usage::

    from engine.overlay import mount_overlay

    # In any scene's Flask app setup:
    mount_overlay(app, socketio)  # registers /overlay/* routes
"""
from .overlay_bp import overlay_bp, mount_overlay, overlay_emit, get_overlay_socketio

__all__ = ["overlay_bp", "mount_overlay", "overlay_emit", "get_overlay_socketio"]
