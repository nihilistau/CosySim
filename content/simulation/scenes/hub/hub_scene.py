"""
Central Hub - Main Launcher Scene

The central hub is the main entry point for the CosyVoice system.
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
import json

# Add project root to path
# content/simulation/scenes/hub/hub_scene.py -> scenes -> simulation -> content -> CosySim (5 parents)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from engine.assets import AssetManager, CharacterAsset, SceneAsset
from engine.config import ConfigManager


# Page config
st.set_page_config(
    page_title="CosyVoice Central Hub",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #4F46E5 0%, #7C3AED 50%, #EC4899 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
        text-align: center;
    }
    .subtitle {
        font-size: 1.3rem;
        color: #6B7280;
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
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
    }
    .quick-stat {
        background: white;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin-bottom: 0.5rem;
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
    st.markdown('<h1 class="main-header">🏠 CosyVoice Central Hub</h1>', unsafe_allow_html=True)
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


def show_scene_launcher():
    """Scene launcher with cards"""
    st.header("🎮 Available Scenes")
    
    # Define available scenes
    scenes = [
        {
            "name": "Phone Scene",
            "icon": "📱",
            "description": "Simulated Android phone with texting, calls, photos",
            "port": 5555,
            "script": "content/simulation/scenes/phone/phone_scene.py",
            "color": "#667eea"
        },
        {
            "name": "Dashboard",
            "icon": "📊",
            "description": "Character management and system overview",
            "port": 8501,
            "script": "content/simulation/scenes/dashboard/dashboard_v2.py",
            "color": "#764ba2"
        },
        {
            "name": "Bedroom Scene",
            "icon": "🏠",
            "description": "Private penthouse environment",
            "port": 5556,
            "script": "content/simulation/scenes/bedroom/bedroom_scene.py",
            "color": "#f093fb"
        },
        {
            "name": "Admin Panel",
            "icon": "🎛️",
            "description": "System administration and asset management",
            "port": 8502,
            "script": "content/simulation/scenes/admin/admin_panel.py",
            "color": "#f5576c"
        }
    ]
    
    # Display scene cards in grid
    cols = st.columns(2)
    
    for i, scene in enumerate(scenes):
        with cols[i % 2]:
            st.markdown(
                f"""
                <div class="scene-card" style="background: linear-gradient(135deg, {scene['color']} 0%, {scene['color']}dd 100%);">
                    <div class="scene-icon">{scene['icon']}</div>
                    <div class="scene-name">{scene['name']}</div>
                    <div class="scene-desc">{scene['description']}</div>
                    <div style="margin-top: 1rem; font-size: 0.8rem;">Port: {scene['port']}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"🚀 Launch {scene['name']}", key=f"launch_{i}", use_container_width=True):
                    st.success(f"Launching {scene['name']}...")
                    st.info(f"Run: `python launcher.py --mode play`\nThen select option {i+1}")
            
            with col2:
                if st.button(f"ℹ️ Info", key=f"info_{i}", use_container_width=True):
                    st.info(f"""
                    **{scene['name']}**
                    
                    Port: {scene['port']}
                    Script: {scene['script']}
                    
                    {scene['description']}
                    """)
            
            st.markdown("<br>", unsafe_allow_html=True)
    
    # Create new scene
    st.markdown("---")
    st.subheader("➕ Create New Scene")
    
    with st.form("create_scene"):
        col1, col2 = st.columns(2)
        
        with col1:
            scene_name = st.text_input("Scene Name*", placeholder="My Custom Scene")
            scene_type = st.selectbox("Scene Type", ["phone", "dashboard", "bedroom", "custom"])
            scene_port = st.number_input("Port", min_value=5000, max_value=9000, value=5557)
        
        with col2:
            scene_desc = st.text_area("Description", placeholder="Describe your scene...")
            scene_chars = st.text_input("Characters (IDs, comma-separated)", placeholder="char-001, char-002")
            scene_tags = st.text_input("Tags (comma-separated)", placeholder="custom, experimental")
        
        if st.form_submit_button("✨ Create Scene"):
            if not scene_name:
                st.error("Scene name is required!")
            else:
                try:
                    from engine.assets import SceneAsset
                    
                    char_list = [c.strip() for c in scene_chars.split(",")] if scene_chars else []
                    tag_list = [t.strip() for t in scene_tags.split(",")] if scene_tags else []
                    
                    scene = SceneAsset.create(
                        name=scene_name,
                        description=scene_desc,
                        scene_type=scene_type,
                        server_config={"host": "localhost", "port": scene_port},
                        characters=char_list,
                        tags=tag_list
                    )
                    
                    st.session_state.asset_manager.save(scene)
                    st.success(f"✅ Created scene: {scene_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")


def show_tutorials():
    """Interactive tutorials"""
    st.header("📖 Interactive Tutorials")
    
    tutorials = [
        {
            "title": "🚀 Getting Started",
            "description": "Learn the basics of CosyVoice",
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
            "name": config.get("system.name", "CosyVoice")
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
