"""GOD Mode — raw SQL, force operations, override safety, red banner."""
import streamlit as st
import json
from datetime import datetime


_GOD_PASSWORD = "cosysim"  # Override in config for production


def render():
    st.header("👑 GOD Mode")

    if not st.session_state.get("god_mode", False):
        st.warning("⚠️ GOD Mode is disabled. Enter the password to enable full access.")
        pwd = st.text_input("Password", type="password", key="god_pwd")
        if st.button("🔓 Enable GOD Mode"):
            if pwd == _GOD_PASSWORD:
                st.session_state["god_mode"] = True
                st.success("GOD Mode enabled!")
                st.rerun()
            else:
                st.error("❌ Wrong password")
        return

    # ── RED BANNER ──────────────────────────────────────────────────────
    st.markdown(
        '<div style="background:#dc3545;color:#fff;padding:12px;border-radius:8px;'
        'text-align:center;font-weight:bold;font-size:1.2rem;margin-bottom:1rem;">'
        '👑 GOD MODE ACTIVE — All safety checks bypassed</div>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔒 Disable GOD Mode"):
            st.session_state["god_mode"] = False
            st.rerun()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🗄️ Raw SQL", "💉 Inject Event", "🎚️ Force Values",
        "🗑️ Danger Zone", "📊 DB Tables",
    ])

    with tab1:
        _render_raw_sql()
    with tab2:
        _render_inject_event()
    with tab3:
        _render_force_values()
    with tab4:
        _render_danger_zone()
    with tab5:
        _render_db_tables()


def _render_raw_sql():
    """Execute raw SQL queries."""
    st.subheader("🗄️ Raw SQL Executor")
    st.warning("⚠️ Direct database access. Be careful with UPDATE/DELETE statements!")

    query = st.text_area(
        "SQL Query",
        value="SELECT * FROM events ORDER BY timestamp DESC LIMIT 10",
        height=100,
        key="god_sql",
    )

    db_choice = st.radio("Database", ["Simulation DB", "Asset DB"], horizontal=True, key="god_db")

    if st.button("▶️ Execute", key="god_exec"):
        try:
            import sqlite3

            if db_choice == "Simulation DB":
                from content.simulation.database.db import Database
                db = Database()
                conn = db.get_connection().__enter__()
            else:
                from engine.assets import AssetManager
                mgr = AssetManager()
                conn = sqlite3.connect(mgr.db_path)

            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query)

            if query.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                if rows:
                    st.dataframe([dict(r) for r in rows])
                    st.caption(f"{len(rows)} row(s)")
                else:
                    st.info("No results")
            else:
                conn.commit()
                st.success(f"✅ {cursor.rowcount} row(s) affected")

            # Log to EventChain
            _log_god_action("raw_sql", {"query": query[:500], "db": db_choice})

        except Exception as e:
            st.error(f"SQL Error: {e}")


def _render_inject_event():
    """Manually inject an event into any chain."""
    st.subheader("💉 Inject Event")

    col1, col2 = st.columns(2)
    with col1:
        chain_id = st.text_input("Chain ID (blank = new chain)", key="god_chain")
        event_type = st.selectbox(
            "Event Type",
            ["message_in", "message_out", "llm_request", "llm_response",
             "tool_call", "tool_result", "media_generated", "scene_state_change",
             "god_mode_action", "error", "custom"],
            key="god_evt_type",
        )
    with col2:
        actor = st.text_input("Actor", value="god_mode", key="god_actor")
        scene_id = st.text_input("Scene ID", value="admin", key="god_scene")

    summary = st.text_input("Summary", key="god_summary")
    payload_text = st.text_area("Payload (JSON)", value="{}", height=80, key="god_payload")

    if st.button("💉 Inject", key="god_inject"):
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            st.error("Invalid JSON payload")
            return

        try:
            from content.simulation.database.events import EventChain
            ec = EventChain()
            ec.log(
                event_type=event_type,
                actor=actor,
                payload=payload,
                summary=summary,
                chain_id=chain_id or None,
                scene_id=scene_id,
            )
            st.success("✅ Event injected")
        except Exception as e:
            st.error(f"Injection failed: {e}")


def _render_force_values():
    """Force character state values."""
    st.subheader("🎚️ Force Character Values")

    try:
        from content.simulation.database.db import Database
        db = Database()
        characters = db.get_all_characters()
    except Exception:
        st.error("Database not available")
        return

    if not characters:
        st.info("No characters in database")
        return

    char_names = {c["id"]: c["name"] for c in characters}
    selected = st.selectbox(
        "Character",
        list(char_names.keys()),
        format_func=lambda x: char_names.get(x, x),
        key="god_force_char",
    )

    if not selected:
        return

    state = db.get_character_state(selected)
    if not state:
        st.info("No character state found")
        return

    st.markdown("**Current State:**")

    # Editable fields
    fields = {}
    col1, col2, col3 = st.columns(3)
    with col1:
        fields["mood"] = st.text_input("Mood", value=state.get("mood", "neutral"), key="god_mood")
        fields["relationship_level"] = st.slider(
            "Relationship", 0.0, 1.0, float(state.get("relationship_level", 0.5)),
            key="god_rel",
        )
    with col2:
        fields["arousal"] = st.slider(
            "Arousal", 0.0, 1.0, float(state.get("arousal", 0.0)),
            key="god_arousal",
        )
        fields["warmth"] = st.slider(
            "Warmth", 0.0, 1.0, float(state.get("warmth", 0.5)),
            key="god_warmth",
        )
    with col3:
        fields["flirtiness"] = st.slider(
            "Flirtiness", 0.0, 1.0, float(state.get("flirtiness", 0.5)),
            key="god_flirt",
        )
        fields["humor"] = st.slider(
            "Humor", 0.0, 1.0, float(state.get("humor", 0.5)),
            key="god_humor",
        )

    if st.button("🎚️ Force Update", key="god_force_apply"):
        try:
            db.update_character_state(selected, **fields)
            _log_god_action("force_character_state", {
                "character_id": selected,
                "fields": fields,
            })
            st.success(f"✅ Character state updated for {char_names[selected]}")
        except Exception as e:
            st.error(f"Update failed: {e}")


def _render_danger_zone():
    """Destructive operations."""
    st.subheader("🗑️ Danger Zone")
    st.error("⚠️ These operations are IRREVERSIBLE!")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Clear all events**")
        if st.checkbox("I understand this deletes ALL event chains", key="god_confirm_events"):
            if st.button("🗑️ Clear Events", key="god_clear_events"):
                try:
                    from content.simulation.database.db import Database
                    db = Database()
                    with db.get_connection() as conn:
                        conn.execute("DELETE FROM events")
                    _log_god_action("clear_events", {})
                    st.success("All events cleared")
                except Exception as e:
                    st.error(str(e))

    with col2:
        st.markdown("**Clear all conversations**")
        if st.checkbox("I understand this deletes ALL conversations", key="god_confirm_conv"):
            if st.button("🗑️ Clear Conversations", key="god_clear_conv"):
                try:
                    from content.simulation.database.db import Database
                    db = Database()
                    with db.get_connection() as conn:
                        conn.execute("DELETE FROM conversations")
                    _log_god_action("clear_conversations", {})
                    st.success("All conversations cleared")
                except Exception as e:
                    st.error(str(e))


def _render_db_tables():
    """Show all database tables and row counts."""
    st.subheader("📊 Database Tables")

    try:
        import sqlite3
        from content.simulation.database.db import Database
        db = Database()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            for table in sorted(tables):
                cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                count = cursor.fetchone()[0]
                cursor.execute(f"PRAGMA table_info([{table}])")
                cols = [row[1] for row in cursor.fetchall()]
                with st.expander(f"📋 {table} ({count} rows)"):
                    st.markdown(f"**Columns:** {', '.join(cols)}")
                    if count > 0 and count <= 100:
                        cursor.execute(f"SELECT * FROM [{table}] LIMIT 20")
                        rows = cursor.fetchall()
                        st.dataframe([dict(zip(cols, r)) for r in rows])
    except Exception as e:
        st.error(f"Error: {e}")


def _log_god_action(action: str, details: dict):
    """Log GOD mode actions to EventChain."""
    try:
        from content.simulation.database.events import EventChain
        ec = EventChain()
        ec.log(
            "god_mode_action",
            actor="god_mode",
            payload={"action": action, **details},
            summary=f"GOD: {action}",
            scene_id="admin",
        )
    except Exception:
        pass
