"""
Central Hub
============

Main Launcher & Navigation.

The central hub for the CosySim system.  Provides:
- Scene launcher with live status indicators
- Categorized scenes (Core · Showcase · Tools)
- Quick system health monitoring
- Asset browser, tutorials, and settings

Version: v1.52.0 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.52.0 [2026-03-25] — Added structured module header
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
import subprocess
import json
import requests

from engine.port_registry import (
    HUB_HEALTH_TARGETS,
    build_health_endpoints,
    get_port,
    get_service_url,
)
from engine.utils import port_is_open

def _service_up(url: str, timeout: float = 1.0) -> bool:
    """Check if an HTTP service responds."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


# Add project root to path
from engine.paths import ROOT as project_root
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

from engine.assets import AssetManager
from engine.config import ConfigManager


# Page config
st.set_page_config(
    page_title="CosySim Hub",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Dark theme + custom CSS
from content.shared.streamlit_theme import inject_dark_theme
inject_dark_theme()
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
        text-align: center;
        letter-spacing: -1px;
    }
    .subtitle {
        font-size: 1.1rem;
        color: #888;
        text-align: center;
        margin-bottom: 2rem;
    }
    .version-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-family: monospace;
        vertical-align: middle;
    }
    .category-header {
        font-size: 1.1rem;
        font-weight: 700;
        color: #ccc;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin: 1.5rem 0 0.8rem 0;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid #333;
    }
    .scene-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.4rem;
        border-radius: 14px;
        color: white;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        position: relative;
        overflow: hidden;
    }
    .scene-card::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 60%);
        pointer-events: none;
    }
    .scene-card:hover { transform: translateY(-3px); box-shadow: 0 8px 25px rgba(0,0,0,0.4); }
    .scene-icon { font-size: 2.8rem; margin-bottom: 0.5rem; }
    .scene-name { font-size: 1.2rem; font-weight: 700; margin-bottom: 0.3rem; }
    .scene-desc { font-size: 0.8rem; opacity: 0.85; line-height: 1.3; }
    .scene-status {
        margin-top: 0.5rem;
        font-size: 0.75rem;
        opacity: 0.9;
    }
    .quick-stat {
        background: #1a1a2e;
        padding: 0.8rem 1rem;
        border-radius: 10px;
        border-left: 3px solid #667eea;
        margin-bottom: 0.4rem;
        color: #e0e0e0;
        font-size: 0.9rem;
    }
    .health-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 1rem;
    }
    .health-chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 0.78rem;
        color: #ccc;
    }
    .tutorial-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #333;
        padding: 1.2rem;
        border-radius: 10px;
        color: #e0e0e0;
        margin-bottom: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Scene Definitions ────────────────────────────────────────────────


def _scene_entry(
    name: str,
    icon: str,
    target_id: str,
    mode: str,
    desc: str,
    color: str,
) -> Dict[str, Any]:
    """Build a scene card entry from canonical control-plane metadata."""
    return {
        "name": name,
        "icon": icon,
        "port": get_port(target_id),
        "mode": mode,
        "desc": desc,
        "color": color,
        "url": get_service_url(target_id),
    }


def _build_scene_categories() -> Dict[str, Dict[str, Any]]:
    """Return legacy hub scene groupings with canonical ports and URLs."""
    return {
        "core": {
            "label": "🎮 Core Scenes",
            "scenes": [
                _scene_entry(
                    "Phone",
                    "📱",
                    "phone",
                    "phone",
                    "Simulated Android — texting, photos, galleries, voice messages, apps",
                    "#667eea",
                ),
                _scene_entry(
                    "The Penthouse",
                    "🏙️",
                    "penthouse",
                    "penthouse",
                    "Multi-agent roleplay — characters, outfits, moods, director scenarios",
                    "#f093fb",
                ),
                _scene_entry(
                    "Velvet Lounge",
                    "🎷",
                    "lounge",
                    "lounge",
                    "1920s jazz speakeasy — Lola & Viktor, heat/trust, MCP dialog",
                    "#c9a84c",
                ),
                _scene_entry(
                    "Casino Royale",
                    "🎰",
                    "casino",
                    "casino",
                    "Texas Hold'em with AI bluffing, moods, bets, and card counting",
                    "#dc2626",
                ),
                _scene_entry(
                    "Art Gallery",
                    "🖼️",
                    "gallery",
                    "gallery",
                    "Streaming art critique, branching debate, image generation",
                    "#8b5cf6",
                ),
                _scene_entry(
                    "The Colosseum",
                    "⚔️",
                    "arena",
                    "arena",
                    "Tactical arena combat with betting and AI fighters",
                    "#059669",
                ),
            ],
        },
        "showcase": {
            "label": "⚡ v0.50a Showcase",
            "scenes": [
                _scene_entry(
                    "The Realm",
                    "⚔️",
                    "realm",
                    "realm",
                    "AI-directed LitRPG — dual-agent Director + Assistant, murder mystery, inventory, fourth-wall mechanics",
                    "#e94560",
                ),
                _scene_entry(
                    "NeonCity",
                    "🌃",
                    "neoncity",
                    "neoncity",
                    "Cyberpunk strategy board — procedural grid, Glitch Storm, loot nodes, AI opponents",
                    "#00d4ff",
                ),
                _scene_entry(
                    "Coders Room",
                    "💻",
                    "coders",
                    "coders",
                    "AI agent idle sim — agents write real Python, review, test in sandboxed pipelines",
                    "#10b981",
                ),
                _scene_entry(
                    "Dragon's Flagon",
                    "🍺",
                    "tavern",
                    "tavern",
                    "Fantasy tavern — 4 NPCs, quests, dice gambling, reputation, atmosphere, MCP showcase",
                    "#d4a344",
                ),
            ],
        },
        "tools": {
            "label": "🛠️ Tools & Services",
            "scenes": [
                _scene_entry(
                    "Dashboard",
                    "📊",
                    "dashboard",
                    "dashboard",
                    "Character stats, relationship levels, activity feed",
                    "#764ba2",
                ),
                _scene_entry(
                    "Admin Panel",
                    "🎛️",
                    "admin",
                    "admin",
                    "Character editor, asset manager, conversation explorer, model config",
                    "#f5576c",
                ),
                _scene_entry(
                    "Asset Studio",
                    "🎨",
                    "asset_studio",
                    "asset_studio",
                    "Generate images, videos, voices and stories via ComfyUI / TTS",
                    "#0ea5e9",
                ),
                _scene_entry(
                    "TTS Server",
                    "🎙️",
                    "tts",
                    "tts",
                    "Voice generation — voicemails, narration, character voices",
                    "#10b981",
                ),
                _scene_entry(
                    "MCP Bridge",
                    "🔌",
                    "bridge",
                    "bridge",
                    "LMStudio ↔ CosySim bridge — SSE streaming, MCP tools",
                    "#f59e0b",
                ),
            ],
        },
    }


def _build_quick_actions() -> List[Dict[str, str]]:
    """Return quick-action links backed by canonical control-plane URLs."""
    return [
        {
            "button": "🎛️ Admin Panel",
            "open_label": "Admin Panel",
            "url": get_service_url("admin"),
        },
        {
            "button": "📱 Phone Scene",
            "open_label": "Phone Scene",
            "url": get_service_url("phone"),
        },
        {
            "button": "🏙️ The Penthouse",
            "open_label": "The Penthouse",
            "url": get_service_url("penthouse"),
        },
    ]


SCENE_CATEGORIES = _build_scene_categories()
QUICK_ACTIONS = _build_quick_actions()

HEALTH_SERVICES = [
    (endpoint["name"], endpoint["url"])
    for endpoint in build_health_endpoints(HUB_HEALTH_TARGETS)
]


# ── Init ─────────────────────────────────────────────────────────────

def init_session_state():
    if 'asset_manager' not in st.session_state:
        st.session_state.asset_manager = AssetManager()
    if 'config' not in st.session_state:
        st.session_state.config = ConfigManager()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    init_session_state()

    # Header
    st.markdown('<h1 class="main-header">🏠 CosySim Hub</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="subtitle">Your gateway to the virtual companion system '
        '<span class="version-badge">v0.50a</span></p>',
        unsafe_allow_html=True,
    )

    # Sidebar
    with st.sidebar:
        st.markdown("### ⚡ Quick Actions")
        for action in QUICK_ACTIONS:
            if st.button(action["button"], use_container_width=True):
                st.markdown(f"[Open {action['open_label']}]({action['url']})")

        st.markdown("---")
        st.markdown("### 📊 System")
        stats = st.session_state.asset_manager.get_stats()
        st.markdown(f"""
        <div class="quick-stat">🗃️ <strong>{stats['total_assets']}</strong> assets</div>
        <div class="quick-stat">👤 <strong>{stats['by_type'].get('character', 0)}</strong> characters</div>
        <div class="quick-stat">🖼️ <strong>{stats['by_type'].get('image', 0)}</strong> images</div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        running_count = sum(1 for _, s in HEALTH_SERVICES if _service_up(s))
        st.markdown(f"**🟢 {running_count}/{len(HEALTH_SERVICES)}** services online")
        st.caption(datetime.now().strftime("%H:%M:%S"))
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    # Health strip
    chips_html = ""
    for name, url in HEALTH_SERVICES:
        up = _service_up(url)
        dot = "🟢" if up else "⚫"
        chips_html += f'<span class="health-chip">{dot} {name}</span>'
    st.markdown(f'<div class="health-row">{chips_html}</div>', unsafe_allow_html=True)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🎮 Scenes", "📖 Tutorials", "🗂️ Assets", "⚙️ Settings"])

    with tab1:
        _show_scenes()
    with tab2:
        _show_tutorials()
    with tab3:
        _show_assets()
    with tab4:
        _show_settings()


# ── Scene Launcher ───────────────────────────────────────────────────

def _show_scenes():
    project_root_path = project_root

    for cat_key, cat in SCENE_CATEGORIES.items():
        st.markdown(f'<div class="category-header">{cat["label"]}</div>', unsafe_allow_html=True)

        cols_per_row = 3
        scenes = cat["scenes"]
        for row_start in range(0, len(scenes), cols_per_row):
            row_scenes = scenes[row_start:row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, scene in zip(cols, row_scenes):
                with col:
                    running = port_is_open(scene["port"])
                    status = "🟢 Running" if running else "⚫ Stopped"
                    url = scene["url"]

                    st.markdown(
                        f"""<div class="scene-card" style="background:linear-gradient(135deg, {scene['color']} 0%, {scene['color']}99 100%);">
                            <div class="scene-icon">{scene['icon']}</div>
                            <div class="scene-name">{scene['name']}</div>
                            <div class="scene-desc">{scene['desc']}</div>
                            <div class="scene-status">{status} · :{scene['port']}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

                    c1, c2 = st.columns(2)
                    with c1:
                        if running:
                            if st.button("🔗 Open", key=f"o_{scene['mode']}", use_container_width=True):
                                st.markdown(f"**[→ {scene['name']}]({url})**")
                        else:
                            if st.button("🚀 Launch", key=f"l_{scene['mode']}", use_container_width=True):
                                try:
                                    subprocess.Popen(
                                        [sys.executable, str(project_root_path / "launcher.py"),
                                         "--mode", scene["mode"]],
                                        cwd=str(project_root_path),
                                        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
                                    )
                                    st.success(f"Launching {scene['name']}...")
                                except Exception as e:
                                    st.error(f"Launch failed: {e}")
                    with c2:
                        if running:
                            st.markdown(f"[🔗 {url}]({url})")


# ── Tutorials ────────────────────────────────────────────────────────

def _show_tutorials():
    st.header("📖 Tutorials")

    tutorials = [
        ("🚀 Getting Started",
         ["Launch any scene from the Scenes tab",
          "Create characters in Admin Panel (port 8502)",
          "Load them into Phone or Bedroom scenes",
          "Chat, generate images, make voice/video calls"]),
        ("⚔️ The Realm — LitRPG",
         ["Launch The Realm (port 5562)",
          "Pick a Director personality and start a new game",
          "Make choices — the Director narrates, the Assistant quips",
          "Try the Murder Mystery sub-module, Desperation Dice, Mutiny Mode"]),
        ("🌃 NeonCity — Strategy",
         ["Launch NeonCity (port 5563)",
          "Start a new game with 1-3 AI opponents",
          "Move, loot prefab nodes, attack/hack other runners",
          "Race to the center before the Glitch Storm closes in"]),
        ("💻 Coders Room — Idle Sim",
         ["Launch Coders Room (port 5564)",
          "Start the simulation — watch agents collaborate on features",
          "Add custom feature requests via the API",
          "Watch live code, reviews, and test results on the terminal"]),
        ("🔧 MCP Framework",
         ["Skills register via @skill decorator, callable by LLM agents",
          "State flows through MCPSceneNode → get_framework().get_scene()",
          "Cross-scene messaging via framework.cross_scene_send()",
          "Consequences queue deferred effects with schedule_consequence()"]),
    ]

    for title, steps in tutorials:
        with st.expander(title):
            for i, step in enumerate(steps, 1):
                st.markdown(f"**{i}.** {step}")

    st.markdown("---")
    st.subheader("⚡ Quick Start")
    st.code("""
# Launch everything
python launcher.py --mode all

# Or launch individual scenes
python launcher.py --mode phone
python launcher.py --mode penthouse
python launcher.py --mode realm

# Run tests (744 passing)
python launcher.py --mode test
    """, language="bash")


# ── Assets ───────────────────────────────────────────────────────────

def _show_assets():
    st.header("🗂️ Assets")
    stats = st.session_state.asset_manager.get_stats()

    if stats['by_type']:
        cols = st.columns(min(len(stats['by_type']), 5))
        for i, (atype, count) in enumerate(stats['by_type'].items()):
            with cols[i % len(cols)]:
                st.metric(atype.title(), count)
    else:
        st.info("No assets yet — create some in the Admin Panel.")

    st.markdown("---")
    st.subheader("🕒 Recent")
    recent = st.session_state.asset_manager.search(limit=5)
    if recent:
        for asset in recent:
            with st.expander(f"{asset.get('type', '?').title()}: {asset.get('id', '?')[:20]}"):
                st.json(asset)
    else:
        st.caption("No assets")


# ── Settings ─────────────────────────────────────────────────────────

def _show_settings():
    st.header("⚙️ Settings")
    config = st.session_state.config

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**System**")
        st.json({
            "version": "0.50b",
            "environment": config.get("system.environment", "default"),
            "name": config.get("system.name", "CosySim"),
        })
    with c2:
        st.markdown("**Paths**")
        st.json({
            "root": config.get("paths.project_root", "."),
            "data": config.get("paths.data_dir", "./data"),
            "models": config.get("paths.models_dir", "./pretrained_models"),
        })

    st.markdown("---")
    if st.checkbox("Show Full Configuration"):
        st.json(dict(config._config))


if __name__ == "__main__":
    main()
