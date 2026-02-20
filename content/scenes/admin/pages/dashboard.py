"""System Dashboard — landing page with service health, VRAM/RAM, loaded model info."""
import streamlit as st
import json
from datetime import datetime
from pathlib import Path


def render():
    st.header("📊 System Dashboard")

    # ── Service Health Row ──────────────────────────────────────────────
    st.subheader("🔌 Service Health")
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    # LMStudio
    with col1:
        try:
            from engine.lmstudio import get_lmstudio_manager
            mgr = get_lmstudio_manager()
            running = mgr.is_server_running()
            st.metric("LMStudio", "🟢 Online" if running else "🔴 Offline")
        except Exception:
            st.metric("LMStudio", "⚪ Unknown")

    # ComfyUI
    with col2:
        try:
            from content.simulation.services.comfyui_client import get_comfyui_client
            client = get_comfyui_client()
            st.metric("ComfyUI", "🟢 Online" if client.is_available() else "🔴 Offline")
        except Exception:
            st.metric("ComfyUI", "⚪ Unknown")

    # TTS Server
    with col3:
        try:
            from engine.logging import get_system_monitor
            health = get_system_monitor().check_services()
            tts_up = health.get("tts", {}).get("up", None)
            st.metric("TTS", "🟢 Online" if tts_up else ("🔴 Offline" if tts_up is False else "⚪ Unknown"))
        except Exception:
            st.metric("TTS", "⚪ Unknown")

    # MCP Server
    with col4:
        try:
            from engine.logging import get_system_monitor
            health = get_system_monitor().check_services()
            mcp_up = health.get("mcp", {}).get("up", None)
            st.metric("MCP", "🟢 Online" if mcp_up else ("🔴 Offline" if mcp_up is False else "⚪ Unknown"))
        except Exception:
            st.metric("MCP", "⚪ Unknown")

    # Database
    with col5:
        try:
            from content.simulation.database.db import Database
            db = Database()
            st.metric("Database", "🟢 OK")
        except Exception:
            st.metric("Database", "🔴 Error")

    # EventChain
    with col6:
        try:
            from content.simulation.database.events import EventChain
            ec = EventChain()
            chains = ec.get_recent_chains(limit=1)
            st.metric("EventChain", f"🟢 {len(chains)} recent")
        except Exception:
            st.metric("EventChain", "⚪ N/A")

    st.markdown("---")

    # ── System Metrics ──────────────────────────────────────────────────
    st.subheader("💻 System Metrics")
    try:
        from engine.logging import get_system_monitor
        monitor = get_system_monitor()
        snap = monitor.snapshot()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            cpu = snap.get("cpu_percent", "?")
            st.metric("CPU", f"{cpu}%")
        with col2:
            ram = snap.get("ram", {})
            used = ram.get("used_gb", "?")
            total = ram.get("total_gb", "?")
            pct = ram.get("percent", "?")
            st.metric("RAM", f"{used}/{total} GB ({pct}%)")
        with col3:
            gpu = snap.get("gpu", {})
            if gpu.get("available"):
                vram_used = gpu.get("vram_used_mb", 0)
                vram_total = gpu.get("vram_total_mb", 0)
                st.metric("VRAM", f"{vram_used}/{vram_total} MB")
            else:
                st.metric("VRAM", "N/A")
        with col4:
            import platform
            st.metric("Python", platform.python_version())

    except Exception as e:
        st.warning(f"System monitor not available: {e}")

    # ── Loaded Model ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🧠 Loaded Model")
    try:
        from engine.lmstudio import get_lmstudio_manager
        mgr = get_lmstudio_manager()
        loaded = mgr.list_loaded_models()
        if loaded:
            for m in loaded:
                model_path = m.get("path", m.get("id", "unknown"))
                st.markdown(f"**Model:** `{model_path}`")
                st.markdown(f"**Status:** {m.get('status', 'loaded')}")
        else:
            st.info("No model loaded")
    except Exception:
        st.info("LMStudio not available")

    # ── Asset Stats ─────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📦 Asset Overview")
    stats = st.session_state.asset_manager.get_stats()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _stat_card(stats['total_assets'], "Total Assets")
    with col2:
        _stat_card(stats['by_type'].get('character', 0), "Characters")
    with col3:
        _stat_card(stats['by_type'].get('scene', 0), "Scenes")
    with col4:
        _stat_card(stats['total_tags'], "Tags")

    # ── Benchmark Summary ───────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⏱️ Benchmark Summary")
    try:
        from engine.logging import get_benchmarks
        benchmarks = get_benchmarks()
        if benchmarks:
            rows = []
            for op, data in sorted(benchmarks.items()):
                rows.append({
                    "Operation": op,
                    "Count": data["count"],
                    "Avg (ms)": f"{data['avg_ms']:.1f}",
                    "P95 (ms)": f"{data['p95_ms']:.1f}",
                    "Max (ms)": f"{data['max_ms']:.1f}",
                })
            st.table(rows)
        else:
            st.info("No benchmark data yet. Interact with the scenes to generate timing data.")
    except Exception:
        st.info("Benchmark system not available")

    # ── Quick Actions ───────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚡ Quick Actions")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🧹 Clean Orphans", use_container_width=True):
            orphans = st.session_state.asset_manager.find_orphans()
            if orphans:
                st.warning(f"Found {len(orphans)} orphaned assets")
            else:
                st.success("No orphans found!")
    with col2:
        if st.button("📊 Export Stats", use_container_width=True):
            st.download_button(
                "Download Stats JSON",
                data=json.dumps(stats, indent=2),
                file_name=f"stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
            )
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    # ── Live Activity Feed ───────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚡ Live Activity Feed")
    try:
        from engine.services.activity_bus import get_activity_bus
        bus = get_activity_bus()
        activities = bus.get_recent(limit=30)
        if activities:
            col_f, col_filt = st.columns([3, 1])
            with col_filt:
                atype_filter = st.selectbox(
                    "Filter type",
                    ["all"] + sorted({a.get("activity_type", "") for a in activities}),
                    key="dash_act_filter",
                )
            if atype_filter != "all":
                activities = [a for a in activities if a.get("activity_type") == atype_filter]
            rows = []
            for a in reversed(activities[-20:]):
                rows.append({
                    "Time":   a.get("timestamp", "")[-8:],
                    "Type":   a.get("activity_type", ""),
                    "Agent":  a.get("agent_id", ""),
                    "Scene":  a.get("scene", ""),
                    "Detail": a.get("description", "")[:80],
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No activity yet — interact with a scene to populate the feed.")
    except Exception as _e:
        st.warning(f"Activity bus not available: {_e}")


def _stat_card(value, label):
    st.markdown(
        f"""<div style="background:linear-gradient(135deg,#667eea,#764ba2);
        padding:1.2rem;border-radius:10px;color:#fff;text-align:center;">
        <div style="font-size:2.2rem;font-weight:bold;">{value}</div>
        <div style="font-size:0.9rem;opacity:0.9;">{label}</div></div>""",
        unsafe_allow_html=True,
    )
