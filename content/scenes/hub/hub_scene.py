"""
Central Hub - Main Launcher Scene

The central hub is the main entry point for the CosySim system.
Features:
- Scene launcher with previews
- Asset browser
- Tutorial system
- Quick access to admin panel
- System status monitoring
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import subprocess
import socket
import json
import requests


def _service_up(url: str, timeout: float = 1.0) -> bool:
    """Check if an HTTP service responds."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def _render_health_strip():
    """Render a horizontal service-health indicator bar for all three pillars."""
    services = [
        ("LMStudio", "http://localhost:1234/v1/models"),
        ("ComfyUI", "http://localhost:8188/system_stats"),
        ("TTS", "http://localhost:8600/status"),
        ("MCP Bridge", "http://localhost:8601/health"),
        ("Phone", "http://localhost:5555/api/health"),
        ("Bedroom", "http://localhost:5556/api/health"),
        ("Lounge", "http://localhost:5557/api/health"),
        ("Admin", "http://localhost:8502"),
    ]
    cols = st.columns(len(services))
    for col, (name, url) in zip(cols, services):
        up = _service_up(url)
        dot = "🟢" if up else "🔴"
        col.markdown(f"**{dot} {name}**")

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
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
    initial_sidebar_state="expanded"
)

# Dark theme + custom CSS
from content.shared.streamlit_theme import inject_dark_theme
inject_dark_theme()
st.markdown("""
<style>
    .main-header {
        font-size: 3.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
        text-align: center;
    }
    .subtitle {
        font-size: 1.3rem;
        color: #a0a0a0;
        text-align: center;
        margin-bottom: 3rem;
    }
    .scene-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        cursor: pointer;
        transition: transform 0.3s;
        height: 250px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .scene-card:hover {
        transform: translateY(-5px);
    }
    .scene-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
    }
    .scene-name {
        font-size: 1.5rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .scene-desc {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    .tutorial-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
    }
    .quick-stat {
        background: #1a1a1a;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin-bottom: 0.5rem;
        color: #f0f0f0;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state"""
    if 'asset_manager' not in st.session_state:
        st.session_state.asset_manager = AssetManager()
    if 'config' not in st.session_state:
        st.session_state.config = ConfigManager()
    if 'show_tutorial' not in st.session_state:
        st.session_state.show_tutorial = True
    if 'tutorial_step' not in st.session_state:
        st.session_state.tutorial_step = 0


def main():
    """Main hub interface"""
    init_session_state()
    
    # Header
    st.markdown('<h1 class="main-header">🏠 CosySim Hub</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Your gateway to the virtual companion system</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("## 🎯 Quick Access")
        
        if st.button("🎛️ Admin Panel", use_container_width=True):
            st.info("Run: `python launcher.py --mode admin`")
        
        if st.button("📚 Documentation", use_container_width=True):
            st.info("Check docs/ folder for guides")
        
        if st.button("🧪 Run Tests", use_container_width=True):
            st.info("Run: `python launcher.py --mode test`")
        
        st.markdown("---")
        st.markdown("## 📊 System Stats")
        
        stats = st.session_state.asset_manager.get_stats()
        st.markdown(f"""
        <div class="quick-stat">
            <strong>Total Assets:</strong> {stats['total_assets']}
        </div>
        <div class="quick-stat">
            <strong>Characters:</strong> {stats['by_type'].get('character', 0)}
        </div>
        <div class="quick-stat">
            <strong>Scenes:</strong> {stats['by_type'].get('scene', 0)}
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("**Status:** 🟢 Online")
        st.markdown(f"**Time:** {datetime.now().strftime('%H:%M:%S')}")
        
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    # Service health strip
    _render_health_strip()

    # Three Pillars quick status
    with st.expander("🏛️ Three Pillars Status", expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            lm_up = _service_up("http://localhost:1234/v1/models")
            st.markdown(f"### {'🟢' if lm_up else '🔴'} LMStudio")
            if lm_up:
                try:
                    r = requests.get("http://localhost:1234/v1/models", timeout=2)
                    models = r.json().get("data", [])
                    if models:
                        st.caption(f"Model: {models[0].get('id', 'unknown')}")
                    else:
                        st.caption("No model loaded")
                except Exception:
                    st.caption("Connected")
            else:
                st.caption("Not running — start LMStudio")
        with p2:
            comfy_up = _service_up("http://localhost:8188/system_stats")
            st.markdown(f"### {'🟢' if comfy_up else '🔴'} ComfyUI")
            if comfy_up:
                st.caption("Image/video generation ready")
            else:
                st.caption("Not running — start ComfyUI")
        with p3:
            tts_up = _service_up("http://localhost:8600/status")
            st.markdown(f"### {'🟢' if tts_up else '🔴'} TTS Server")
            if tts_up:
                try:
                    r = requests.get("http://localhost:8600/status", timeout=2)
                    mode = r.json().get("mode", "unknown")
                    st.caption(f"Mode: {mode}")
                except Exception:
                    st.caption("Connected")
            else:
                st.caption("Run: python launcher.py --mode tts")

    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["🎮 Launch Scenes", "📖 Tutorials", "🗂️ Assets", "⚙️ Settings"])
    
    with tab1:
        show_scene_launcher()
    
    with tab2:
        show_tutorials()
    
    with tab3:
        show_asset_quick_view()
    
    with tab4:
        show_settings()


def _port_open(port: int) -> bool:
    """Check if a TCP port is listening on localhost."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def show_scene_launcher():
    """Scene launcher with live status cards"""
    st.header("🎮 Available Scenes")

    scenes = [
        {
            "name": "Phone Scene",
            "icon": "📱",
            "description": "Simulated Android phone — texting, photos, autonomous messages",
            "port": 5555,
            "launch_args": ["--mode", "phone"],
            "color": "#667eea",
        },
        {
            "name": "Bedroom Scene",
            "icon": "🛏️",
            "description": "Private penthouse environment with character interactions",
            "port": 5556,
            "launch_args": ["--mode", "bedroom"],
            "color": "#f093fb",
        },
        {
            "name": "The Velvet Lounge",
            "icon": "🎷",
            "description": "1920s underground jazz speakeasy — Lola Voss, Viktor Marlowe, MCP heat/trust system",
            "port": 5557,
            "launch_args": ["--mode", "lounge"],
            "color": "#c9a84c",
        },
        {
            "name": "Dashboard",
            "icon": "📊",
            "description": "Character stats, relationship levels, activity feed",
            "port": 8501,
            "launch_args": ["--mode", "dashboard"],
            "color": "#764ba2",
        },
        {
            "name": "Admin Panel",
            "icon": "🎛️",
            "description": "Character editor, asset manager, running log",
            "port": 8502,
            "launch_args": ["--mode", "admin"],
            "color": "#f5576c",
        },
        {
            "name": "Asset Generator",
            "icon": "🎨",
            "description": "Generate images, videos, voices and stories via ComfyUI / TTS",
            "port": 8503,
            "launch_args": ["--mode", "assets"],
            "color": "#0ea5e9",
        },
        {
            "name": "TTS Server",
            "icon": "🎙️",
            "description": "Qwen3-TTS voice generation — voicemails, stories, character voices",
            "port": 8600,
            "launch_args": ["--mode", "tts"],
            "color": "#10b981",
        },
        {
            "name": "MCP Bridge",
            "icon": "🔌",
            "description": "LMStudio ↔ CosySim bridge — SSE streaming, MCP tools, file upload",
            "port": 8601,
            "launch_args": ["--mode", "bridge"],
            "color": "#f59e0b",
        },
    ]

    cols = st.columns(2)
    project_root_path = Path(__file__).parent.parent.parent

    for i, scene in enumerate(scenes):
        with cols[i % 2]:
            running = _port_open(scene["port"])
            status_badge = "🟢 Running" if running else "⚫ Stopped"
            url = f"http://localhost:{scene['port']}"

            st.markdown(
                f"""
                <div class="scene-card" style="background: linear-gradient(135deg, {scene['color']} 0%, {scene['color']}cc 100%);">
                    <div class="scene-icon">{scene['icon']}</div>
                    <div class="scene-name">{scene['name']}</div>
                    <div class="scene-desc">{scene['description']}</div>
                    <div style="margin-top:0.6rem;font-size:0.85rem;">{status_badge} &bull; Port {scene['port']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c1, c2 = st.columns(2)
            with c1:
                if running:
                    if st.button(f"🔗 Open", key=f"open_{i}", use_container_width=True):
                        st.markdown(f"**[Open {scene['name']}]({url})**")
                else:
                    if st.button(f"🚀 Launch", key=f"launch_{i}", use_container_width=True):
                        try:
                            subprocess.Popen(
                                [sys.executable, str(project_root_path / "launcher.py")] + scene["launch_args"],
                                cwd=str(project_root_path),
                                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
                            )
                            st.success(f"Launching {scene['name']}...")
                        except Exception as e:
                            st.error(f"Launch failed: {e}")
            with c2:
                if running:
                    st.markdown(f"[🔗 {url}]({url})")

            st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("➕ Create New Scene")
    st.markdown("Use the **Scene Creator** wizard for guided scene scaffolding.")
    if st.button("🎨 Open Scene Creator", use_container_width=True):
        st.info("Run: `python launcher.py --mode creator`  (port 8504)")


def show_tutorials():
    """Interactive tutorials"""
    st.header("📖 Interactive Tutorials")
    
    tutorials = [
        {
            "title": "🚀 Getting Started",
            "description": "Learn the basics of CosySim",
            "steps": [
                "Launch a scene from the Scene Launcher",
                "Create your first character in Admin Panel",
                "Test text messaging in Phone Scene",
                "Try voice/video calls"
            ]
        },
        {
            "title": "👥 Character Creation",
            "description": "Create and customize characters",
            "steps": [
                "Open Admin Panel (port 8502)",
                "Navigate to Character Manager",
                "Fill in character details (name, age, appearance)",
                "Set behavior settings (autonomy, messaging frequency)",
                "Save character to asset system"
            ]
        },
        {
            "title": "🗂️ Asset Management",
            "description": "Manage your assets",
            "steps": [
                "Open Admin Panel → Asset Browser",
                "Filter assets by type or tag",
                "View asset details and dependencies",
                "Export/import assets as JSON",
                "Clean up orphaned assets"
            ]
        },
        {
            "title": "🎨 Scene Customization",
            "description": "Create custom scenes",
            "steps": [
                "Use Scene Launcher → Create New Scene",
                "Configure scene type and port",
                "Assign characters to scene",
                "Set scene-specific configuration",
                "Launch your custom scene"
            ]
        },
        {
            "title": "🔧 Advanced Configuration",
            "description": "Configure the system",
            "steps": [
                "Edit config/default.yaml for base settings",
                "Use config/development.yaml for dev overrides",
                "Set environment variables for runtime config",
                "View configuration in Admin Panel",
                "Test changes with launcher dev mode"
            ]
        }
    ]
    
    for tutorial in tutorials:
        with st.expander(f"{tutorial['title']} - {tutorial['description']}"):
            st.markdown(f"**{tutorial['title']}**")
            st.markdown(tutorial['description'])
            st.markdown("")
            st.markdown("**Steps:**")
            for i, step in enumerate(tutorial['steps'], 1):
                st.markdown(f"{i}. {step}")
    
    # Quick start guide
    st.markdown("---")
    st.subheader("⚡ Quick Start")
    
    st.code("""
# 1. Launch admin panel to create a character
python launcher.py --mode admin

# 2. Launch phone scene to interact
python launcher.py --mode play
# Then select option 1 (Phone Scene)

# 3. Run tests to verify everything works
python launcher.py --mode test
    """, language="bash")


def show_asset_quick_view():
    """Quick asset overview"""
    st.header("🗂️ Asset Overview")
    
    stats = st.session_state.asset_manager.get_stats()
    
    # Asset type breakdown
    st.subheader("📦 Asset Breakdown")
    
    if stats['by_type']:
        cols = st.columns(4)
        asset_types = list(stats['by_type'].items())
        
        for i, (asset_type, count) in enumerate(asset_types):
            with cols[i % 4]:
                st.metric(asset_type.title(), count)
    else:
        st.info("No assets yet. Create some in the Admin Panel!")
    
    # Recent assets
    st.markdown("---")
    st.subheader("🕒 Recent Assets")
    
    recent = st.session_state.asset_manager.search(limit=5)
    
    if recent:
        for asset in recent:
            with st.expander(f"{asset['type'].title()}: {asset['id'][:16]}..."):
                st.json(asset)
    else:
        st.info("No recent assets")
    
    # Quick actions
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🎛️ Open Admin Panel", use_container_width=True):
            st.info("Run: `python launcher.py --mode admin`")
    
    with col2:
        if st.button("📊 Export Stats", use_container_width=True):
            st.download_button(
                "Download JSON",
                data=json.dumps(stats, indent=2),
                file_name=f"stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
    
    with col3:
        if st.button("🧹 Clean Orphans", use_container_width=True):
            orphans = st.session_state.asset_manager.find_orphans()
            if orphans:
                st.warning(f"Found {len(orphans)} orphaned assets")
            else:
                st.success("No orphans found!")


def show_settings():
    """System settings"""
    st.header("⚙️ Settings")
    
    config = st.session_state.config
    
    # Display configuration
    st.subheader("Current Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**System Info**")
        st.json({
            "version": "1.0.0",
            "environment": config.get("system.environment", "development"),
            "name": config.get("system.name", "CosySim")
        })
    
    with col2:
        st.markdown("**Paths**")
        st.json({
            "root": config.get("paths.root", "."),
            "data": config.get("paths.data", "./data"),
            "models": config.get("paths.models", "./pretrained_models")
        })
    
    # Database info
    st.markdown("---")
    st.subheader("💾 Database")
    
    st.json({
        "type": config.get("database.type", "sqlite"),
        "path": config.get("database.path", "./data/simulation.db"),
        "chroma_path": config.get("database.chroma_path", "./data/chroma")
    })
    
    # Full config
    st.markdown("---")
    if st.checkbox("Show Full Configuration"):
        st.json(dict(config._config))


if __name__ == "__main__":
    main()
