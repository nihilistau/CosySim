"""Character Manager page — extracted from admin monolith."""
import streamlit as st
import json
from datetime import datetime
from engine.assets import AssetManager, CharacterAsset, PersonalityAsset


def render():
    st.header("👥 Character Manager")

    tab1, tab2 = st.tabs(["👥 Characters", "➕ Create New"])

    with tab1:
        _show_characters()
    with tab2:
        _create_character()


def _show_characters():
    """List and manage existing characters."""
    am = st.session_state.asset_manager

    characters = am.search(asset_type="character")
    if not characters:
        st.info("No characters yet. Create one in the 'Create New' tab.")
        return

    for char_data in characters:
        meta = char_data.get("metadata", {})
        name = meta.get("name", "Unnamed")
        with st.expander(f"👤 {name}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**ID:** `{char_data['id'][:12]}…`")
                st.markdown(f"**Age:** {meta.get('age', 'N/A')}")
                st.markdown(f"**Sex:** {meta.get('sex', 'N/A')}")
            with col2:
                st.markdown(f"**Hair:** {meta.get('hair_color', 'N/A')}")
                st.markdown(f"**Eyes:** {meta.get('eye_color', 'N/A')}")
                st.markdown(f"**Height:** {meta.get('height', 'N/A')}")

            tags = char_data.get("tags", [])
            if tags:
                st.markdown(f"**Tags:** {', '.join(tags)}")

            # Delete button
            if st.button(f"🗑️ Delete", key=f"del_char_{char_data['id']}"):
                try:
                    am.delete(char_data["id"])
                    st.success(f"Deleted {name}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


def _create_character():
    """Character creation form."""
    st.subheader("Create Character")

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Name", key="cc_name")
        age = st.number_input("Age", 18, 100, 24, key="cc_age")
        sex = st.selectbox("Sex", ["female", "male", "non-binary"], key="cc_sex")
    with col2:
        hair = st.text_input("Hair Color", key="cc_hair")
        eyes = st.text_input("Eye Color", key="cc_eyes")
        height = st.text_input("Height", key="cc_height")

    body_type = st.selectbox("Body Type", ["slim", "athletic", "curvy", "average", "muscular"], key="cc_body")
    tags = st.text_input("Tags (comma separated)", key="cc_tags")
    nsfw = st.checkbox("NSFW Enabled", key="cc_nsfw")

    if st.button("✅ Create Character", type="primary", key="cc_create"):
        if not name:
            st.error("Name is required")
            return

        try:
            char = CharacterAsset.create(
                name=name, age=age, sex=sex,
                hair_color=hair, eye_color=eyes,
                height=height, body_type=body_type,
                tags=[t.strip() for t in tags.split(",") if t.strip()],
                nsfw_enabled=nsfw,
            )
            asset_id = st.session_state.asset_manager.save(char)
            st.success(f"✅ Created character '{name}' (ID: {asset_id[:12]}…)")
        except Exception as e:
            st.error(f"Error: {e}")
