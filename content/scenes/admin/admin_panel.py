"""
Admin Control Panel

System administration dashboard for managing assets, characters, scenes, and configuration.
"""

import streamlit as st
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

from engine.assets import (
    AssetManager,
    CharacterAsset,
    PersonalityAsset,
    RoleAsset,
    SceneAsset,
    AudioAsset,
    ImageAsset,
    VideoAsset,
    MessageAsset
)
from engine.config import ConfigManager


# Page config
st.set_page_config(
    page_title="CosySim Admin Panel",
    page_icon="🎛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem;
    }
    .stat-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .stat-value {
        font-size: 2.5rem;
        font-weight: bold;
    }
    .stat-label {
        font-size: 1rem;
        opacity: 0.9;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables"""
    if 'asset_manager' not in st.session_state:
        st.session_state.asset_manager = AssetManager()
    if 'config' not in st.session_state:
        st.session_state.config = ConfigManager()
    if 'selected_asset' not in st.session_state:
        st.session_state.selected_asset = None


def main():
    """Main admin panel"""
    init_session_state()
    
    # Header
    st.markdown('<h1 class="main-header">🎛️ CosySim Admin Panel</h1>', unsafe_allow_html=True)
    st.markdown("**Unified system management for assets, characters, scenes, and configuration**")
    st.markdown("---")
    
    # Sidebar navigation
    with st.sidebar:
        st.markdown("## Navigation")
        
        page = st.radio(
            "Select Section",
            [
                "📊 Dashboard",
                "🗂️ Asset Browser",
                "👥 Character Manager",
                "🎭 Scene Manager",
                "🧠 Personality Library",
                "⚙️ Configuration",
                "💾 Database",
                "🔍 Search & Filter",
                "🖼️ Media Gallery",
                "🎨 Asset Generator",
                "🔗 Dependency Graph",
                "📜 Log Viewer",
                "⛓️ Event Chains",
                "🤖 LM Studio",
                "📈 Performance Monitor",
                "🗄️ Backup & Restore",
                "🎮 MCP Monitor",
            ],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        st.markdown("### Quick Stats")
        stats = st.session_state.asset_manager.get_stats()
        st.metric("Total Assets", stats['total_assets'])
        st.metric("Asset Types", len(stats['registered_types']))
        st.metric("Tags", stats['total_tags'])
        
        st.markdown("---")
        st.markdown("**System Status**: 🟢 Online")
        st.markdown(f"**Time**: {datetime.now().strftime('%H:%M:%S')}")
    
    # Main content based on page selection
    PAGE_MAP = {
        "📊 Dashboard":         show_dashboard,
        "🗂️ Asset Browser":     show_asset_browser,
        "👥 Character Manager":  show_character_manager,
        "🎭 Scene Manager":      show_scene_manager,
        "🧠 Personality Library": show_personality_library,
        "⚙️ Configuration":      show_configuration,
        "💾 Database":           show_database,
        "🔍 Search & Filter":    show_search,
        "🖼️ Media Gallery":      show_media_gallery,
        "🔗 Dependency Graph":   show_dependency_graph,
        "🎨 Asset Generator":    show_asset_generator,
        "📜 Log Viewer":         show_log_viewer,
        "⛓️ Event Chains":       show_event_chains,
        "🤖 LM Studio":          show_lmstudio,
        "📈 Performance Monitor": show_performance_monitor,
        "🗄️ Backup & Restore":   show_backup_restore,
        "🎮 MCP Monitor":        show_mcp_monitor,
    }
    handler = PAGE_MAP.get(page)
    if handler:
        try:
            handler()
        except Exception as exc:
            st.error(f"⚠️ Error loading **{page}**: {exc}")
            import traceback
            st.code(traceback.format_exc(), language="python")
    else:
        st.warning(f"Unknown page: {page}")


def show_dashboard():
    """System dashboard with overview"""
    st.header("📊 System Dashboard")
    
    # Get statistics
    stats = st.session_state.asset_manager.get_stats()
    
    # Overview metrics in columns
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(
            f"""
            <div class="stat-card">
                <div class="stat-value">{stats['total_assets']}</div>
                <div class="stat-label">Total Assets</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    with col2:
        st.markdown(
            f"""
            <div class="stat-card">
                <div class="stat-value">{stats['by_type'].get('character', 0)}</div>
                <div class="stat-label">Characters</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    with col3:
        st.markdown(
            f"""
            <div class="stat-card">
                <div class="stat-value">{stats['by_type'].get('scene', 0)}</div>
                <div class="stat-label">Scenes</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    with col4:
        st.markdown(
            f"""
            <div class="stat-card">
                <div class="stat-value">{stats['total_tags']}</div>
                <div class="stat-label">Tags</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    st.markdown("##")
    
    # Asset breakdown
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📦 Assets by Type")
        if stats['by_type']:
            for asset_type, count in sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True):
                st.metric(asset_type.title(), count)
        else:
            st.info("No assets yet")
    
    with col2:
        st.subheader("📋 Registered Asset Types")
        for asset_type in stats['registered_types']:
            st.markdown(f"- **{asset_type}**")
    
    st.markdown("---")
    
    # Recent activity
    st.subheader("🕒 Recent Assets")
    recent = st.session_state.asset_manager.search(limit=10)
    if recent:
        for asset_data in recent:
            with st.expander(f"{asset_data['type'].title()}: {asset_data['id'][:8]}..."):
                st.json(asset_data['metadata'])
    else:
        st.info("No assets found")
    
    # Quick actions
    st.markdown("---")
    st.subheader("⚡ Quick Actions")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("➕ Create Character", use_container_width=True):
            st.info("Switch to Character Manager tab")
    
    with col2:
        if st.button("🧹 Clean Orphans", use_container_width=True):
            orphans = st.session_state.asset_manager.find_orphans()
            if orphans:
                st.warning(f"Found {len(orphans)} orphaned assets")
            else:
                st.success("No orphans found!")
    
    with col3:
        if st.button("📊 Export Stats", use_container_width=True):
            st.download_button(
                "Download Stats JSON",
                data=json.dumps(stats, indent=2),
                file_name=f"stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )


def show_asset_browser():
    """Browse and manage all assets"""
    st.header("🗂️ Asset Browser")
    
    # Filters
    col1, col2, col3 = st.columns(3)
    
    with col1:
        asset_type = st.selectbox(
            "Asset Type",
            ["All"] + st.session_state.asset_manager.get_stats()['registered_types']
        )
    
    with col2:
        search_tag = st.text_input("Search by Tag")
    
    with col3:
        limit = st.number_input("Results", min_value=10, max_value=100, value=20)
    
    # Search
    search_params = {}
    if asset_type != "All":
        search_params['asset_type'] = asset_type
    if search_tag:
        search_params['tags'] = [search_tag]
    search_params['limit'] = limit
    
    results = st.session_state.asset_manager.search(**search_params)
    
    st.markdown(f"**Found {len(results)} assets**")
    st.markdown("---")
    
    # Display results
    for asset_data in results:
        with st.expander(f"{asset_data['type'].title()}: {asset_data['id'][:16]}..."):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.json(asset_data)
            
            with col2:
                if st.button("🗑️ Delete", key=f"del_{asset_data['id']}"):
                    try:
                        st.session_state.asset_manager.delete(asset_data['id'])
                        st.success("Deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


def show_character_manager():
    """Manage characters"""
    st.header("👥 Character Manager")
    
    tab1, tab2 = st.tabs(["📋 Character List", "➕ Create Character"])
    
    with tab1:
        characters = st.session_state.asset_manager.search(asset_type="character")
        
        if not characters:
            st.info("No characters yet. Create one in the 'Create Character' tab!")
        else:
            for char_data in characters:
                char = st.session_state.asset_manager.load("character", char_data['id'])
                
                with st.expander(f"**{char.name}** ({char_data['id'][:8]}...)"):
                    view_col, edit_col = st.columns([2, 1])

                    with view_col:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Description**: {char.description}")
                            st.markdown(f"**Age**: {char.age}")
                            st.markdown(f"**Gender**: {char.gender}")
                            st.markdown(f"**Messaging Frequency**: {char.messaging_frequency}")
                            st.markdown(f"**Autonomy Level**: {char.autonomy_level}")
                        with col2:
                            st.markdown(f"**Hair Color**: {char.hair_color}")
                            st.markdown(f"**Eye Color**: {char.eye_color}")
                            st.markdown(f"**NSFW**: {char.nsfw_enabled}")
                            current_tags = ", ".join(char.metadata.tags) if hasattr(char, 'metadata') else ""
                            st.markdown(f"**Tags**: {current_tags}")

                    with edit_col:
                        if st.button(f"✏️ Edit", key=f"edit_char_{char.id}"):
                            st.session_state[f"editing_{char.id}"] = True
                        if st.button(f"🗑️ Delete {char.name}", key=f"del_char_{char.id}"):
                            st.session_state.asset_manager.delete(char.id)
                            st.success("Deleted!")
                            st.rerun()

                    # Edit form (shown when edit button pressed)
                    if st.session_state.get(f"editing_{char.id}"):
                        st.markdown("---")
                        st.subheader(f"Edit: {char.name}")
                        existing_tags = ", ".join(char.metadata.tags) if hasattr(char, 'metadata') else ""
                        with st.form(f"edit_char_form_{char.id}"):
                            e_name = st.text_input("Name", value=char.name)
                            e_desc = st.text_area("Description", value=char.description or "")
                            e_age  = st.number_input("Age", min_value=18, max_value=100, value=int(char.age or 25))
                            e_gender = st.selectbox("Gender", ["female","male","non-binary","other"],
                                                    index=["female","male","non-binary","other"].index(char.gender or "female"))
                            e_hair = st.text_input("Hair Color", value=char.hair_color or "")
                            e_eye  = st.text_input("Eye Color",  value=char.eye_color or "")
                            _freq_opts = ["low", "medium", "high"]
                            _cur_freq = char.messaging_frequency if char.messaging_frequency in _freq_opts else "medium"
                            e_freq = st.selectbox("Messaging Frequency", _freq_opts,
                                                  index=_freq_opts.index(_cur_freq))
                            e_auto = st.slider("Autonomy Level", 0.0, 1.0,
                                               float(char.autonomy_level or 0.5), 0.1)
                            e_nsfw = st.checkbox("NSFW Enabled", value=bool(char.nsfw_enabled))
                            e_tags = st.text_input("Tags (comma-separated)", value=existing_tags)

                            c1, c2 = st.columns(2)
                            save_clicked   = c1.form_submit_button("💾 Save")
                            cancel_clicked = c2.form_submit_button("✕ Cancel")

                        if save_clicked:
                            try:
                                tag_list = [t.strip() for t in e_tags.split(",") if t.strip()]
                                char.name              = e_name
                                char.description       = e_desc
                                char.age               = e_age
                                char.gender            = e_gender
                                char.hair_color        = e_hair
                                char.eye_color         = e_eye
                                char.messaging_frequency = e_freq
                                char.autonomy_level    = e_auto
                                char.nsfw_enabled      = e_nsfw
                                if hasattr(char, 'metadata'):
                                    char.metadata.tags = tag_list
                                st.session_state.asset_manager.save(char)
                                st.session_state[f"editing_{char.id}"] = False
                                st.success("✅ Saved!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Save failed: {e}")

                        if cancel_clicked:
                            st.session_state[f"editing_{char.id}"] = False
                            st.rerun()
    
    with tab2:
        st.subheader("Create New Character")
        if st.session_state.pop("_char_created", None):
            st.success(f"✅ Character created successfully!")
        
        with st.form("create_character"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Name*", placeholder="Alice")
                description = st.text_area("Description", placeholder="A friendly virtual companion")
                age = st.number_input("Age", min_value=18, max_value=100, value=25)
                gender = st.selectbox("Gender", ["female", "male", "non-binary", "other"])
                hair_color = st.text_input("Hair Color", placeholder="blonde")
                eye_color = st.text_input("Eye Color", placeholder="blue")
            
            with col2:
                messaging_freq = st.selectbox("Messaging Frequency", ["low", "medium", "high"])
                autonomy = st.slider("Autonomy Level", 0.0, 1.0, 0.5, 0.1)
                nsfw = st.checkbox("NSFW Enabled")
                tags = st.text_input("Tags (comma-separated)", placeholder="companion, friendly")
            
            if st.form_submit_button("✨ Create Character"):
                if not name:
                    st.error("Name is required!")
                else:
                    try:
                        tag_list = [t.strip() for t in tags.split(",")] if tags else []
                        char = CharacterAsset.create(
                            name=name,
                            description=description,
                            age=age,
                            gender=gender,
                            hair_color=hair_color,
                            eye_color=eye_color,
                            messaging_frequency=messaging_freq,
                            autonomy_level=autonomy,
                            nsfw_enabled=nsfw,
                            tags=tag_list
                        )
                        st.session_state.asset_manager.save(char)
                        st.session_state["_char_created"] = name
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


def show_scene_manager():
    """Manage scenes"""
    st.header("🎭 Scene Manager")
    
    tab1, tab2 = st.tabs(["📋 Scene List", "➕ Create Scene"])
    
    with tab1:
        scenes = st.session_state.asset_manager.search(asset_type="scene")
        
        if not scenes:
            st.info("No scenes yet. Create one in the 'Create Scene' tab!")
        else:
            for scene_data in scenes:
                scene = st.session_state.asset_manager.load("scene", scene_data['id'])
                
                with st.expander(f"**{scene.name}** ({scene_data['id'][:8]}...)"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"**Description**: {scene.description}")
                        st.markdown(f"**Type**: {scene.scene_type}")
                        st.markdown(f"**Characters**: {len(scene.characters)}")
                        st.markdown(f"**Port**: {scene.server_config.get('port', 'N/A')}")
                    
                    with col2:
                        st.markdown(f"**Tags**: {', '.join(scene.metadata.tags)}")
                        st.json(scene.server_config)
                    
                    if st.button(f"🗑️ Delete {scene.name}", key=f"del_scene_{scene.id}"):
                        st.session_state.asset_manager.delete(scene.id)
                        st.success("Deleted!")
                        st.rerun()
    
    with tab2:
        st.subheader("Create New Scene")
        
        with st.form("create_scene"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Name*", placeholder="My Scene")
                description = st.text_area("Description", placeholder="Scene description")
                scene_type = st.selectbox("Scene Type", ["phone", "dashboard", "bedroom", "lounge", "casino", "gallery", "custom"])
                port = st.number_input("Port", min_value=5000, max_value=9000, value=5557)
            
            with col2:
                characters = st.text_input("Character IDs (comma-separated)", placeholder="char-001, char-002")
                tags = st.text_input("Tags (comma-separated)", placeholder="custom, test")
                enable_debug = st.checkbox("Enable Debug Mode")
            
            if st.form_submit_button("✨ Create Scene"):
                if not name:
                    st.error("Name is required!")
                else:
                    try:
                        char_list = [c.strip() for c in characters.split(",")] if characters else []
                        tag_list = [t.strip() for t in tags.split(",")] if tags else []
                        
                        from engine.assets import SceneAsset
                        scene = SceneAsset.create(
                            name=name,
                            description=description,
                            scene_type=scene_type,
                            server_config={"host": "localhost", "port": port, "debug": enable_debug},
                            characters=char_list,
                            tags=tag_list
                        )
                        st.session_state.asset_manager.save(scene)
                        st.success(f"✅ Created scene: {name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


def show_personality_library():
    """Manage personalities"""
    st.header("🧠 Personality Library")
    
    tab1, tab2 = st.tabs(["📋 Personality List", "➕ Create Personality"])
    
    with tab1:
        personalities = st.session_state.asset_manager.search(asset_type="personality")
        
        if not personalities:
            st.info("No personalities yet. Create one in the 'Create Personality' tab!")
        else:
            for pers_data in personalities:
                pers = st.session_state.asset_manager.load("personality", pers_data['id'])
                
                with st.expander(f"**{pers.name}** ({pers_data['id'][:8]}...)"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"**Description**: {pers.description}")
                        st.markdown(f"**Type**: {pers.personality_type}")
                        st.markdown(f"**Traits**: {', '.join(pers.traits)}")
                    
                    with col2:
                        st.markdown("**Parameters:**")
                        st.markdown(f"- Warmth: {pers.warmth}")
                        st.markdown(f"- Formality: {pers.formality}")
                        st.markdown(f"- Humor: {pers.humor}")
                        st.markdown(f"- Flirtiness: {pers.flirtiness}")
                    
                    st.markdown("**System Prompt:**")
                    st.text(pers.system_prompt[:200] + "..." if len(pers.system_prompt) > 200 else pers.system_prompt)
                    
                    if st.button(f"🗑️ Delete {pers.name}", key=f"del_pers_{pers.id}"):
                        st.session_state.asset_manager.delete(pers.id)
                        st.success("Deleted!")
                        st.rerun()
    
    with tab2:
        st.subheader("Create New Personality")
        
        with st.form("create_personality"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Name*", placeholder="Cheerful")
                description = st.text_area("Description", placeholder="Happy and energetic personality")
                personality_type = st.text_input("Type", placeholder="friendly", value="friendly")
                system_prompt = st.text_area("System Prompt", placeholder="You are a cheerful companion...")
                traits = st.text_input("Traits (comma-separated)", placeholder="optimistic, energetic, supportive")
            
            with col2:
                warmth = st.slider("Warmth", 0.0, 1.0, 0.7, 0.1)
                formality = st.slider("Formality", 0.0, 1.0, 0.3, 0.1)
                humor = st.slider("Humor", 0.0, 1.0, 0.5, 0.1)
                flirtiness = st.slider("Flirtiness", 0.0, 1.0, 0.5, 0.1)
                intelligence = st.slider("Intelligence", 0.0, 1.0, 0.7, 0.1)
                creativity = st.slider("Creativity", 0.0, 1.0, 0.6, 0.1)
                tags = st.text_input("Tags (comma-separated)", placeholder="positive, energetic")
            
            if st.form_submit_button("✨ Create Personality"):
                if not name:
                    st.error("Name is required!")
                else:
                    try:
                        trait_list = [t.strip() for t in traits.split(",")] if traits else []
                        tag_list = [t.strip() for t in tags.split(",")] if tags else []
                        
                        from engine.assets import PersonalityAsset
                        personality = PersonalityAsset.create(
                            name=name,
                            description=description,
                            personality_type=personality_type,
                            system_prompt=system_prompt,
                            traits=trait_list,
                            warmth=warmth,
                            formality=formality,
                            humor=humor,
                            flirtiness=flirtiness,
                            intelligence=intelligence,
                            creativity=creativity,
                            tags=tag_list
                        )
                        st.session_state.asset_manager.save(personality)
                        st.success(f"✅ Created personality: {name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


def show_configuration():
    """System configuration — live editor that writes back to config/default.yaml."""
    st.header("⚙️ Configuration")

    config = st.session_state.config

    tab1, tab2, tab3 = st.tabs(["📋 View Config", "✏️ Edit Config", "🔄 Environment"])

    with tab1:
        st.subheader("Current Configuration")
        st.json(dict(config._config))

    with tab2:
        st.subheader("Edit Configuration")
        st.markdown("Changes are written directly to **config/default.yaml** and take effect on the next server restart.")

        try:
            import yaml
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"

            def _load_yaml():
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}

            def _save_yaml(data: dict):
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            raw = _load_yaml()

            # ── LLM / LMStudio ────────────────────────────────────────
            st.markdown("### 🤖 LLM / LMStudio")
            c1, c2 = st.columns(2)
            with c1:
                llm_base_url = st.text_input(
                    "LMStudio Base URL",
                    value=raw.get("llm", {}).get("base_url", "http://localhost:1234/v1"),
                    key="cfg_llm_base_url",
                )
                llm_model = st.text_input(
                    "Model name",
                    value=raw.get("llm", {}).get("model", "qwen3-vl-8b"),
                    key="cfg_llm_model",
                    help="Model ID that LMStudio has loaded. Leave blank to auto-detect first loaded model.",
                )
            with c2:
                llm_temp = st.slider(
                    "Temperature", 0.0, 2.0,
                    float(raw.get("llm", {}).get("temperature", 0.7)), 0.05,
                    key="cfg_llm_temp",
                )
                llm_max_tokens = st.number_input(
                    "Max tokens", 100, 32000,
                    int(raw.get("llm", {}).get("max_tokens", 5000)),
                    key="cfg_llm_max_tokens",
                )
            lms_host = st.text_input(
                "LMStudio host",
                value=raw.get("lmstudio", {}).get("host", "127.0.0.1"),
                key="cfg_lms_host",
            )
            lms_port = st.number_input(
                "LMStudio port", 1, 65535,
                int(raw.get("lmstudio", {}).get("port", 1234)),
                key="cfg_lms_port",
            )
            lms_mcp = st.checkbox(
                "Enable MCP integrations",
                value=bool(raw.get("lmstudio", {}).get("mcp_enabled", False)),
                key="cfg_lms_mcp",
            )

            st.divider()

            # ── ComfyUI ───────────────────────────────────────────────
            st.markdown("### 🎨 ComfyUI (Image/Video Generation)")
            comfy_enabled = st.checkbox(
                "ComfyUI enabled",
                value=bool(raw.get("comfyui", {}).get("enabled", False)),
                key="cfg_comfy_enabled",
            )
            comfy_url = st.text_input(
                "ComfyUI base URL",
                value=raw.get("comfyui", {}).get("base_url", "http://localhost:8188"),
                key="cfg_comfy_url",
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                comfy_steps = st.number_input(
                    "Steps", 5, 150,
                    int(raw.get("comfyui", {}).get("generation", {}).get("steps", 30)),
                    key="cfg_comfy_steps",
                )
            with c2:
                comfy_cfg = st.number_input(
                    "CFG scale", 1.0, 20.0,
                    float(raw.get("comfyui", {}).get("generation", {}).get("cfg", 5.5)),
                    key="cfg_comfy_cfg",
                    step=0.5,
                )
            with c3:
                comfy_sampler = st.selectbox(
                    "Sampler",
                    ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "ddim", "lcm"],
                    index=["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "ddim", "lcm"].index(
                        raw.get("comfyui", {}).get("generation", {}).get("sampler_name", "euler")
                    ) if raw.get("comfyui", {}).get("generation", {}).get("sampler_name", "euler") in [
                        "euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "ddim", "lcm"
                    ] else 0,
                    key="cfg_comfy_sampler",
                )

            st.divider()

            # ── TTS ───────────────────────────────────────────────────
            st.markdown("### 🎤 TTS (Text-to-Speech)")
            c1, c2 = st.columns(2)
            with c1:
                tts_server_url = st.text_input(
                    "TTS server URL",
                    value=raw.get("tts", {}).get("server_url", "http://localhost:8600"),
                    key="cfg_tts_url",
                )
                tts_model = st.text_input(
                    "TTS model name",
                    value=raw.get("tts", {}).get("model_name", "CosyVoice-300M"),
                    key="cfg_tts_model",
                )
            with c2:
                tts_engine = st.selectbox(
                    "TTS engine",
                    ["cosyvoice", "coqui", "piper", "bark", "none"],
                    index=["cosyvoice", "coqui", "piper", "bark", "none"].index(
                        raw.get("tts", {}).get("engine", "cosyvoice")
                    ) if raw.get("tts", {}).get("engine", "cosyvoice") in ["cosyvoice", "coqui", "piper", "bark", "none"] else 0,
                    key="cfg_tts_engine",
                )
                tts_device = st.selectbox(
                    "TTS compute device",
                    ["cuda", "cpu"],
                    index=0 if raw.get("tts", {}).get("device", "cuda") == "cuda" else 1,
                    key="cfg_tts_device",
                )

            st.divider()

            # ── Characters ───────────────────────────────────────────
            st.markdown("### 👥 Character System")
            c1, c2 = st.columns(2)
            with c1:
                char_personality = st.selectbox(
                    "Default personality",
                    ["playful", "shy", "confident", "caring", "mysterious", "dominant", "submissive"],
                    index=["playful", "shy", "confident", "caring", "mysterious", "dominant", "submissive"].index(
                        raw.get("characters", {}).get("default_personality", "playful")
                    ) if raw.get("characters", {}).get("default_personality", "playful") in [
                        "playful", "shy", "confident", "caring", "mysterious", "dominant", "submissive"
                    ] else 0,
                    key="cfg_char_personality",
                )
                char_max_ctx = st.number_input(
                    "Max context messages", 10, 1000,
                    int(raw.get("characters", {}).get("memory", {}).get("max_context_messages", 200)),
                    key="cfg_char_max_ctx",
                )
            with c2:
                char_importance = st.slider(
                    "Memory importance threshold", 0.0, 1.0,
                    float(raw.get("characters", {}).get("memory", {}).get("importance_threshold", 0.5)),
                    0.05,
                    key="cfg_char_importance",
                )

            st.divider()

            # ── Services ─────────────────────────────────────────────
            st.markdown("### ⚙️ Services")
            auto_enabled = st.checkbox(
                "Autonomous messenger enabled",
                value=bool(raw.get("services", {}).get("autonomous_messenger", {}).get("enabled", True)),
                key="cfg_auto_enabled",
            )
            auto_freq = st.selectbox(
                "Autonomous message frequency",
                ["low", "moderate", "high"],
                index=["low", "moderate", "high"].index(
                    raw.get("services", {}).get("autonomous_messenger", {}).get("frequency", "moderate")
                ),
                key="cfg_auto_freq",
            )
            c1, c2 = st.columns(2)
            with c1:
                auto_start = st.number_input(
                    "Active hours start (0-23)", 0, 23,
                    int(raw.get("services", {}).get("autonomous_messenger", {}).get("active_hours", {}).get("start", 8)),
                    key="cfg_auto_start",
                )
            with c2:
                auto_end = st.number_input(
                    "Active hours end (0-23)", 0, 23,
                    int(raw.get("services", {}).get("autonomous_messenger", {}).get("active_hours", {}).get("end", 23)),
                    key="cfg_auto_end",
                )

            st.divider()

            # ── Logging ──────────────────────────────────────────────
            st.markdown("### 📜 Logging")
            log_level = st.selectbox(
                "Log level",
                ["DEBUG", "INFO", "WARNING", "ERROR"],
                index=["DEBUG", "INFO", "WARNING", "ERROR"].index(
                    raw.get("logging", {}).get("level", "INFO")
                ) if raw.get("logging", {}).get("level", "INFO") in ["DEBUG", "INFO", "WARNING", "ERROR"] else 1,
                key="cfg_log_level",
            )

            st.divider()

            # ── Save ─────────────────────────────────────────────────
            if st.button("💾 Save Configuration", type="primary", use_container_width=True):
                try:
                    raw.setdefault("llm", {})
                    raw["llm"]["base_url"] = llm_base_url
                    raw["llm"]["model"] = llm_model
                    raw["llm"]["temperature"] = float(llm_temp)
                    raw["llm"]["max_tokens"] = int(llm_max_tokens)

                    raw.setdefault("lmstudio", {})
                    raw["lmstudio"]["host"] = lms_host
                    raw["lmstudio"]["port"] = int(lms_port)
                    raw["lmstudio"]["base_url"] = f"http://{lms_host}:{lms_port}"
                    raw["lmstudio"]["mcp_enabled"] = lms_mcp

                    raw.setdefault("comfyui", {})
                    raw["comfyui"]["enabled"] = comfy_enabled
                    raw["comfyui"]["base_url"] = comfy_url
                    raw["comfyui"].setdefault("generation", {})
                    raw["comfyui"]["generation"]["steps"] = int(comfy_steps)
                    raw["comfyui"]["generation"]["cfg"] = float(comfy_cfg)
                    raw["comfyui"]["generation"]["sampler_name"] = comfy_sampler

                    raw.setdefault("tts", {})
                    raw["tts"]["server_url"] = tts_server_url
                    raw["tts"]["model_name"] = tts_model
                    raw["tts"]["engine"] = tts_engine
                    raw["tts"]["device"] = tts_device

                    raw.setdefault("characters", {})
                    raw["characters"]["default_personality"] = char_personality
                    raw["characters"].setdefault("memory", {})
                    raw["characters"]["memory"]["max_context_messages"] = int(char_max_ctx)
                    raw["characters"]["memory"]["importance_threshold"] = float(char_importance)

                    raw.setdefault("services", {})
                    raw["services"].setdefault("autonomous_messenger", {})
                    raw["services"]["autonomous_messenger"]["enabled"] = auto_enabled
                    raw["services"]["autonomous_messenger"]["frequency"] = auto_freq
                    raw["services"]["autonomous_messenger"].setdefault("active_hours", {})
                    raw["services"]["autonomous_messenger"]["active_hours"]["start"] = int(auto_start)
                    raw["services"]["autonomous_messenger"]["active_hours"]["end"] = int(auto_end)

                    raw.setdefault("logging", {})
                    raw["logging"]["level"] = log_level

                    _save_yaml(raw)
                    # Reload the in-memory config manager so it reflects new values
                    st.session_state.config = ConfigManager()
                    st.success("✅ Configuration saved to config/default.yaml")
                    st.rerun()
                except Exception as save_err:
                    st.error(f"Save failed: {save_err}")

        except ImportError:
            st.warning("PyYAML not installed. Run: pip install pyyaml")
        except Exception as e:
            st.error(f"Config editor error: {e}")

    with tab3:
        st.subheader("Environment Settings")

        current_env = config.get("system.environment", "development")
        st.markdown(f"**Current Environment:** `{current_env}`")

        st.markdown("**Environment Variables:**")
        import os
        env_vars = {k: v for k, v in os.environ.items() if k.startswith("COSYSIM_") or k.startswith("COSYVOICE_")}
        if env_vars:
            st.json(env_vars)
        else:
            st.info("No COSYSIM_* / COSYVOICE_* environment variables set")


def show_database():
    """Database management"""
    st.header("💾 Database Management")
    
    tab1, tab2, tab3 = st.tabs(["📊 Statistics", "🗄️ Asset DB", "🧠 RAG Memory"])
    
    with tab1:
        st.subheader("Asset Database Statistics")
        stats = st.session_state.asset_manager.get_stats()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Assets", stats['total_assets'])
        with col2:
            st.metric("Asset Types", len(stats['registered_types']))
        with col3:
            st.metric("Total Tags", stats['total_tags'])
        
        st.markdown("---")
        st.subheader("Asset Breakdown")
        st.json(stats['by_type'])
    
    with tab2:
        st.subheader("Asset Database")
        st.info("Database browser coming soon")
        
        # Show DB path
        import sqlite3
        from engine.assets import AssetManager
        manager = AssetManager()
        st.markdown(f"**Database Path:** `{manager.db_path}`")
        
        # Connection info
        try:
            conn = sqlite3.connect(manager.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            st.markdown("**Tables:**")
            for table in tables:
                st.markdown(f"- {table}")
        except Exception as e:
            st.error(f"Error: {e}")
    
    with tab3:
        st.subheader("RAG Memory (ChromaDB)")
        st.info("RAG memory viewer coming soon")


def show_search():
    """Advanced search"""
    st.header("🔍 Advanced Search")
    
    st.subheader("Search Assets")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        search_type = st.selectbox(
            "Asset Type",
            ["All"] + st.session_state.asset_manager.get_stats()['registered_types']
        )
    
    with col2:
        search_tags = st.text_input("Tags (comma-separated)", placeholder="tag1, tag2")
    
    with col3:
        limit = st.number_input("Max Results", min_value=10, max_value=100, value=20)
    
    if st.button("🔍 Search", use_container_width=True):
        search_params = {}
        if search_type != "All":
            search_params['asset_type'] = search_type
        if search_tags:
            search_params['tags'] = [t.strip() for t in search_tags.split(",")]
        search_params['limit'] = limit
        
        results = st.session_state.asset_manager.search(**search_params)
        
        st.markdown(f"**Found {len(results)} assets**")
        st.markdown("---")
        
        for result in results:
            with st.expander(f"{result['type'].title()}: {result['id'][:16]}..."):
                st.json(result)


def show_media_gallery():
    """Media gallery with thumbnails"""
    st.header("🖼️ Media Gallery")
    
    st.markdown("Browse all media assets with thumbnails")
    
    # Filter by media type
    col1, col2 = st.columns([3, 1])
    
    with col1:
        media_type = st.radio(
            "Media Type",
            ["All", "Images", "Videos", "Audio"],
            horizontal=True
        )
    
    with col2:
        grid_cols = st.slider("Columns", 2, 5, 3)
    
    # Search media assets
    if media_type == "Images":
        results = st.session_state.asset_manager.search(asset_type="image", limit=50)
    elif media_type == "Videos":
        results = st.session_state.asset_manager.search(asset_type="video", limit=50)
    elif media_type == "Audio":
        results = st.session_state.asset_manager.search(asset_type="audio", limit=50)
    else:
        # Get all media types
        results_image = st.session_state.asset_manager.search(asset_type="image", limit=50)
        results_video = st.session_state.asset_manager.search(asset_type="video", limit=50)
        results_audio = st.session_state.asset_manager.search(asset_type="audio", limit=50)
        results = results_image + results_video + results_audio
    
    st.markdown(f"**Found {len(results)} media assets**")
    st.markdown("---")
    
    if results:
        # Display in grid
        cols = st.columns(grid_cols)
        for i, asset_data in enumerate(results):
            with cols[i % grid_cols]:
                asset = st.session_state.asset_manager.load(asset_data['type'], asset_data['id'])
                
                # Display thumbnail/preview
                if asset_data['type'] == "image" and hasattr(asset, 'filepath'):
                    try:
                        from PIL import Image
                        import os
                        if os.path.exists(asset.filepath):
                            img = Image.open(asset.filepath)
                            st.image(img, use_container_width=True)
                        else:
                            st.info("🖼️ Image file not found")
                    except Exception as e:
                        st.error(f"Error: {e}")
                
                elif asset_data['type'] == "video" and hasattr(asset, 'filepath'):
                    try:
                        import os
                        if os.path.exists(asset.filepath):
                            st.video(asset.filepath)
                        else:
                            st.info("🎬 Video file not found")
                    except Exception:
                        st.info("🎬 Video")
                
                elif asset_data['type'] == "audio" and hasattr(asset, 'filepath'):
                    try:
                        import os
                        if os.path.exists(asset.filepath):
                            st.audio(asset.filepath)
                        else:
                            st.info("🎵 Audio file not found")
                    except Exception:
                        st.info("🎵 Audio")
                
                # Asset info
                st.caption(f"{asset_data['type'].title()}")
                st.caption(f"ID: {asset_data['id'][:8]}...")
    else:
        st.info("No media assets found")


def show_dependency_graph():
    """Visualize asset dependencies"""
    st.header("🔗 Dependency Graph")
    
    all_assets = st.session_state.asset_manager.search(limit=1000)
    
    if not all_assets:
        st.info("No assets to visualize")
        return
    
    # Build dependency data
    nodes = []
    edges = []
    
    for asset in all_assets:
        nodes.append({"id": asset['id'], "type": asset['type']})
        try:
            deps = st.session_state.asset_manager.get_dependencies(asset['id'])
            for dep_id in deps:
                edges.append({"source": asset['id'], "target": dep_id})
        except:
            pass
    
    st.markdown(f"**Nodes:** {len(nodes)} | **Edges:** {len(edges)}")
    
    if edges:
        st.subheader("Dependencies")
        for edge in edges[:20]:
            st.markdown(f"- `{edge['source'][:8]}...` → `{edge['target'][:8]}...`")
        if len(edges) > 20:
            st.info(f"... and {len(edges) - 20} more")
    else:
        st.info("No dependencies found")
    
    # Orphan detection
    st.markdown("---")
    orphans = st.session_state.asset_manager.find_orphans()
    if orphans:
        st.warning(f"Found {len(orphans)} orphaned assets")
        if st.button("🧹 Clean All Orphans"):
            for orphan_id in orphans:
                try:
                    st.session_state.asset_manager.delete(orphan_id)
                except:
                    pass
            st.success("Cleaned!")
            st.rerun()
    else:
        st.success("No orphans!")


def show_asset_generator():
    """Generate images, videos, audio and stories via ComfyUI / TTS / LLM."""
    st.header("🎨 Asset Generator")
    st.markdown("Generate media assets directly from the admin panel. Requires ComfyUI and LM Studio (localhost:1234) to be running.")

    tab_img, tab_vid, tab_voice, tab_story = st.tabs(["🖼️ Image", "🎥 Video", "🎤 Voice", "📖 Story"])

    # --- Image ---
    with tab_img:
        st.subheader("Generate Image via ComfyUI")
        c1, c2 = st.columns(2)
        with c1:
            pos_prompt = st.text_area("Positive Prompt", placeholder="beautiful woman, brown hair, green eyes, happy, outdoor, realistic, 8k")
            neg_prompt = st.text_area("Negative Prompt", value="blurry, low quality, nsfw" if True else "")
        with c2:
            img_width  = st.number_input("Width",  value=512, step=64)
            img_height = st.number_input("Height", value=512, step=64)
            img_steps  = st.number_input("Steps",  value=20, min_value=5, max_value=100)
            nsfw_img   = st.checkbox("Allow NSFW")

        if st.button("🎨 Generate Image", type="primary"):
            with st.spinner("Generating via ComfyUI..."):
                try:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
                    from content.simulation.services.comfyui_client import get_comfyui_client
                    client = get_comfyui_client()
                    if not client.is_available():
                        st.error("ComfyUI not reachable. Check config/default.yaml for comfyui.base_url.")
                    else:
                        save_dir = Path(__file__).parent.parent.parent / "simulation" / "media" / "images"
                        save_dir.mkdir(parents=True, exist_ok=True)
                        path = client.generate_image(
                            positive_prompt=pos_prompt,
                            negative_prompt=neg_prompt,
                            save_dir=str(save_dir),
                        )
                        if path:
                            st.image(path, caption="Generated image", use_column_width=True)
                            st.success(f"Saved: {path}")
                        else:
                            st.error("Generation failed or ComfyUI returned no output.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Video ---
    with tab_vid:
        st.subheader("Generate Video Message")
        char_list_vid = []
        try:
            char_list_vid = [c['id'] for c in st.session_state.asset_manager.search(asset_type="character")]
        except Exception:
            pass
        vid_char = st.selectbox("Character", char_list_vid or ["(no characters)"], key="vid_char")
        vid_text = st.text_area("Script / Text", placeholder="Hey, I was thinking about you today...")
        vid_mood = st.selectbox("Mood", ["happy", "flirty", "seductive", "sad", "excited", "romantic"])
        if st.button("🎥 Generate Video Message"):
            with st.spinner("Generating..."):
                try:
                    from content.simulation.database.db import Database
                    from content.simulation.character_system.character import Character
                    from content.simulation.services.media_generator import MediaGenerator
                    from content.simulation.services.voice_message import VoiceMessageGenerator
                    from content.simulation.services.video_message import VideoMessageGenerator
                    db  = Database()
                    mg  = MediaGenerator()
                    vmg = VoiceMessageGenerator(db=db)
                    vdg = VideoMessageGenerator(media_gen=mg, voice_gen=vmg, db=db)
                    char = Character.load(vid_char, db=db)
                    if char:
                        result = vdg.generate_video_message(
                            character_id=char.id,
                            character_name=char.name,
                            character_description=getattr(char, 'appearance', char.description or ''),
                            text=vid_text,
                            mood=vid_mood,
                        )
                        if result:
                            st.success(f"Video created: {result['filename']}")
                            st.video(result['filepath'])
                        else:
                            st.warning("Generation returned nothing. Check ComfyUI and CosyVoice are running.")
                    else:
                        st.error(f"Character {vid_char} not found.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Voice ---
    with tab_voice:
        st.subheader("Generate Voice Message (TTS)")
        char_list_v = []
        try:
            char_list_v = [c['id'] for c in st.session_state.asset_manager.search(asset_type="character")]
        except Exception:
            pass
        v_char = st.selectbox("Character", char_list_v or ["(no characters)"], key="v_char")
        v_text = st.text_area("Text", placeholder="Hey, just thinking of you ❤️")
        v_emotion = st.selectbox("Emotion", ["happy", "flirty", "sad", "excited", "neutral", "romantic"])
        if st.button("🎤 Generate Voice Message"):
            with st.spinner("Generating TTS..."):
                try:
                    from content.simulation.database.db import Database
                    from content.simulation.character_system.character import Character
                    from content.simulation.services.voice_message import VoiceMessageGenerator
                    db  = Database()
                    vmg = VoiceMessageGenerator(db=db)
                    char = Character.load(v_char, db=db)
                    if char:
                        result = vmg.generate_voice_message(
                            character_id=char.id,
                            character_name=char.name,
                            text=v_text,
                            emotion=v_emotion,
                        )
                        if result:
                            st.success(f"Audio file: {result['filename']}")
                            st.audio(result['filepath'])
                        else:
                            st.warning("TTS not available or returned nothing.")
                    else:
                        st.error(f"Character {v_char} not found.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Story ---
    with tab_story:
        st.subheader("Generate Story / Scenario via LLM")
        story_prompt = st.text_area("Prompt / Scenario brief", placeholder="Write a romantic evening scene where Emma and the user meet at a cafe...")
        story_len = st.slider("Target length (tokens)", 100, 2000, 500, 50)
        story_temp = st.slider("Temperature (creativity)", 0.1, 2.0, 0.85, 0.05)
        if st.button("📖 Generate Story"):
            with st.spinner("Generating via LLM..."):
                try:
                    from content.simulation.services.llm_service import get_llm_service
                    llm = get_llm_service()
                    result = llm.chat(
                        messages=[{"role": "user", "content": story_prompt}],
                        system_prompt="You are a creative fiction writer. Write vivid, immersive scenes. Adult content is allowed when requested.",
                        temperature=story_temp,
                        max_tokens=story_len,
                    )
                    st.markdown("---")
                    st.markdown(result)
                except Exception as e:
                    st.error(f"Error: {e}")


def show_log_viewer():
    """View system logs"""
    st.header("📜 Log Viewer")
    
    col1, col2 = st.columns(2)
    with col1:
        log_level = st.selectbox("Level", ["ALL", "INFO", "WARNING", "ERROR"])
    with col2:
        max_lines = st.number_input("Max Lines", 10, 1000, 100)
    
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    
    if not log_dir.exists():
        st.info("No logs directory found")
        return
    
    log_files = list(log_dir.glob("*.log"))
    if not log_files:
        st.info("No log files")
        return
    
    selected_log = st.selectbox("Log File", [f.name for f in sorted(log_files, reverse=True)])
    
    if selected_log:
        try:
            with open(log_dir / selected_log, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            filtered = [l for l in lines[-max_lines:] if log_level == "ALL" or log_level in l]
            st.code("".join(filtered), language="log")
        except Exception as e:
            st.error(f"Error: {e}")


def show_event_chains():
    """
    EventChain diagnostics viewer.

    Shows recent event chains from the ``events`` table so developers can
    trace every LLM request, tool call, and autonomous trigger in one place.
    """
    st.header("\U0001f517 Event Chains")
    st.markdown(
        "Browse causal event trees logged by ``CharacterAgent``, ``AutonomousMessenger``, "
        "and other services.  Each *chain* groups all events for a single turn or "
        "autonomous cycle."
    )

    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent.parent
        sys.path.insert(0, str(project_root))
        from content.simulation.database.db import Database
        from content.simulation.database.events import EventChain

        db = Database()
        ec = EventChain(db)

        col1, col2 = st.columns(2)
        with col1:
            scene_filter = st.text_input("Scene filter (leave blank for all)", "")
        with col2:
            limit = st.number_input("Max chains", 5, 200, 20)

        chains = ec.get_recent_chains(scene_id=scene_filter or None, limit=int(limit))

        if not chains:
            st.info("No event chains recorded yet.  Start the phone scene and send a message.")
            return

        st.markdown(f"**{len(chains)} chain(s) found**")
        st.markdown("---")

        for chain in chains:
            chain_id   = chain.get("chain_id", "?")
            scene_id   = chain.get("scene_id", "?")
            summary    = chain.get("summary", "")
            char_id    = chain.get("character_id", "")
            timestamp  = chain.get("timestamp", "")
            evt_count  = chain.get("event_count", "?")

            with st.expander(
                f"\U0001f517 {summary or chain_id[:12]}\u2026  |  scene={scene_id}  |  "
                f"{evt_count} events  |  {timestamp[:19]}",
                expanded=False,
            ):
                events = ec.get_chain_events(chain_id)
                if not events:
                    st.info("No events")
                    continue

                for ev in events:
                    ev_type  = ev.get("event_type", "?")
                    actor    = ev.get("actor", "?")
                    ev_sum   = ev.get("summary", "")
                    payload  = ev.get("payload", {})
                    ts       = ev.get("timestamp", "")[:19]
                    parent   = ev.get("parent_id")

                    indent = "\u00a0\u00a0\u00a0\u00a0" if parent else ""
                    icon_map = {
                        "llm_request":  "\U0001f4e4",
                        "llm_response": "\U0001f916",
                        "llm_cancelled": "\u274c",
                        "tool_call":    "\U0001f527",
                        "tool_result":  "\u2705",
                        "rag_result":   "\U0001f9e0",
                        "message_in":   "\U0001f4ac",
                        "message_out":  "\U0001f4f1",
                        "autonomous_trigger": "\u23f0",
                        "error":        "\u26a0\ufe0f",
                    }
                    icon = icon_map.get(ev_type, "\u25b6\ufe0f")
                    st.markdown(
                        f"{indent}{icon} **{ev_type}** _(actor={actor})_  &nbsp; {ts}  \n"
                        f"{indent}\u00a0\u00a0 {ev_sum}",
                        unsafe_allow_html=True,
                    )
                    if payload and st.checkbox(f"Show payload ({ev_type})", key=ev.get("id", ev_type)):
                        st.json(payload)

    except ImportError as e:
        st.error(f"Could not load EventChain module: {e}")
    except Exception as e:
        st.error(f"Error loading event chains: {e}")


def show_lmstudio():
    """
    LM Studio model management panel.

    Shows server status, currently loaded models, and allows browsing the
    available model catalogue on disk.  Uses ``engine.lmstudio.LMStudioManager``.
    """
    st.header("\U0001f916 LM Studio")
    st.markdown(
        "Monitor and manage your local LM Studio instance.  Uses the LMStudio "
        "Python SDK and CLI.  Make sure **LM Studio server** is running on the "
        "configured host/port before using this panel."
    )

    try:
        from engine.lmstudio import get_lmstudio_manager
        mgr = get_lmstudio_manager()

        # ── Status row ──
        col1, col2, col3 = st.columns(3)
        running = mgr.is_server_running()
        with col1:
            st.metric("Server", "\U0001f7e2 Online" if running else "\U0001f534 Offline")
        with col2:
            st.metric("Host", mgr.host)
        with col3:
            st.metric("Port", str(mgr.port))

        if not running:
            st.warning(
                "LM Studio server not reachable.  Start it with:\n"
                "```\nlms server start\n```"
            )
            return

        st.markdown("---")

        # ── Loaded models ──
        st.subheader("Loaded Models")
        loaded = mgr.list_loaded_models()
        if not loaded:
            st.info("No models currently loaded.  Load one from the catalogue below.")
        else:
            for m in loaded:
                with st.expander(f"\U0001f4e6 {m.get('path', m.get('id', 'unknown'))}", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**Status:** `{m.get('status', '?')}`")
                    with col_b:
                        if st.button(f"Unload", key=f"unload_{m.get('id', m.get('path','?'))}"):
                            try:
                                mgr.unload_model()
                                st.success("Model unloaded.  Refresh to update.")
                            except Exception as ue:
                                st.error(str(ue))

        st.markdown("---")

        # ── Available models ──
        st.subheader("Available Models (on disk)")
        if st.button("\U0001f504 Refresh model list"):
            st.session_state.pop("lms_available", None)

        if "lms_available" not in st.session_state:
            with st.spinner("Scanning models\u2026"):
                st.session_state["lms_available"] = mgr.get_available_models()

        available = st.session_state.get("lms_available", [])
        if not available:
            st.info("No models found in LM Studio library.  Add models via the LM Studio app.")
        else:
            search = st.text_input("\U0001f50d Filter models", "")
            shown = [m for m in available if search.lower() in str(m).lower()] if search else available

            st.markdown(f"**{len(shown)} model(s)**")
            for m in shown[:100]:
                key = m if isinstance(m, str) else m.get("path", str(m))
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"\u2022 `{key}`")
                with col_b:
                    if st.button("Load", key=f"load_{hash(key)}"):
                        try:
                            mgr.load_model(key)
                            st.success(f"Load requested for `{key}`")
                        except Exception as le:
                            st.error(str(le))

        st.markdown("---")

        # ── VRAM estimate ──
        st.subheader("VRAM Budget")
        st.markdown(
            f"**Cap:** {mgr.vram_cap_mb:,} MB  \u00a0|\u00a0 "
            f"**Default GPU fraction:** {mgr.default_gpu * 100:.0f}%"
        )

    except ImportError as e:
        st.error(f"LM Studio engine module not found: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")


def show_performance_monitor():
    """Performance monitoring"""
    st.header("📈 Performance Monitor")
    
    try:
        import psutil, platform, time
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("CPU", f"{psutil.cpu_percent(1)}%")
        with col2:
            st.metric("Memory", f"{psutil.virtual_memory().percent}%")
        with col3:
            st.metric("Disk", f"{psutil.disk_usage('C:\\' if __import__('sys').platform == 'win32' else '/').percent}%")
        with col4:
            st.metric("Python", platform.python_version())
        
        st.markdown("---")
        st.subheader("Database Performance")
        
        start = time.time()
        stats = st.session_state.asset_manager.get_stats()
        query_time = (time.time() - start) * 1000
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Query Time", f"{query_time:.2f}ms")
        with col2:
            st.metric("Total Assets", stats['total_assets'])
        
    except ImportError:
        st.warning("Install psutil: pip install psutil")


def show_backup_restore():
    """Backup and restore"""
    st.header("💾 Backup & Restore")
    
    tab1, tab2 = st.tabs(["📤 Backup", "📥 Restore"])
    
    with tab1:
        backup_name = st.text_input("Name", f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        include_media = st.checkbox("Include media")
        
        if st.button("Create Backup"):
            try:
                import shutil
                backup_dir = Path(__file__).parent.parent.parent.parent / "backups"
                backup_dir.mkdir(exist_ok=True)
                backup_path = backup_dir / backup_name
                backup_path.mkdir(exist_ok=True)
                
                # Backup database
                db_path = st.session_state.asset_manager.db_path
                if Path(db_path).exists():
                    shutil.copy2(db_path, backup_path / "assets.db")
                
                st.success(f"✅ Backup created: {backup_name}")
            except Exception as e:
                st.error(f"Failed: {e}")
    
    with tab2:
        backup_dir = Path(__file__).parent.parent.parent.parent / "backups"
        if backup_dir.exists():
            backups = [d.name for d in backup_dir.iterdir() if d.is_dir()]
            if backups:
                selected = st.selectbox("Select Backup", backups)
                st.warning("⚠️ This will overwrite current data!")
                if st.checkbox("Confirm") and st.button("Restore"):
                    try:
                        import shutil
                        backup_path = backup_dir / selected
                        db_backup = backup_path / "assets.db"
                        if db_backup.exists():
                            shutil.copy2(db_backup, st.session_state.asset_manager.db_path)
                        st.success("✅ Restored!")
                    except Exception as e:
                        st.error(f"Failed: {e}")
            else:
                st.info("No backups")
        else:
            st.info("No backup directory")


def show_mcp_monitor():
    """
    🎮 MCP Monitor — live view and control of the MCP framework state.

    Sections
    --------
    1. MCPFramework Status     — scenes, characters, turn counter, pending consequences
    2. Active Game Sessions    — per-session history viewer and action panel
    3. GameState Editor        — raw key-value inspection + inline edit
    4. AgentRouter Inbox       — pending messages per agent
    5. Channel Actions         — send router message, fire consequence, cross-scene send
    6. Character Registry      — all known characters with state/skills
    """
    st.header("🎮 MCP Monitor")
    st.markdown("Live view and control of the MCP framework state machine.")

    tabs = st.tabs([
        "📡 Framework",
        "🎲 Game Sessions",
        "🗂️ GameState Editor",
        "📬 Agent Router",
        "⚡ Channel Actions",
        "🧑 Character Registry",
        "📡 Streaming",
    ])

    # ── Tab 1: MCPFramework Status ────────────────────────────────────
    with tabs[0]:
        st.subheader("MCPFramework Status")

        try:
            from engine.mcp.framework import get_framework
            fw     = get_framework()
            status = fw.get_status()

            col1, col2, col3 = st.columns(3)
            col1.metric("Turn",       status.get("turn", 0))
            col2.metric("Scenes",     len(status.get("scenes", {})))
            col3.metric("Characters", len(status.get("characters", {})))

            st.divider()
            left, right = st.columns(2)

            with left:
                st.markdown("**Registered Scenes**")
                scene_map = status.get("scenes", {})
                if scene_map:
                    for sid, sdata in scene_map.items():
                        with st.expander(f"🏠 {sid}"):
                            st.json(sdata)
                else:
                    st.info("No scenes registered yet.")

            with right:
                st.markdown("**Registered Characters**")
                char_map = status.get("characters", {})
                if char_map:
                    for cid, cdata in char_map.items():
                        with st.expander(f"👤 {cid}"):
                            st.json(cdata)
                else:
                    st.info("No characters registered yet.")

            st.divider()
            st.markdown("**Pending Consequences**")
            consequences = status.get("consequences", [])
            if consequences:
                import pandas as pd
                st.dataframe(pd.DataFrame(consequences), use_container_width=True)
            else:
                st.info("No pending consequences.")

        except Exception as exc:
            st.warning(f"MCPFramework unavailable: {exc}")

    # ── Tab 2: Game Sessions ──────────────────────────────────────────
    with tabs[1]:
        st.subheader("Active Game Sessions")

        try:
            from engine.mcp.game_mcp import active_sessions, all_sessions, get_session

            active = active_sessions()
            if active:
                for sess in active:
                    gid = sess.get("game_id", "?")
                    with st.expander(
                        f"🎲 {sess.get('type', '?').replace('_', ' ').title()} "
                        f"— {gid}  |  Turn {sess.get('turn', 0)}  |  Score {sess.get('score', 0)}",
                        expanded=True,
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Character:** `{sess.get('character_id')}`")
                            st.markdown(f"**Scene:** `{sess.get('scene_id')}`")
                            st.markdown(f"**Won:** {sess.get('won')}")
                        with col2:
                            st.markdown("**Recent History**")
                            recent = sess.get("recent_history", "No history yet.")
                            st.code(recent, language=None)

                        # Full turn history
                        _s = get_session(gid)
                        if _s:
                            full_hist = _s.get_history(50)
                            if full_hist:
                                st.markdown("**Full Turn Log**")
                                import pandas as pd
                                df = pd.DataFrame(full_hist)
                                cols_to_show = ["turn", "event_type", "actor", "description"]
                                st.dataframe(
                                    df[[c for c in cols_to_show if c in df.columns]],
                                    use_container_width=True,
                                )
            else:
                st.info("No active game sessions.")

            st.divider()
            st.markdown("**All Sessions (including ended)**")
            all_s = all_sessions()
            if all_s:
                import pandas as pd
                df = pd.DataFrame([
                    {
                        "game_id": s.get("game_id"),
                        "type":    s.get("type"),
                        "char":    s.get("character_id"),
                        "scene":   s.get("scene_id"),
                        "active":  s.get("active"),
                        "turn":    s.get("turn"),
                        "score":   s.get("score"),
                        "won":     s.get("won"),
                    }
                    for s in all_s
                ])
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No sessions recorded this run.")
        except Exception as exc:
            st.warning(f"Game session registry unavailable: {exc}")

    # ── Tab 3: GameState Editor ───────────────────────────────────────
    with tabs[2]:
        st.subheader("GameState Key-Value Editor")

        try:
            from engine.mcp.comms_framework import get_game_state
            gs = get_game_state()
            games = gs.all_games()

            if not games:
                st.info("No game states stored.")
            else:
                selected_game = st.selectbox(
                    "Select game ID to inspect",
                    list(games.keys()),
                )
                state_data = gs.get_all(selected_game)

                st.markdown(f"**State for `{selected_game}`**")
                st.json(state_data)

                st.divider()
                st.markdown("**Edit a key**")
                edit_col1, edit_col2, edit_col3 = st.columns([2, 3, 1])
                with edit_col1:
                    edit_key = st.text_input("Key", key="gs_edit_key")
                with edit_col2:
                    edit_val = st.text_input("New value (JSON or string)", key="gs_edit_val")
                with edit_col3:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("💾 Set", key="gs_set_btn"):
                        if edit_key:
                            import json as _json
                            try:
                                parsed_val = _json.loads(edit_val)
                            except Exception:
                                parsed_val = edit_val
                            gs.set(selected_game, edit_key, parsed_val)
                            st.success(f"Set {selected_game}.{edit_key} = {parsed_val!r}")
                            st.rerun()
        except Exception as exc:
            st.warning(f"GameState unavailable: {exc}")

    # ── Tab 4: Agent Router Inbox ─────────────────────────────────────
    with tabs[3]:
        st.subheader("AgentRouter Inbox Viewer")

        try:
            from engine.mcp.comms_framework import get_router
            router = get_router()

            agent_id_to_inspect = st.text_input(
                "Agent ID to inspect",
                placeholder="e.g. char:001",
                key="router_agent_id",
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("📥 Peek", key="router_peek"):
                    if agent_id_to_inspect:
                        msgs = router.peek(agent_id_to_inspect)
                        if msgs:
                            for i, m in enumerate(msgs, 1):
                                st.markdown(
                                    f"**{i}.** _{m.get('sender_id', 'unknown')}_ → "
                                    f"`{m.get('message', '')[:120]}`"
                                )
                        else:
                            st.info("No pending messages.")
                    else:
                        st.warning("Enter an agent ID.")
            with col2:
                if st.button("🗑️ Drain (read + clear)", key="router_drain"):
                    if agent_id_to_inspect:
                        msgs = router.drain(agent_id_to_inspect)
                        st.success(f"Drained {len(msgs)} messages.")
                    else:
                        st.warning("Enter an agent ID.")
        except Exception as exc:
            st.warning(f"AgentRouter unavailable: {exc}")

    # ── Tab 5: Channel Actions ────────────────────────────────────────
    with tabs[4]:
        st.subheader("Channel Action Panel")

        st.markdown("### 📤 Send Router Message")
        with st.form("send_router_msg"):
            r_to      = st.text_input("Recipient agent ID",  placeholder="char:001")
            r_from    = st.text_input("Sender ID (optional)", placeholder="admin")
            r_message = st.text_area("Message", placeholder="You've received a game invite…")
            if st.form_submit_button("Send"):
                try:
                    from engine.mcp.comms_framework import get_router
                    get_router().send(r_to, r_message, sender_id=r_from or "admin")
                    st.success(f"Message sent to {r_to}.")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

        st.divider()
        st.markdown("### ⚡ Schedule Consequence")
        with st.form("schedule_consequence"):
            c_scene  = st.text_input("Scene ID",      placeholder="bedroom")
            c_char   = st.text_input("Character ID",  placeholder="char:001")
            c_type   = st.text_input("Type",          placeholder="stat_adjust")
            c_params = st.text_input("Params JSON",   placeholder='{"stat": "happiness", "delta": 10}')
            c_turns  = st.number_input("After turns", value=1, min_value=0, max_value=100)
            c_desc   = st.text_input("Description",   placeholder="post-game mood lift")
            if st.form_submit_button("Schedule"):
                try:
                    import json as _json
                    from engine.mcp.framework import get_framework
                    params = _json.loads(c_params) if c_params else {}
                    get_framework().schedule_consequence(
                        scene_id=c_scene,
                        character_id=c_char,
                        consequence_type=c_type,
                        params=params,
                        trigger_after_turns=int(c_turns),
                        description=c_desc,
                    )
                    st.success("Consequence scheduled.")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

        st.divider()
        st.markdown("### 🌐 Cross-Scene Message")
        with st.form("cross_scene_msg"):
            cs_from   = st.text_input("From scene",   placeholder="bedroom")
            cs_to     = st.text_input("To scene",     placeholder="phone")
            cs_type   = st.text_input("Message type", placeholder="game_invite")
            cs_payload = st.text_input("Payload JSON", placeholder='{"game": "mystery"}')
            if st.form_submit_button("Send"):
                try:
                    import json as _json
                    from engine.mcp.framework import get_framework
                    payload = _json.loads(cs_payload) if cs_payload else {}
                    get_framework().cross_scene_send(cs_from, cs_to, cs_type, payload)
                    st.success(f"Cross-scene message sent {cs_from} → {cs_to}.")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

        st.divider()
        st.markdown("### 🚀 Launch Game (quick)")
        with st.form("quick_launch_game"):
            ql_char = st.text_input("Character ID",  placeholder="char:001")
            ql_type = st.selectbox("Game type", ["truth_or_dare", "mystery"])
            ql_case = st.number_input("Case index (mystery, -1 = random)", value=-1, min_value=-1)
            if st.form_submit_button("Launch"):
                try:
                    from content.scenes.bedroom.bedroom_game_skill import launch_game
                    result = launch_game(ql_char, ql_type, int(ql_case))
                    st.success("Game launched!")
                    import json as _json
                    st.json(_json.loads(result))
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    # ── Tab 6: Character Registry ─────────────────────────────────────
    with tabs[5]:
        st.subheader("Character Registry")

        try:
            from engine.mcp.character_registry import get_character_registry
            reg = get_character_registry()

            # Try to get all records from the registry
            records = {}
            try:
                records = getattr(reg, "_records", {})
            except Exception:
                pass

            if not records:
                st.info("No characters registered in the character registry yet.")
            else:
                st.markdown(f"**{len(records)} character(s) registered**")
                for cid, record in records.items():
                    with st.expander(f"👤 {cid}"):
                        # State
                        try:
                            state = reg.get_state(cid)
                            st.markdown("**State**")
                            st.json(state or {})
                        except Exception:
                            pass

                        # Skills
                        try:
                            skills = getattr(record, "skills", None) or getattr(record, "skill_ids", [])
                            if skills:
                                st.markdown(f"**Skills:** {', '.join(str(s) for s in skills)}")
                        except Exception:
                            pass

                        # Current scene
                        try:
                            scene = getattr(record, "current_scene", None)
                            if scene:
                                st.markdown(f"**Current scene:** `{scene}`")
                        except Exception:
                            pass
        except Exception as exc:
            st.warning(f"Character registry unavailable: {exc}")

    # ── Tab 7: Streaming Stats ────────────────────────────────────────
    with tabs[6]:
        st.subheader("v2.7 Streaming & Conversations")

        try:
            from engine.agents.virtual_agent_manager import get_virtual_agent_manager
            mgr = get_virtual_agent_manager()
            col1, col2 = st.columns(2)
            col1.metric("Active Agents", len(getattr(mgr, "_agents", {})))
            col2.metric("Total Calls", getattr(mgr, "_total_calls", 0))
        except Exception as exc:
            st.caption(f"VirtualAgentManager: {exc}")

        st.divider()
        st.markdown("**Active Conversations**")
        try:
            from engine.lmstudio.conversation import ConversationManager
            cm = ConversationManager.instance()
            convos = cm.list_conversations() if hasattr(cm, "list_conversations") else []
            if convos:
                for c in convos[:20]:
                    turns = len(c._history)
                    branches = len(getattr(c, "_response_id_history", []))
                    with st.expander(f"💬 {c.conversation_id} — {turns} turns, {branches} branch points"):
                        st.json({
                            "conversation_id": c.conversation_id,
                            "turns": turns,
                            "branches": branches,
                            "last_response_id": getattr(c, "_last_response_id", None),
                        })
            else:
                st.info("No active conversations.")
        except Exception as exc:
            st.caption(f"ConversationManager: {exc}")

        st.divider()
        st.markdown("**StreamProcessor**")
        try:
            from engine.agents.stream_processor import StreamProcessor
            st.success("StreamProcessor available")
            if hasattr(StreamProcessor, "DEFAULT_TAG_PATTERNS"):
                st.caption(f"Tag patterns: {', '.join(StreamProcessor.DEFAULT_TAG_PATTERNS.keys())}")
        except Exception:
            st.warning("StreamProcessor not available")


if __name__ == "__main__":
    main()
