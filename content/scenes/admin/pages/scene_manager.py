"""Scene Manager page — scene CRUD and monitoring."""
import streamlit as st
from engine.assets import AssetManager, SceneAsset


def render():
    st.header("🎭 Scene Manager")

    tab1, tab2 = st.tabs(["🎭 Active Scenes", "➕ Create Scene"])

    with tab1:
        _show_scenes()
    with tab2:
        _create_scene()


def _show_scenes():
    """List scenes from asset registry."""
    am = st.session_state.asset_manager
    scenes = am.search(asset_type="scene")

    if not scenes:
        st.info("No scenes registered yet.")
        return

    for scene_data in scenes:
        meta = scene_data.get("metadata", {})
        name = meta.get("name", "Unnamed Scene")
        port = meta.get("port", "?")

        with st.expander(f"🎭 {name} (port {port})"):
            st.markdown(f"**ID:** `{scene_data['id'][:12]}…`")
            st.markdown(f"**Type:** {meta.get('type', 'unknown')}")
            chars = meta.get("characters", [])
            st.markdown(f"**Characters:** {len(chars)}")
            st.json(meta)

            if st.button("🗑️ Delete", key=f"del_scene_{scene_data['id']}"):
                try:
                    am.delete(scene_data["id"])
                    st.success("Deleted")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # Show discovered scenes from registry
    st.markdown("---")
    st.subheader("🔍 Discovered Scenes (from engine)")
    try:
        from engine.scenes.scene_registry import SceneRegistry
        registry = SceneRegistry()
        discovered = registry.discover()
        if discovered:
            for s in discovered:
                st.markdown(f"- **{s.name}** → port `{s.port}`")
        else:
            st.info("No scenes discovered in content/scenes/")
    except Exception as e:
        st.warning(f"Registry not available: {e}")


def _create_scene():
    """Simple scene creation form."""
    st.subheader("Create New Scene")

    name = st.text_input("Scene Name", key="cs_name")
    scene_type = st.selectbox("Type", ["phone", "bedroom", "dashboard", "custom"], key="cs_type")
    port = st.number_input("Port", 5000, 65535, 5560, key="cs_port")

    if st.button("✅ Create Scene", type="primary", key="cs_create"):
        if not name:
            st.error("Name required")
            return
        try:
            scene = SceneAsset(
                name=name,
                type=scene_type,
                host="0.0.0.0",
                port=port,
                characters=[],
                config={},
            )
            sid = st.session_state.asset_manager.save(scene)
            st.success(f"✅ Created scene '{name}' (ID: {sid[:12]}…)")
        except Exception as e:
            st.error(f"Error: {e}")
