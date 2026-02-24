"""Asset pages — browser, search, generator, dependencies, personality library.

These are extracted from the original monolith with minimal changes.
They share the ``st.session_state.asset_manager`` set up by the router.
"""
import streamlit as st
import json
from pathlib import Path
from datetime import datetime
from engine.paths import IMAGES_DIR


# ═══════════════════════════════════════════════════════════════════════
#  Asset Browser
# ═══════════════════════════════════════════════════════════════════════

def render_browser():
    st.header("🗂️ Asset Browser")

    col1, col2, col3 = st.columns(3)
    with col1:
        asset_type = st.selectbox(
            "Asset Type",
            ["All"] + st.session_state.asset_manager.get_stats()["registered_types"],
            key="ab_type",
        )
    with col2:
        search_tag = st.text_input("Search by Tag", key="ab_tag")
    with col3:
        limit = st.number_input("Results", 10, 100, 20, key="ab_limit")

    params = {"limit": limit}
    if asset_type != "All":
        params["asset_type"] = asset_type
    if search_tag:
        params["tags"] = [search_tag]

    results = st.session_state.asset_manager.search(**params)
    st.markdown(f"**Found {len(results)} assets**")
    st.markdown("---")

    for ad in results:
        with st.expander(f"{ad['type'].title()}: {ad['id'][:16]}…"):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.json(ad)
            with col2:
                if st.button("🗑️ Delete", key=f"del_{ad['id']}"):
                    try:
                        st.session_state.asset_manager.delete(ad["id"])
                        st.success("Deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Advanced Search
# ═══════════════════════════════════════════════════════════════════════

def render_search():
    st.header("🔍 Advanced Search")

    col1, col2, col3 = st.columns(3)
    with col1:
        search_type = st.selectbox(
            "Asset Type",
            ["All"] + st.session_state.asset_manager.get_stats()["registered_types"],
            key="as_type",
        )
    with col2:
        search_tags = st.text_input("Tags (comma-separated)", key="as_tags")
    with col3:
        limit = st.number_input("Max Results", 10, 100, 20, key="as_limit")

    if st.button("🔍 Search", use_container_width=True):
        params = {"limit": limit}
        if search_type != "All":
            params["asset_type"] = search_type
        if search_tags:
            params["tags"] = [t.strip() for t in search_tags.split(",")]

        results = st.session_state.asset_manager.search(**params)
        st.markdown(f"**Found {len(results)} assets**")
        st.markdown("---")
        for r in results:
            with st.expander(f"{r['type'].title()}: {r['id'][:16]}…"):
                st.json(r)


# ═══════════════════════════════════════════════════════════════════════
#  Personality Library
# ═══════════════════════════════════════════════════════════════════════

def render_personality_library():
    st.header("🧠 Personality Library")

    tab1, tab2 = st.tabs(["📋 Personality List", "➕ Create Personality"])

    with tab1:
        personalities = st.session_state.asset_manager.search(asset_type="personality")
        if not personalities:
            st.info("No personalities yet.")
        else:
            for pd in personalities:
                try:
                    pers = st.session_state.asset_manager.load("personality", pd["id"])
                except Exception:
                    continue
                with st.expander(f"**{pers.name}** ({pd['id'][:8]}…)"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Description:** {pers.description}")
                        st.markdown(f"**Type:** {pers.personality_type}")
                        st.markdown(f"**Traits:** {', '.join(pers.traits)}")
                    with col2:
                        st.markdown("**Parameters:**")
                        st.markdown(f"- Warmth: {pers.warmth}")
                        st.markdown(f"- Formality: {pers.formality}")
                        st.markdown(f"- Humor: {pers.humor}")
                        st.markdown(f"- Flirtiness: {pers.flirtiness}")
                    st.markdown("**System Prompt:**")
                    sp = pers.system_prompt
                    st.text(sp[:200] + "…" if len(sp) > 200 else sp)
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
                description = st.text_area("Description", placeholder="Happy personality")
                personality_type = st.text_input("Type", value="friendly")
                system_prompt = st.text_area("System Prompt", placeholder="You are a cheerful companion…")
                traits = st.text_input("Traits (comma-separated)", placeholder="optimistic, energetic")
            with col2:
                warmth = st.slider("Warmth", 0.0, 1.0, 0.7, 0.1)
                formality = st.slider("Formality", 0.0, 1.0, 0.3, 0.1)
                humor = st.slider("Humor", 0.0, 1.0, 0.5, 0.1)
                flirtiness = st.slider("Flirtiness", 0.0, 1.0, 0.5, 0.1)
                intelligence = st.slider("Intelligence", 0.0, 1.0, 0.7, 0.1)
                creativity = st.slider("Creativity", 0.0, 1.0, 0.6, 0.1)
                tags = st.text_input("Tags (comma-separated)", placeholder="positive")

            if st.form_submit_button("✨ Create Personality"):
                if not name:
                    st.error("Name required!")
                else:
                    try:
                        from engine.assets import PersonalityAsset
                        pers = PersonalityAsset.create(
                            name=name, description=description,
                            personality_type=personality_type,
                            system_prompt=system_prompt,
                            traits=[t.strip() for t in traits.split(",") if t.strip()],
                            warmth=warmth, formality=formality,
                            humor=humor, flirtiness=flirtiness,
                            intelligence=intelligence, creativity=creativity,
                            tags=[t.strip() for t in tags.split(",") if t.strip()],
                        )
                        st.session_state.asset_manager.save(pers)
                        st.success(f"✅ Created personality: {name}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Dependency Graph
# ═══════════════════════════════════════════════════════════════════════

def render_dependency_graph():
    st.header("🔗 Dependency Graph")

    all_assets = st.session_state.asset_manager.search(limit=1000)
    if not all_assets:
        st.info("No assets to visualize")
        return

    nodes, edges = [], []
    for a in all_assets:
        nodes.append({"id": a["id"], "type": a["type"]})
        try:
            deps = st.session_state.asset_manager.get_dependencies(a["id"])
            for dep_id in deps:
                edges.append({"source": a["id"], "target": dep_id})
        except Exception:
            pass

    st.markdown(f"**Nodes:** {len(nodes)} | **Edges:** {len(edges)}")

    if edges:
        st.subheader("Dependencies")
        for e in edges[:20]:
            st.markdown(f"- `{e['source'][:8]}…` → `{e['target'][:8]}…`")
        if len(edges) > 20:
            st.info(f"… and {len(edges) - 20} more")
    else:
        st.info("No dependencies found")

    st.markdown("---")
    orphans = st.session_state.asset_manager.find_orphans()
    if orphans:
        st.warning(f"Found {len(orphans)} orphaned assets")
        if st.button("🧹 Clean All Orphans"):
            for oid in orphans:
                try:
                    st.session_state.asset_manager.delete(oid)
                except Exception:
                    pass
            st.success("Cleaned!")
            st.rerun()
    else:
        st.success("No orphans!")


# ═══════════════════════════════════════════════════════════════════════
#  Asset Generator
# ═══════════════════════════════════════════════════════════════════════

def render_generator():
    st.header("🎨 Asset Generator")
    st.markdown("Generate media assets. Requires ComfyUI and LM Studio.")

    tab_img, tab_vid, tab_voice, tab_story = st.tabs(
        ["🖼️ Image", "🎥 Video", "🎤 Voice", "📖 Story"]
    )

    with tab_img:
        _gen_image()
    with tab_vid:
        _gen_video()
    with tab_voice:
        _gen_voice()
    with tab_story:
        _gen_story()


def _gen_image():
    st.subheader("Generate Image via ComfyUI")
    c1, c2 = st.columns(2)
    with c1:
        pos = st.text_area("Positive Prompt", placeholder="beautiful woman, realistic, 8k", key="gi_pos")
        neg = st.text_area("Negative Prompt", value="blurry, low quality", key="gi_neg")
    with c2:
        st.number_input("Width", value=512, step=64, key="gi_w")
        st.number_input("Height", value=512, step=64, key="gi_h")
        st.number_input("Steps", value=20, min_value=5, max_value=100, key="gi_s")
        st.checkbox("Allow NSFW", key="gi_nsfw")

    if st.button("🎨 Generate Image", type="primary"):
        with st.spinner("Generating…"):
            try:
                from content.simulation.services.comfyui_client import get_comfyui_client
                client = get_comfyui_client()
                if not client.is_available():
                    st.error("ComfyUI not reachable.")
                    return
                save_dir = IMAGES_DIR
                save_dir.mkdir(parents=True, exist_ok=True)
                path = client.generate_image(positive_prompt=pos, negative_prompt=neg, save_dir=str(save_dir))
                if path:
                    st.image(path, caption="Generated", use_container_width=True)
                    st.success(f"Saved: {path}")
                else:
                    st.error("Generation failed.")
            except Exception as e:
                st.error(str(e))


def _gen_video():
    st.subheader("Generate Video Message")
    st.info("Requires ComfyUI + CosyVoice running")
    vid_text = st.text_area("Script", key="gv_text")
    vid_mood = st.selectbox("Mood", ["happy", "flirty", "seductive", "sad", "excited"], key="gv_mood")
    if st.button("🎥 Generate Video"):
        st.info("Video generation delegates to ComfyUI workflow — not yet wired in admin.")


def _gen_voice():
    st.subheader("Generate Voice Message (TTS)")
    v_text = st.text_area("Text", key="gvo_text")
    v_emotion = st.selectbox("Emotion", ["happy", "flirty", "sad", "excited", "neutral"], key="gvo_emo")
    if st.button("🎤 Generate Voice"):
        st.info("Voice generation requires TTS server — coming in Phase 18 (Qwen3-TTS).")


def _gen_story():
    st.subheader("Generate Story via LLM")
    prompt = st.text_area("Prompt", key="gs_prompt")
    temp = st.slider("Temperature", 0.1, 2.0, 0.85, 0.05, key="gs_temp")
    max_tok = st.slider("Max tokens", 100, 2000, 500, 50, key="gs_tok")
    if st.button("📖 Generate Story"):
        with st.spinner("Generating…"):
            try:
                from content.simulation.services.llm_service import get_llm_service
                llm = get_llm_service()
                result = llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt="You are a creative fiction writer. Write vivid, immersive scenes.",
                    temperature=temp, max_tokens=max_tok,
                )
                st.markdown("---")
                st.markdown(result)
            except Exception as e:
                st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Database Management
# ═══════════════════════════════════════════════════════════════════════

def render_database():
    st.header("💾 Database Management")

    tab1, tab2, tab3 = st.tabs(["📊 Statistics", "🗄️ Asset DB", "🧠 RAG Memory"])

    with tab1:
        stats = st.session_state.asset_manager.get_stats()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Assets", stats["total_assets"])
        with col2:
            st.metric("Asset Types", len(stats["registered_types"]))
        with col3:
            st.metric("Total Tags", stats["total_tags"])
        st.markdown("---")
        st.subheader("Asset Breakdown")
        st.json(stats["by_type"])

    with tab2:
        st.subheader("Asset Database")
        import sqlite3
        from engine.assets import AssetManager
        mgr = AssetManager()
        st.markdown(f"**Database Path:** `{mgr.db_path}`")
        try:
            conn = sqlite3.connect(mgr.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            st.markdown("**Tables:**")
            for t in tables:
                st.markdown(f"- {t}")
        except Exception as e:
            st.error(str(e))

    with tab3:
        st.subheader("RAG Memory (ChromaDB)")
        st.info("RAG memory viewer integrated in the RAG Editor page.")
