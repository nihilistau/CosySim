"""EventChain Browser — tree view, filtering, detail panel."""
import streamlit as st
from pathlib import Path


def render():
    st.header("🔗 Event Chains")
    st.markdown(
        "Browse causal event trees logged by `CharacterAgent`, "
        "`AutonomousMessenger`, and services. Each *chain* groups all "
        "events for a single turn or autonomous cycle."
    )

    try:
        from content.simulation.database.db import Database
        from content.simulation.database.events import EventChain

        db = Database()
        ec = EventChain(db)

        # ── Filters ─────────────────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            scene_filter = st.text_input("Scene", "", key="chain_scene")
        with col2:
            char_filter = st.text_input("Character ID", "", key="chain_char")
        with col3:
            type_filter = st.selectbox(
                "Event Type",
                ["ALL", "message_in", "message_out", "llm_request", "llm_response",
                 "tool_call", "tool_result", "rag_query", "rag_result",
                 "memory_stored", "media_generated", "autonomous_trigger",
                 "scene_state_change", "error"],
                key="chain_type",
            )
        with col4:
            limit = st.number_input("Max chains", 5, 500, 30, key="chain_limit")

        chains = ec.get_recent_chains(
            scene_id=scene_filter or None,
            limit=int(limit),
        )

        if not chains:
            st.info("No event chains recorded yet. Start a scene and interact.")
            return

        st.markdown(f"**{len(chains)} chain(s) found**")
        st.markdown("---")

        for chain in chains:
            chain_id = chain.get("chain_id", "?")
            scene_id = chain.get("scene_id", "?")
            char_id_val = chain.get("character_id", "")
            timestamp = chain.get("started_at", "")

            # Skip if char filter active and doesn't match
            if char_filter and char_filter not in (char_id_val or ""):
                continue

            tree = ec.get_chain_as_tree(chain_id)
            root_events = tree.get("events", [])

            # Apply event type filter
            if type_filter != "ALL":
                root_events = _filter_events(root_events, type_filter)
                if not root_events:
                    continue

            evt_count = _count_events(root_events)

            with st.expander(
                f"🔗 {chain_id[:12]}… | {evt_count} events | {timestamp[:19]} | {scene_id}",
                expanded=False,
            ):
                if not root_events:
                    st.info("No events")
                    continue

                # Chain metadata
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.caption(f"Chain: `{chain_id}`")
                with col_b:
                    st.caption(f"Scene: `{scene_id}`")
                with col_c:
                    st.caption(f"Character: `{char_id_val or 'N/A'}`")

                st.markdown("---")

                # Render tree
                for root_ev in root_events:
                    _render_node(root_ev, chain_id, depth=0)

    except ImportError as e:
        st.error(f"Could not load EventChain module: {e}")
    except Exception as e:
        st.error(f"Error: {e}")


# ── Helpers ─────────────────────────────────────────────────────────────

_ICON_MAP = {
    "llm_request": "📤", "llm_response": "🤖", "llm_cancelled": "❌",
    "tool_call": "🔧", "tool_result": "✅",
    "rag_query": "🔍", "rag_result": "🧠",
    "memory_stored": "💾", "media_generated": "🎨",
    "message_in": "💬", "message_out": "📱",
    "autonomous_trigger": "⏰",
    "scene_state_change": "⚙️",
    "error": "⚠️",
    "god_mode_action": "👑",
    "rag_edit": "✏️",
    "benchmark": "⏱️",
}


def _render_node(node, chain_id, depth=0):
    ev_type = node.get("event_type", "?")
    actor = node.get("actor", "?")
    ev_sum = node.get("summary", "")
    ts = node.get("timestamp", "")[:19]
    icon = _ICON_MAP.get(ev_type, "▶️")
    indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * depth
    connector = "└─ " if depth > 0 else ""

    st.markdown(
        f"{indent}{connector}{icon} **{ev_type}** _(actor={actor})_"
        f"  &nbsp; `{ts}`  \n"
        f"{indent}&nbsp;&nbsp;&nbsp;&nbsp; {ev_sum}",
        unsafe_allow_html=True,
    )

    payload = node.get("payload", {})
    if payload:
        node_id = node.get("id", f"{chain_id}_{ev_type}_{depth}")
        if st.checkbox(f"Show payload ({ev_type})", key=f"pay_{node_id}"):
            st.json(payload)

    for child in node.get("children", []):
        _render_node(child, chain_id, depth + 1)


def _count_events(nodes):
    n = len(nodes)
    for node in nodes:
        n += _count_events(node.get("children", []))
    return n


def _filter_events(nodes, event_type):
    """Filter tree keeping only nodes matching the type (or with matching children)."""
    result = []
    for node in nodes:
        children = _filter_events(node.get("children", []), event_type)
        if node.get("event_type") == event_type or children:
            filtered = dict(node)
            filtered["children"] = children
            result.append(filtered)
    return result
