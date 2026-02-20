"""
CosySim Admin Control Panel — thin Streamlit router.

All page logic lives in ``pages/`` submodules.
This file handles page config, sidebar navigation, and session state.
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

from engine.assets import AssetManager
from engine.config import ConfigManager

# ── Page modules ───────────────────────────────────────────────────────
from content.scenes.admin.pages import (
    dashboard,
    logs,
    chains,
    config_editor,
    character_manager,
    scene_manager,
    rag_editor,
    media,
    lmstudio,
    god_mode,
    backup,
    assets,
    kpi,
)


# ── Streamlit page config ─────────────────────────────────────────────
st.set_page_config(
    page_title="CosySim Admin Panel",
    page_icon="🎛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Dark theme
from content.shared.streamlit_theme import inject_dark_theme
inject_dark_theme()

# Extra CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem; font-weight: bold;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    if "asset_manager" not in st.session_state:
        st.session_state.asset_manager = AssetManager()
    if "config" not in st.session_state:
        st.session_state.config = ConfigManager()
    if "god_mode" not in st.session_state:
        st.session_state.god_mode = False


# ── Page registry ──────────────────────────────────────────────────────
_PAGES = {
    "📊 Dashboard":        dashboard.render,
    "🗂️ Asset Browser":    assets.render_browser,
    "👥 Character Manager": character_manager.render,
    "🎭 Scene Manager":    scene_manager.render,
    "🧠 Personality Library": assets.render_personality_library,
    "⚙️ Configuration":    config_editor.render,
    "💾 Database":          assets.render_database,
    "🔍 Search & Filter":  assets.render_search,
    "🖼️ Media Gallery":    media.render,
    "🎨 Asset Generator":  assets.render_generator,
    "🔗 Dependency Graph":  assets.render_dependency_graph,
    "📜 Log Viewer":       logs.render,
    "📈 KPI Dashboard":    kpi.render,
    "🔗 Event Chains":     chains.render,
    "✏️ RAG Editor":       rag_editor.render,
    "🤖 LM Studio":       lmstudio.render,
    "👑 GOD Mode":         god_mode.render,
    "💾 Backup & Restore": backup.render,
}


def main():
    init_session_state()

    # Header
    st.markdown('<h1 class="main-header">🎛️ CosySim Admin Panel</h1>', unsafe_allow_html=True)

    # GOD mode banner
    if st.session_state.get("god_mode"):
        st.markdown(
            '<div style="background:#dc3545;color:#fff;padding:8px;border-radius:6px;'
            'text-align:center;font-weight:bold;">👑 GOD MODE ACTIVE</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Sidebar ────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## Navigation")

        page = st.radio(
            "Select Section",
            list(_PAGES.keys()),
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown("### Quick Stats")
        try:
            stats = st.session_state.asset_manager.get_stats()
            st.metric("Total Assets", stats["total_assets"])
            st.metric("Asset Types", len(stats["registered_types"]))
            st.metric("Tags", stats["total_tags"])
        except Exception:
            st.info("Stats unavailable")

        st.markdown("---")
        st.markdown("**System Status**: 🟢 Online")
        st.markdown(f"**Time**: {datetime.now().strftime('%H:%M:%S')}")

    # ── Route to page module ──────────────────────────────────────────
    render_fn = _PAGES.get(page, dashboard.render)
    render_fn()


if __name__ == "__main__":
    main()
