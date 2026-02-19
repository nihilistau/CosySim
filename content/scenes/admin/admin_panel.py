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
                "📈 Performance Monitor",
                "💾 Backup & Restore"
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
    if page == "📊 Dashboard":
        show_dashboard()
    elif page == "🗂️ Asset Browser":
        show_asset_browser()
    elif page == "👥 Character Manager":
        show_character_manager()
    elif page == "🎭 Scene Manager":
        show_scene_manager()
    elif page == "🧠 Personality Library":
        show_personality_library()
    elif page == "⚙️ Configuration":
        show_configuration()
    elif page == "💾 Database":
        show_database()
    elif page == "🔍 Search & Filter":
        show_search()
    elif page == "🖼️ Media Gallery":
        show_media_gallery()
    elif page == "🔗 Dependency Graph":
        show_dependency_graph()
    elif page == "🎨 Asset Generator":
        show_asset_generator()
    elif page == "📜 Log Viewer":
        show_log_viewer()
    elif page == "📈 Performance Monitor":
        show_performance_monitor()
    elif page == "💾 Backup & Restore":
        show_backup_restore()


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
                            _freq_opts = ["rare", "occasional", "frequent"]
                            _cur_freq = char.messaging_frequency if char.messaging_frequency in _freq_opts else "occasional"
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
                        st.success(f"✅ Created character: {name}")
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
                scene_type = st.selectbox("Scene Type", ["phone", "dashboard", "bedroom", "custom"])
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
    """System configuration"""
    st.header("⚙️ Configuration")
    
    config = st.session_state.config
    
    tab1, tab2, tab3 = st.tabs(["📋 View Config", "✏️ Edit Config", "🔄 Environment"])
    
    with tab1:
        # Display current configuration
        st.subheader("Current Configuration")
        st.json(dict(config._config))
    
    with tab2:
        st.subheader("Edit Configuration")
        st.info("Configuration editing coming soon. For now, edit config/*.yaml files directly.")
        
        st.markdown("**Config Files:**")
        st.code("""
config/default.yaml       - Base configuration
config/development.yaml   - Development overrides
config/production.yaml    - Production settings
        """)
    
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
            st.info("No COSYVOICE_* environment variables set")


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
    st.markdown("Generate media assets directly from the admin panel. Requires ComfyUI (192.168.8.150:8188) and LM Studio (localhost:1234) to be running.")

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
                        st.error("ComfyUI not reachable at 192.168.8.150:8188")
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
            st.metric("Disk", f"{psutil.disk_usage('/').percent}%")
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


if __name__ == "__main__":
    main()
