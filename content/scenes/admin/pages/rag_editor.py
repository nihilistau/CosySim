"""RAG Editor — browse and edit conversations, memories, agent messages with logic guards."""
import streamlit as st
import json
from datetime import datetime


def render():
    st.header("✏️ RAG Message Editor")
    st.markdown(
        "Edit stored conversations and memories. "
        "Changes are logged to EventChain as `rag_edit` events."
    )

    try:
        from content.simulation.database.db import Database
        db = Database()
    except Exception as e:
        st.error(f"Database not available: {e}")
        return

    tab1, tab2, tab3 = st.tabs(["💬 Conversations", "🧠 Memories", "📊 Interactions"])

    with tab1:
        _render_conversations(db)
    with tab2:
        _render_memories(db)
    with tab3:
        _render_interactions(db)


def _render_conversations(db):
    """Browse and edit conversation records."""
    st.subheader("Conversations")

    # Get characters for filtering
    try:
        characters = db.get_all_characters()
        char_names = {c["id"]: c["name"] for c in characters}
        char_ids = ["ALL"] + list(char_names.keys())
    except Exception:
        char_ids = ["ALL"]
        char_names = {}

    col1, col2 = st.columns(2)
    with col1:
        selected_char = st.selectbox(
            "Character",
            char_ids,
            format_func=lambda x: char_names.get(x, x) if x != "ALL" else "All Characters",
            key="rag_conv_char",
        )
    with col2:
        page_size = st.number_input("Per page", 5, 100, 20, key="rag_conv_page")

    try:
        if selected_char == "ALL":
            convos, total = db.get_conversations_paginated(limit=page_size)
        else:
            convos = db.get_character_conversations(selected_char, limit=page_size)
            total = len(convos)
    except Exception as e:
        st.error(f"Error loading conversations: {e}")
        return

    st.caption(f"{total} conversation(s) found")

    for conv in convos:
        conv_id = conv.get("id", "?")
        role = conv.get("role", "?")
        content = conv.get("content", "")
        char_id = conv.get("character_id", "")
        ts = conv.get("timestamp", "")[:19]
        char_name = char_names.get(char_id, char_id or "unknown")

        with st.expander(f"{'🧑' if role == 'user' else '🤖'} {role} — {char_name} — {ts}"):
            # Show current content
            god_mode = st.session_state.get("god_mode", False)

            new_content = st.text_area(
                "Content",
                value=content,
                key=f"rag_conv_{conv_id}",
                height=100,
            )

            col_a, col_b = st.columns([1, 4])
            with col_a:
                if st.button("💾 Save", key=f"save_conv_{conv_id}"):
                    if new_content == content:
                        st.info("No changes")
                    else:
                        # Logic guard: don't allow empty messages
                        if not new_content.strip():
                            st.error("❌ Cannot save empty message")
                        else:
                            try:
                                db.update_conversation(conv_id, content=new_content)
                                _log_rag_edit(db, "conversation", conv_id, content, new_content, char_id)
                                st.success("✅ Saved")
                            except Exception as e:
                                st.error(f"Save failed: {e}")
            with col_b:
                if god_mode:
                    if st.button("🗑️ Delete", key=f"del_conv_{conv_id}"):
                        try:
                            db.delete_conversation(conv_id)
                            st.success("Deleted")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))


def _render_memories(db):
    """Browse and edit memory entries."""
    st.subheader("Memories")

    try:
        characters = db.get_all_characters()
        char_names = {c["id"]: c["name"] for c in characters}
        char_ids = ["ALL"] + list(char_names.keys())
    except Exception:
        char_ids = ["ALL"]
        char_names = {}

    selected_char = st.selectbox(
        "Character",
        char_ids,
        format_func=lambda x: char_names.get(x, x) if x != "ALL" else "All Characters",
        key="rag_mem_char",
    )

    try:
        if selected_char == "ALL":
            memories, total = db.get_memories_paginated(limit=50)
        else:
            memories = db.get_character_memories(selected_char)
            total = len(memories)
    except Exception as e:
        st.error(f"Error: {e}")
        return

    st.caption(f"{total} memory/ies found")

    for mem in memories:
        mem_id = mem.get("id", "?")
        mem_type = mem.get("memory_type", "?")
        content = mem.get("content", "")
        char_id = mem.get("character_id", "")
        importance = mem.get("importance", 0)
        char_name = char_names.get(char_id, char_id or "unknown")

        with st.expander(f"🧠 {mem_type} — {char_name} (importance: {importance})"):
            new_content = st.text_area(
                "Content",
                value=content,
                key=f"rag_mem_{mem_id}",
                height=80,
            )

            new_importance = st.slider(
                "Importance",
                0.0, 1.0, float(importance),
                key=f"rag_mem_imp_{mem_id}",
            )

            if st.button("💾 Save", key=f"save_mem_{mem_id}"):
                if not new_content.strip():
                    st.error("❌ Cannot save empty memory")
                else:
                    try:
                        db.update_memory(mem_id, content=new_content, importance=new_importance)
                        _log_rag_edit(db, "memory", mem_id, content, new_content, char_id)
                        st.success("✅ Saved")
                    except Exception as e:
                        st.error(f"Save failed: {e}")


def _render_interactions(db):
    """Browse interactions/chain entries."""
    st.subheader("Interactions")

    try:
        characters = db.get_all_characters()
        char_names = {c["id"]: c["name"] for c in characters}
        char_ids = ["ALL"] + list(char_names.keys())
    except Exception:
        char_ids = ["ALL"]
        char_names = {}

    selected_char = st.selectbox(
        "Character",
        char_ids,
        format_func=lambda x: char_names.get(x, x) if x != "ALL" else "All Characters",
        key="rag_int_char",
    )

    try:
        if selected_char != "ALL":
            interactions = db.get_character_interactions(selected_char, limit=50)
        else:
            interactions = []
            for cid in list(char_names.keys())[:5]:
                interactions.extend(db.get_character_interactions(cid, limit=10))
    except Exception as e:
        st.error(f"Error: {e}")
        return

    st.caption(f"{len(interactions)} interaction(s)")

    for ix in interactions:
        ix_id = ix.get("id", "?")
        ix_type = ix.get("interaction_type", "?")
        content = ix.get("content", "")
        ts = ix.get("timestamp", "")[:19]

        with st.expander(f"📌 {ix_type} — {ts}"):
            st.text_area("Content", value=content, key=f"rag_ix_{ix_id}", disabled=True)
            meta = ix.get("metadata", {})
            if meta:
                st.json(meta)


def _log_rag_edit(db, entity_type, entity_id, old_value, new_value, character_id):
    """Log a RAG edit to EventChain."""
    try:
        from content.simulation.database.events import EventChain
        ec = EventChain(db)
        ec.log(
            "rag_edit",
            actor="admin_panel",
            payload={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "old_value": old_value[:500],
                "new_value": new_value[:500],
            },
            summary=f"RAG edit: {entity_type} {entity_id[:8]}…",
            chain_id=None,  # generates new chain
            scene_id="admin",
            character_id=character_id,
        )
    except Exception:
        pass
