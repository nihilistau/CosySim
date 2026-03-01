"""Flask Hub — main landing page and scene navigator for CosySim.

Replaces the Streamlit hub with a proper Flask app that integrates with
the shared navbar, system assistant, and design token system.

Usage:
    python launcher.py --mode hub
"""
from __future__ import annotations

import logging
import os
import socket
import time
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template_string

from engine.scenes.base_scene import BaseScene
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

SCENE_ID = "hub"
DEFAULT_PORT = 8500

# ── Scene catalogue ──────────────────────────────────────────────────
SCENE_CATALOGUE: List[Dict[str, Any]] = [
    {"id": "phone",     "port": 5555, "label": "CosyPhone",        "icon": "📱", "group": "core",  "desc": "Multi-contact messaging, calls, photo/video sharing"},
    {"id": "bedroom",   "port": 5556, "label": "The Bedroom",      "icon": "🛏️", "group": "core",  "desc": "Intimate roleplay with emotional AI companions"},
    {"id": "lounge",    "port": 5557, "label": "Velvet Lounge",    "icon": "🎵", "group": "core",  "desc": "Jazz bar with NPCs, drinks, and mood contagion"},
    {"id": "tavern",    "port": 5558, "label": "Dragon's Flagon",  "icon": "🍺", "group": "core",  "desc": "Fantasy tavern with quests and barkeep wisdom"},
    {"id": "casino",    "port": 5559, "label": "Midnight Casino",  "icon": "🎰", "group": "core",  "desc": "Blackjack, roulette, and a charismatic dealer"},
    {"id": "gallery",   "port": 5560, "label": "The Gallery",      "icon": "🎨", "group": "core",  "desc": "AI-generated art exhibition and curation"},
    {"id": "warzone",   "port": 5561, "label": "Global Strike",    "icon": "⚔️", "group": "core",  "desc": "Tactical combat simulation with RPG elements"},
    {"id": "realm",     "port": 5562, "label": "The Realm",        "icon": "🏰", "group": "core",  "desc": "Open-world RPG with quest chains and exploration"},
    {"id": "neoncity",  "port": 5563, "label": "NeonCity",         "icon": "🌃", "group": "core",  "desc": "Cyberpunk city exploration and noir stories"},
    {"id": "coders",    "port": 5564, "label": "Coders Room",      "icon": "💻", "group": "core",  "desc": "Multi-agent programming collaboration"},
    {"id": "heist",     "port": 5565, "label": "The Heist",        "icon": "🔓", "group": "core",  "desc": "Plan and execute elaborate heists with AI crew"},
    {"id": "games",     "port": 5567, "label": "Games Arcade",     "icon": "🎮", "group": "core",  "desc": "Mystery investigation and truth-or-dare with AI GameMaster"},
    {"id": "command_center", "port": 5566, "label": "Command Center", "icon": "📡", "group": "tools", "desc": "Real-time system monitoring and control"},
    {"id": "nexus_panel",    "port": 5570, "label": "Nexus Control",   "icon": "🧠", "group": "tools", "desc": "Knowledge management, Librarian AI, workflows"},
    {"id": "intel_hub",      "port": 5580, "label": "Intelligence Hub", "icon": "◆",  "group": "tools", "desc": "Unified control: Nexus, Copilot, NLM, fine-tuning, scheduler"},
    {"id": "dashboard", "port": 8501, "label": "Dashboard",        "icon": "📊", "group": "tools", "desc": "Admin dashboard and analytics"},
]


def _port_open(port: int) -> bool:
    """Check if a TCP port is listening on localhost."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class HubScene(BaseScene):
    """Flask-based CosySim hub — landing page and scene navigator."""

    SCENE_METADATA = {
        "name": SCENE_ID,
        "title": "CosySim Hub",
        "description": "Central hub for scene navigation and system monitoring",
        "genre": "utility",
        "type": "hub",
        "max_characters": 0,
        "features": ["scene_navigation", "health_monitoring", "system_status"],
        "port": DEFAULT_PORT,
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self.app = Flask(__name__)
        register_shared_assets(self.app)
        self.register_health_route(self.app)

        # Register news feed API blueprint
        try:
            from engine.nexus.news_feed_api import create_news_blueprint
            self.app.register_blueprint(create_news_blueprint(), url_prefix="/api/news")
        except Exception as exc:
            logger.debug("News feed API not available: %s", exc)

        self._setup_routes()
        logger.info("HubScene created on port %d", port)

    def _setup_routes(self) -> None:
        """Register all Flask routes."""
        app = self.app

        @app.route("/")
        def index() -> str:
            return render_template_string(_HUB_HTML)

        @app.route("/api/scenes")
        def api_scenes() -> Any:
            """Return scene list with live health status."""
            scenes = []
            for s in SCENE_CATALOGUE:
                online = _port_open(s["port"])
                scenes.append({**s, "status": "online" if online else "offline"})
            return jsonify(scenes)

        @app.route("/api/system")
        def api_system() -> Any:
            """Return system summary."""
            try:
                from engine.assistant.system_assistant import get_assistant
                return jsonify(get_assistant().get_system_summary())
            except Exception:
                return jsonify({"active_scenes": [], "vram_used_mb": 0})

    def start(self) -> None:
        """Start the hub Flask server."""
        logger.info("Starting HubScene on %s:%d", self.host, self.port)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self) -> None:
        """Stop the hub."""
        logger.info("HubScene stopping")

    def get_plugin_info(self) -> Dict[str, Any]:
        """Return plugin metadata for the hub."""
        return {
            "name": SCENE_ID,
            "version": "0.57b",
            "description": self.SCENE_METADATA["description"],
            "author": "CosySim",
            "port": self.port,
            "tags": ["hub", "navigation", "system"],
            "skill_packs": [],
            "routes": ["/", "/api/scenes", "/api/system", "/api/health"],
        }


def create_app(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> HubScene:
    """Factory function for the launcher.

    Args:
        host: Bind address.
        port: Port number.

    Returns:
        Configured HubScene instance.
    """
    return HubScene(host=host, port=port)


# ── HTML Template ────────────────────────────────────────────────────

_HUB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CosySim Hub</title>
  <link rel="stylesheet" href="/shared/css/design_tokens.css">
  <script src="/shared/js/cosysim-core.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: var(--cs-bg-deepest);
      color: var(--cs-text-primary);
      font-family: -apple-system, system-ui, 'Segoe UI', sans-serif;
      min-height: 100vh;
    }

    /* ── Hero ─────────────────────────────────── */
    .hub-hero {
      text-align: center;
      padding: 48px 24px 32px;
      background: linear-gradient(180deg, rgba(102,126,234,0.08) 0%, transparent 100%);
    }
    .hub-hero h1 {
      font-size: 32px;
      font-weight: 700;
      background: linear-gradient(135deg, #667eea, #764ba2, #f093fb);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 8px;
    }
    .hub-hero p {
      color: var(--cs-text-secondary);
      font-size: 14px;
    }
    .hub-version {
      display: inline-block;
      background: rgba(102,126,234,0.15);
      color: var(--cs-accent);
      padding: 2px 10px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 600;
      margin-left: 8px;
    }

    /* ── System Bar ──────────────────────────── */
    .system-bar {
      display: flex;
      justify-content: center;
      gap: 24px;
      padding: 12px 24px;
      border-bottom: 1px solid rgba(102,126,234,0.08);
      font-size: 12px;
      color: var(--cs-text-muted);
    }
    .system-bar .stat { display: flex; align-items: center; gap: 6px; }
    .system-bar .stat-value { color: var(--cs-text-primary); font-weight: 600; }

    /* ── Scene Grid ──────────────────────────── */
    .hub-content {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }
    .section-title {
      font-size: 13px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--cs-text-muted);
      margin: 24px 0 12px;
      padding-bottom: 6px;
      border-bottom: 1px solid rgba(102,126,234,0.08);
    }
    .scene-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 14px;
    }
    .scene-card {
      background: var(--cs-bg-card);
      border: 1px solid rgba(102,126,234,0.08);
      border-radius: 10px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: flex-start;
      gap: 14px;
      text-decoration: none;
      color: inherit;
    }
    .scene-card:hover {
      border-color: rgba(102,126,234,0.25);
      background: var(--cs-bg-elevated);
      transform: translateY(-1px);
      box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    }
    .scene-card .icon {
      font-size: 28px;
      width: 42px;
      height: 42px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(102,126,234,0.06);
      border-radius: 10px;
      flex-shrink: 0;
    }
    .scene-card .info { flex: 1; min-width: 0; }
    .scene-card .name {
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 4px;
    }
    .scene-card .desc {
      font-size: 12px;
      color: var(--cs-text-secondary);
      line-height: 1.4;
      margin-bottom: 6px;
    }
    .scene-card .meta {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      color: var(--cs-text-dim);
    }
    .scene-card .dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .scene-card .dot.online { background: var(--cs-green); box-shadow: 0 0 4px rgba(34,197,94,0.4); }
    .scene-card .dot.offline { background: var(--cs-text-dim); }

    /* ── Loading Skeleton ────────────────────── */
    .loading-text {
      color: var(--cs-text-dim);
      font-size: 13px;
      text-align: center;
      padding: 40px;
    }

    /* ── Footer ──────────────────────────────── */
    .hub-footer {
      text-align: center;
      padding: 24px;
      font-size: 11px;
      color: var(--cs-text-dim);
      border-top: 1px solid rgba(102,126,234,0.05);
      margin-top: 40px;
    }
  </style>
</head>
<body>
  <div class="hub-hero">
    <h1>🏠 CosySim Hub</h1>
    <p>Your gateway to the virtual companion system <span class="hub-version">v0.57b</span></p>
  </div>

  <div class="system-bar" id="system-bar">
    <div class="stat">🖥️ Scenes: <span class="stat-value" id="stat-scenes">...</span></div>
    <div class="stat">🧠 Agents: <span class="stat-value" id="stat-agents">...</span></div>
    <div class="stat">💾 VRAM: <span class="stat-value" id="stat-vram">...</span></div>
  </div>

  <div class="hub-content">
    <div class="section-title">🎮 Scenes</div>
    <div class="scene-grid" id="scene-grid-core">
      <div class="loading-text">Loading scenes...</div>
    </div>

    <div class="section-title">🛠️ Tools & Admin</div>
    <div class="scene-grid" id="scene-grid-tools">
      <div class="loading-text">Loading tools...</div>
    </div>
  </div>

  <div class="hub-footer">
    CosySim v0.57b · Multi-Scene AI Simulation Framework
  </div>

  <script>
    (function() {
      'use strict';

      async function loadScenes() {
        try {
          const resp = await fetch('/api/scenes');
          const scenes = await resp.json();

          const core = scenes.filter(s => s.group === 'core');
          const tools = scenes.filter(s => s.group === 'tools');

          renderGrid('scene-grid-core', core);
          renderGrid('scene-grid-tools', tools);

          // Update stats
          const online = scenes.filter(s => s.status === 'online').length;
          document.getElementById('stat-scenes').textContent = `${online}/${scenes.length} online`;
        } catch (err) {
          document.getElementById('scene-grid-core').innerHTML =
            '<div class="loading-text">Failed to load scenes. Refresh to retry.</div>';
        }
      }

      async function loadSystem() {
        try {
          const resp = await fetch('/api/system');
          const data = await resp.json();
          document.getElementById('stat-agents').textContent = data.agent_count || '0';
          if (data.vram_total_mb) {
            const pct = ((data.vram_used_mb / data.vram_total_mb) * 100).toFixed(0);
            document.getElementById('stat-vram').textContent =
              `${Math.round(data.vram_used_mb)}/${Math.round(data.vram_total_mb)} MB (${pct}%)`;
          } else {
            document.getElementById('stat-vram').textContent = 'N/A';
          }
        } catch {
          document.getElementById('stat-agents').textContent = '?';
          document.getElementById('stat-vram').textContent = '?';
        }
      }

      function renderGrid(containerId, scenes) {
        const container = document.getElementById(containerId);
        if (!container) return;
        if (!scenes.length) {
          container.innerHTML = '<div class="loading-text">No scenes found</div>';
          return;
        }
        container.innerHTML = scenes.map(s => `
          <a class="scene-card" href="http://localhost:${s.port}/"
             onclick="event.preventDefault(); window.location.href='http://localhost:${s.port}/'">
            <div class="icon">${s.icon}</div>
            <div class="info">
              <div class="name">${s.label}</div>
              <div class="desc">${s.desc || ''}</div>
              <div class="meta">
                <span class="dot ${s.status}"></span>
                <span>${s.status === 'online' ? 'Online' : 'Offline'}</span>
                <span>· :${s.port}</span>
              </div>
            </div>
          </a>
        `).join('');
      }

      // Init
      loadScenes();
      loadSystem();
      // Refresh every 15s
      setInterval(loadScenes, 15000);
      setInterval(loadSystem, 30000);
    })();
  </script>
</body>
</html>"""
