"""
Enhanced Dashboard v2 for Virtual Companion System
Streamlit-based UI for character management and system control
"""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from simulation.database.db import Database
from simulation.database.rag import RAGMemory
from simulation.character_system.character import Character
from simulation.character_system.personality import Personality
from simulation.character_system.role import Role


# Page config
st.set_page_config(
    page_title="Virtual Companion Dashboard",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    .main .block-container {
        padding: 2rem;
        background: white;
        border-radius: 15px;
        margin: 1rem;
    }
    h1 {
        color: #667eea;
    }
    .character-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


# Initialize session state
if 'db' not in st.session_state:
    st.session_state.db = Database()

if 'rag' not in st.session_state:
    st.session_state.rag = RAGMemory()

if 'personality_mgr' not in st.session_state:
    st.session_state.personality_mgr = Personality(st.session_state.db)

if 'role_mgr' not in st.session_state:
    st.session_state.role_mgr = Role(st.session_state.db)

if 'selected_character' not in st.session_state:
    st.session_state.selected_character = None


# Sidebar navigation
st.sidebar.title("🎮 Virtual Companion")
page = st.sidebar.radio(
    "Navigation",
    ["📊 Dashboard", "👤 Characters", "🎭 Personalities", "🎬 Roles", "💾 Memories", "🚀 Deploy", "⚙️ Settings"]
)


# ============= DASHBOARD PAGE =============
if page == "📊 Dashboard":
    st.title("📊 Dashboard")
    
    # Stats
    col1, col2, col3, col4 = st.columns(4)
    
    characters = st.session_state.db.get_all_characters()
    personalities = st.session_state.personality_mgr.list_all()
    roles = st.session_state.role_mgr.list_all()
    
    with col1:
        st.metric("Characters", len(characters))
    with col2:
        st.metric("Personalities", len(personalities))
    with col3:
        st.metric("Roles", len(roles))
    with col4:
        total_memories = st.session_state.rag.get_memory_count()
        st.metric("Total Memories", total_memories)
    
    # Recent characters
    st.subheader("Recent Characters")
    
    if characters:
        for char_data in characters[:5]:
            with st.expander(f"👤 {char_data['name']}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Age:** {char_data.get('age', 'N/A')}")
                    st.write(f"**Sex:** {char_data.get('sex', 'N/A')}")
                    st.write(f"**Created:** {char_data.get('created_at', 'N/A')[:10]}")
                
                with col2:
                    tags = char_data.get('tags', [])
                    if tags:
                        st.write(f"**Tags:** {', '.join(tags)}")
                    
                    # Get character state
                    state = st.session_state.db.get_character_state(char_data['id'])
                    if state:
                        st.write(f"**Mood:** {state.get('mood', 'neutral')}")
                        st.progress(state.get('relationship_level', 0.0))
                        st.caption(f"Relationship: {state.get('relationship_level', 0.0):.0%}")
    else:
        st.info("No characters yet. Create one in the Characters tab!")


# ============= CHARACTERS PAGE =============
elif page == "👤 Characters":
    st.title("👤 Character Management")
    
    tab1, tab2, tab3 = st.tabs(["Create Character", "View Characters", "Edit Character"])
    
    # CREATE CHARACTER TAB
    with tab1:
        st.subheader("Create New Character")
        
        with st.form("create_character"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Name *", placeholder="Emma")
                age = st.number_input("Age", min_value=18, max_value=99, value=25)
                sex = st.selectbox("Sex", ["female", "male", "other"])
                hair_color = st.text_input("Hair Color", placeholder="blonde")
                eye_color = st.text_input("Eye Color", placeholder="blue")
            
            with col2:
                height = st.text_input("Height", placeholder="5'6\"")
                body_type = st.text_input("Body Type", placeholder="athletic")
                
                # Personality selection
                personalities = st.session_state.personality_mgr.list_all()
                personality_options = {p['name']: p['id'] for p in personalities}
                
                if personalities:
                    personality_name = st.selectbox("Personality", list(personality_options.keys()))
                    personality_id = personality_options[personality_name]
                else:
                    st.warning("No personalities available. Initialize defaults first.")
                    personality_id = None
            
            # Tags
            st.subheader("Tags")
            tags_input = st.text_input("Tags (comma-separated)", placeholder="girlfriend, playful, romantic")
            
            # Metadata
            with st.expander("Advanced Options"):
                backstory = st.text_area("Backstory", placeholder="Optional backstory...")
                voice_preference = st.text_input("Voice Preference", placeholder="female_voice_1")
            
            submitted = st.form_submit_button("Create Character", type="primary")
            
            if submitted:
                if not name:
                    st.error("Name is required!")
                elif not personality_id:
                    st.error("Personality is required!")
                else:
                    # Parse tags
                    tags = [t.strip() for t in tags_input.split(',') if t.strip()]
                    
                    # Create metadata
                    metadata = {}
                    if backstory:
                        metadata['backstory'] = backstory
                    if voice_preference:
                        metadata['voice_preference'] = voice_preference
                    
                    # Create character
                    try:
                        char = Character.create(
                            name=name,
                            personality_id=personality_id,
                            age=age,
                            sex=sex,
                            hair_color=hair_color,
                            eye_color=eye_color,
                            height=height,
                            body_type=body_type,
                            tags=tags,
                            metadata=metadata,
                            db=st.session_state.db
                        )
                        
                        st.success(f"✅ Created character: {name}")
                        st.balloons()
                        
                    except Exception as e:
                        st.error(f"Error creating character: {e}")
    
    # VIEW CHARACTERS TAB
    with tab2:
        st.subheader("All Characters")
        
        characters = st.session_state.db.get_all_characters()
        
        if characters:
            for char_data in characters:
                with st.container():
                    col1, col2, col3 = st.columns([3, 2, 1])
                    
                    with col1:
                        st.markdown(f"### {char_data['name']}")
                        
                        # Basic info
                        info_parts = []
                        if char_data.get('age'):
                            info_parts.append(f"{char_data['age']} years old")
                        if char_data.get('sex'):
                            info_parts.append(char_data['sex'])
                        if info_parts:
                            st.caption(" • ".join(info_parts))
                        
                        # Physical description
                        phys = []
                        if char_data.get('hair_color'):
                            phys.append(f"{char_data['hair_color']} hair")
                        if char_data.get('eye_color'):
                            phys.append(f"{char_data['eye_color']} eyes")
                        if char_data.get('height'):
                            phys.append(char_data['height'])
                        if phys:
                            st.write(" • ".join(phys))
                        
                        # Tags
                        if char_data.get('tags'):
                            st.write("🏷️ " + ", ".join(char_data['tags']))
                    
                    with col2:
                        # State
                        state = st.session_state.db.get_character_state(char_data['id'])
                        if state:
                            st.write(f"**Mood:** {state.get('mood', 'neutral')}")
                            st.progress(state.get('relationship_level', 0.0))
                            st.caption(f"Relationship: {state.get('relationship_level', 0.0):.0%}")
                        
                        # Memory count
                        mem_count = st.session_state.rag.get_memory_count(char_data['id'])
                        st.caption(f"💾 {mem_count} memories")
                    
                    with col3:
                        if st.button("Select", key=f"select_{char_data['id']}"):
                            st.session_state.selected_character = char_data['id']
                            st.success(f"Selected {char_data['name']}")
                        
                        if st.button("Delete", key=f"delete_{char_data['id']}", type="secondary"):
                            if st.session_state.db.delete_character(char_data['id']):
                                st.success(f"Deleted {char_data['name']}")
                                st.rerun()
                    
                    st.divider()
        else:
            st.info("No characters yet. Create one in the 'Create Character' tab!")
    
    # EDIT CHARACTER TAB
    with tab3:
        st.subheader("Edit Character")
        
        characters = st.session_state.db.get_all_characters()
        
        if characters:
            char_options = {c['name']: c['id'] for c in characters}
            selected_name = st.selectbox("Select Character", list(char_options.keys()))
            selected_id = char_options[selected_name]
            
            char_data = st.session_state.db.get_character(selected_id)
            
            if char_data:
                with st.form("edit_character"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        new_age = st.number_input("Age", value=char_data.get('age', 25))
                        new_mood = st.selectbox(
                            "Mood", 
                            ["neutral", "happy", "sad", "playful", "romantic", "horny", "angry"],
                            index=0
                        )
                    
                    with col2:
                        state = st.session_state.db.get_character_state(selected_id)
                        current_rel = state.get('relationship_level', 0.0) if state else 0.0
                        new_relationship = st.slider("Relationship Level", 0.0, 1.0, current_rel)
                        
                        current_arousal = state.get('arousal', 0.0) if state else 0.0
                        new_arousal = st.slider("Arousal Level", 0.0, 1.0, current_arousal)
                    
                    # Tags
                    current_tags = ", ".join(char_data.get('tags', []))
                    new_tags_input = st.text_input("Tags", value=current_tags)
                    
                    if st.form_submit_button("Update Character"):
                        # Update basic attributes
                        st.session_state.db.update_character(selected_id, age=new_age)
                        
                        # Update state
                        st.session_state.db.update_character_state(
                            selected_id,
                            mood=new_mood,
                            relationship_level=new_relationship,
                            arousal=new_arousal
                        )
                        
                        # Update tags
                        new_tags = [t.strip() for t in new_tags_input.split(',') if t.strip()]
                        st.session_state.db.update_character(selected_id, tags=new_tags)
                        
                        st.success("✅ Character updated!")
                        st.rerun()
        else:
            st.info("No characters available to edit.")


# ============= PERSONALITIES PAGE =============
elif page == "🎭 Personalities":
    st.title("🎭 Personality Management")
    
    tab1, tab2 = st.tabs(["View Personalities", "Create Custom"])
    
    with tab1:
        st.subheader("Available Personalities")
        
        # Initialize defaults button
        if st.button("Initialize Default Personalities", type="primary"):
            created = st.session_state.personality_mgr.initialize_defaults()
            st.success(f"✅ Initialized {len(created)} personality templates")
            st.rerun()
        
        personalities = st.session_state.personality_mgr.list_all()
        
        for pers in personalities:
            with st.expander(f"🎭 {pers['name']}"):
                st.write(f"**Traits:** {', '.join(pers.get('traits', []))}")
                st.write(f"**Sexual Openness:** {pers.get('sexual_openness', 0.5):.1%}")
                
                with st.container():
                    st.write("**System Prompt:**")
                    st.code(pers['system_prompt'], language=None)
                
                if pers.get('communication_style'):
                    st.json(pers['communication_style'])
    
    with tab2:
        st.subheader("Create Custom Personality")
        
        with st.form("create_personality"):
            name = st.text_input("Name *", placeholder="My Custom Personality")
            system_prompt = st.text_area(
                "System Prompt *",
                placeholder="You are a...",
                height=150
            )
            
            traits_input = st.text_input("Traits (comma-separated)", placeholder="caring, funny, smart")
            
            col1, col2 = st.columns(2)
            with col1:
                sexual_openness = st.slider("Sexual Openness", 0.0, 1.0, 0.5)
            with col2:
                values_input = st.text_input("Values (comma-separated)", placeholder="honesty, loyalty")
            
            if st.form_submit_button("Create Personality"):
                if not name or not system_prompt:
                    st.error("Name and System Prompt are required!")
                else:
                    traits = [t.strip() for t in traits_input.split(',') if t.strip()]
                    values = [v.strip() for v in values_input.split(',') if v.strip()]
                    
                    try:
                        pers_id = st.session_state.personality_mgr.create_custom(
                            name=name,
                            system_prompt=system_prompt,
                            traits=traits,
                            sexual_openness=sexual_openness,
                            values=values
                        )
                        st.success(f"✅ Created personality: {name}")
                    except Exception as e:
                        st.error(f"Error: {e}")


# ============= ROLES PAGE =============
elif page == "🎬 Roles":
    st.title("🎬 Role Management")
    
    tab1, tab2 = st.tabs(["View Roles", "Create Custom"])
    
    with tab1:
        st.subheader("Available Roles")
        
        # Initialize defaults button
        if st.button("Initialize Default Roles", type="primary"):
            created = st.session_state.role_mgr.initialize_defaults()
            st.success(f"✅ Initialized {len(created)} role templates")
            st.rerun()
        
        roles = st.session_state.role_mgr.list_all()
        
        for role in roles:
            with st.expander(f"🎬 {role['name']}"):
                st.write(f"**Description:** {role['description']}")
                st.write(f"**Required Traits:** {', '.join(role.get('required_traits', []))}")
                
                if role.get('context'):
                    st.write("**Context:**")
                    st.info(role['context'])
                
                if role.get('scenario'):
                    st.write("**Scenario:**")
                    st.info(role['scenario'])
    
    with tab2:
        st.subheader("Create Custom Role")
        
        with st.form("create_role"):
            name = st.text_input("Name *", placeholder="Custom Role")
            description = st.text_area("Description *", placeholder="Role description...")
            
            required_traits = st.text_input("Required Traits", placeholder="trait1, trait2")
            context = st.text_area("Context", placeholder="Context for this role...")
            scenario = st.text_area("Scenario", placeholder="Scenario details...")
            
            if st.form_submit_button("Create Role"):
                if not name or not description:
                    st.error("Name and Description are required!")
                else:
                    traits = [t.strip() for t in required_traits.split(',') if t.strip()]
                    
                    try:
                        role_id = st.session_state.role_mgr.create_custom(
                            name=name,
                            description=description,
                            required_traits=traits,
                            context=context,
                            scenario=scenario
                        )
                        st.success(f"✅ Created role: {name}")
                    except Exception as e:
                        st.error(f"Error: {e}")


# ============= MEMORIES PAGE =============
elif page == "💾 Memories":
    st.title("💾 Memory Browser")
    
    characters = st.session_state.db.get_all_characters()
    
    if characters:
        char_options = {c['name']: c['id'] for c in characters}
        selected_name = st.selectbox("Select Character", list(char_options.keys()))
        selected_id = char_options[selected_name]
        
        # Memory stats
        mem_count = st.session_state.rag.get_memory_count(selected_id)
        st.metric("Total Memories", mem_count)
        
        # Memory tabs
        tab1, tab2, tab3 = st.tabs(["Recent", "Important", "Search"])
        
        with tab1:
            st.subheader("Recent Memories")
            recent = st.session_state.rag.get_recent_memories(selected_id, n_results=20)
            
            for mem in recent:
                with st.container():
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(mem['content'])
                    with col2:
                        importance = mem['metadata'].get('importance', 0.5)
                        st.progress(importance)
                        st.caption(f"{importance:.0%}")
                    
                    st.caption(f"🕐 {mem['metadata'].get('timestamp', 'N/A')}")
                    st.divider()
        
        with tab2:
            st.subheader("Important Memories")
            important = st.session_state.rag.get_important_memories(selected_id, n_results=10, min_importance=0.7)
            
            for mem in important:
                st.info(mem['content'])
                st.caption(f"Importance: {mem['metadata'].get('importance', 0):.0%} • {mem['metadata'].get('timestamp', 'N/A')}")
        
        with tab3:
            st.subheader("Search Memories")
            query = st.text_input("Search query", placeholder="What do you remember about...")
            
            if st.button("Search") and query:
                results = st.session_state.rag.query_memories(selected_id, query, n_results=10)
                
                for mem in results:
                    st.success(mem['content'])
                    relevance = 1.0 - (mem['distance'] or 0)
                    st.caption(f"Relevance: {relevance:.0%}")
                    st.divider()
    else:
        st.info("No characters available. Create one first!")


# ============= DEPLOY PAGE =============
elif page == "🚀 Deploy":
    st.title("🚀 Deploy & Run")
    
    st.subheader("Phone Scene")
    
    characters = st.session_state.db.get_all_characters()
    
    if characters:
        char_options = {c['name']: c['id'] for c in characters}
        selected_name = st.selectbox("Select Character for Phone Scene", list(char_options.keys()))
        selected_id = char_options[selected_name]
        
        col1, col2 = st.columns(2)
        
        with col1:
            port = st.number_input("Port", value=5555, min_value=1000, max_value=9999)
        
        with col2:
            if st.button("Launch Phone Scene", type="primary"):
                st.info(f"To launch the phone scene, run:\n\n```\npython simulation/scenes/phone/phone_scene.py\n```")
                st.code(f"""
from simulation.scenes.phone.phone_scene import create_phone_scene

scene = create_phone_scene(character_id="{selected_id}", port={port})
scene.run(debug=True)
                """, language="python")
    else:
        st.warning("No characters available. Create one first!")


# ============= SETTINGS PAGE =============
elif page == "⚙️ Settings":
    st.title("⚙️ Settings")
    
    st.subheader("Database")
    st.info(f"Database Path: simulation/simulation.db")
    st.info(f"ChromaDB Path: simulation/chroma_db")
    
    st.subheader("Danger Zone")
    
    with st.expander("⚠️ Reset Database"):
        st.warning("This will delete ALL data permanently!")
        
        if st.button("Reset All Data", type="secondary"):
            confirm = st.text_input("Type 'DELETE' to confirm")
            if confirm == "DELETE":
                st.error("Feature disabled for safety. Manually delete database files if needed.")


# Footer
st.sidebar.divider()
st.sidebar.caption("Virtual Companion System v1.0")
st.sidebar.caption("Built with ❤️")


if __name__ == "__main__":
    pass  # Streamlit handles execution
