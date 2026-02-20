"""
KPI Dashboard — Performance metrics, LLM benchmarks, and system analytics.

Admin panel page that provides:
- Operation timing stats (all @timed calls)
- LLM-specific KPIs (tokens/sec, TTFT, input/output tokens)
- System resource monitoring (CPU, RAM, GPU)
- EventChain analytics (chain stats, event type distribution)
"""
import json
import time
import streamlit as st
from datetime import datetime


def render():
    """Render the KPI Dashboard page."""
    st.header("📊 KPI Dashboard")
    st.caption("Performance metrics, benchmarks, and system analytics")

    # ── Tabs ────────────────────────────────────────────────────────
    tab_ops, tab_llm, tab_system, tab_chains = st.tabs([
        "⏱️ Operations", "🧠 LLM KPIs", "💻 System", "🔗 Chain Analytics"
    ])

    # ── Operations tab ──────────────────────────────────────────────
    with tab_ops:
        _render_operations()

    # ── LLM KPIs tab ────────────────────────────────────────────────
    with tab_llm:
        _render_llm_kpis()

    # ── System tab ──────────────────────────────────────────────────
    with tab_system:
        _render_system()

    # ── Chain analytics tab ─────────────────────────────────────────
    with tab_chains:
        _render_chain_analytics()


def _render_operations():
    """Render operation timing benchmarks."""
    try:
        from engine.logging import get_benchmarks, get_all_operations, reset_benchmarks
    except ImportError:
        st.warning("Benchmarking module not available.")
        return

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🗑️ Reset All", key="reset_benchmarks"):
            reset_benchmarks()
            st.rerun()

    stats = get_benchmarks()
    if not stats:
        st.info("No benchmark data yet. Operations will appear as they execute.")
        return

    # Summary metrics
    total_ops = sum(s["count"] for s in stats.values())
    total_time = sum(s["total_ms"] for s in stats.values())
    unique_ops = len(stats)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Calls", f"{total_ops:,}")
    c2.metric("Total Time", f"{total_time / 1000:.1f}s")
    c3.metric("Tracked Ops", str(unique_ops))

    st.divider()

    # Table of all operations sorted by total time
    sorted_ops = sorted(stats.items(), key=lambda x: x[1]["total_ms"], reverse=True)

    for op_name, s in sorted_ops:
        with st.expander(f"**{op_name}** — {s['count']} calls, avg {s['avg_ms']:.1f}ms"):
            cols = st.columns(6)
            cols[0].metric("Count", s["count"])
            cols[1].metric("Avg", f"{s['avg_ms']:.1f}ms")
            cols[2].metric("Min", f"{s['min_ms']:.1f}ms")
            cols[3].metric("Max", f"{s['max_ms']:.1f}ms")
            cols[4].metric("P95", f"{s['p95_ms']:.1f}ms")
            cols[5].metric("Total", f"{s['total_ms'] / 1000:.2f}s")

            # Mini chart of raw timings
            try:
                from engine.logging import get_operation_timings
                timings = get_operation_timings(op_name)
                if timings and len(timings) > 1:
                    st.line_chart(timings[-100:], height=120)
            except Exception:
                pass


def _render_llm_kpis():
    """Render LLM-specific performance indicators."""
    try:
        from engine.logging import get_llm_kpis, get_kpi_timeseries
    except ImportError:
        st.warning("LLM KPI tracking not available.")
        return

    kpis = get_llm_kpis()
    if kpis.get("count", 0) == 0:
        st.info(
            "No LLM KPI data yet. KPIs are recorded when using the REST v2 client "
            "(`client_v2.py`) or when `record_llm_kpi()` is called manually."
        )
        st.code(
            "from engine.logging import record_llm_kpi\n"
            "record_llm_kpi('llm_chat', latency_ms=350, tokens_in=50, tokens_out=120, model='qwen-7b')",
            language="python",
        )
        return

    # Summary
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Calls", kpis["count"])
    c2.metric("Avg Latency", f"{kpis['avg_latency_ms']:.0f}ms")
    c3.metric("Avg Tokens/s", f"{kpis['avg_tokens_per_sec']:.1f}")
    c4.metric("Avg TTFT", f"{kpis['avg_first_token_ms']:.0f}ms")

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tokens In", f"{kpis['total_tokens_in']:,}")
    c2.metric("Total Tokens Out", f"{kpis['total_tokens_out']:,}")
    c3.metric("P95 Latency", f"{kpis['p95_latency_ms']:.0f}ms")
    c4.metric("Models Used", ", ".join(kpis.get("models", [])) or "—")

    # Timeseries chart
    timeseries = get_kpi_timeseries(last_n=100)
    if timeseries:
        st.subheader("Token Throughput Over Time")
        tps_data = [s["tokens_per_sec"] for s in timeseries]
        if len(tps_data) > 1:
            st.line_chart(tps_data, height=200)

        st.subheader("Latency Over Time")
        lat_data = [s["latency_ms"] for s in timeseries]
        if len(lat_data) > 1:
            st.line_chart(lat_data, height=200)


def _render_system():
    """Render system resource monitoring."""
    try:
        from engine.logging import get_system_monitor
        monitor = get_system_monitor()
        snap = monitor.snapshot()
    except Exception:
        st.warning("System monitor not available (psutil/nvidia-smi may be missing).")
        return

    # CPU & RAM
    st.subheader("Hardware")
    c1, c2, c3 = st.columns(3)
    c1.metric("CPU", f"{snap.get('cpu_percent', 0):.0f}%")
    c2.metric("RAM", f"{snap.get('ram_used_gb', 0):.1f} / {snap.get('ram_total_gb', 0):.1f} GB")
    c3.metric("RAM %", f"{snap.get('ram_percent', 0):.0f}%")

    # GPU
    gpu_name = snap.get("gpu_name", "N/A")
    gpu_vram_used = snap.get("gpu_vram_used_mb", 0)
    gpu_vram_total = snap.get("gpu_vram_total_mb", 0)
    gpu_temp = snap.get("gpu_temp_c", 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("GPU", gpu_name)
    c2.metric("VRAM", f"{gpu_vram_used} / {gpu_vram_total} MB")
    c3.metric("GPU Temp", f"{gpu_temp}°C" if gpu_temp else "N/A")

    if gpu_vram_total > 0:
        pct = gpu_vram_used / gpu_vram_total
        st.progress(min(pct, 1.0), text=f"VRAM: {pct*100:.0f}%")

    # Service health
    st.subheader("Service Health")
    try:
        services = monitor.check_services()
        for name, info in services.items():
            icon = "🟢" if info.get("up") else "🔴"
            lat = f"{info.get('latency_ms', 0):.0f}ms" if info.get("up") else info.get("error", "offline")
            st.write(f"{icon} **{name}**: {lat}")
    except Exception:
        st.info("Service health check unavailable.")


def _render_chain_analytics():
    """Render EventChain analytics."""
    try:
        from content.simulation.database.events import EventChain
        ec = EventChain()
    except Exception:
        st.warning("EventChain not available.")
        return

    try:
        chains = ec.get_recent_chains(limit=50)
    except Exception:
        chains = []

    if not chains:
        st.info("No EventChain data yet.")
        return

    st.metric("Recent Chains", len(chains))

    # Event type distribution
    type_counts = {}
    total_events = 0
    chain_lengths = []

    for chain in chains:
        chain_id = chain.get("chain_id", "")
        try:
            events = ec.get_chain_events(chain_id)
            chain_lengths.append(len(events))
            for ev in events:
                evt = ev.get("event_type", "unknown") if isinstance(ev, dict) else "unknown"
                type_counts[evt] = type_counts.get(evt, 0) + 1
                total_events += 1
        except Exception:
            pass

    st.subheader("Event Type Distribution")
    if type_counts:
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        for etype, count in sorted_types:
            pct = count / total_events * 100 if total_events > 0 else 0
            st.write(f"**{etype}**: {count} ({pct:.0f}%)")
    else:
        st.info("No events found in recent chains.")

    # Chain length stats
    if chain_lengths:
        st.subheader("Chain Length Statistics")
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Length", f"{sum(chain_lengths) / len(chain_lengths):.1f}")
        c2.metric("Max Length", max(chain_lengths))
        c3.metric("Total Events", total_events)

        if len(chain_lengths) > 1:
            st.bar_chart(chain_lengths[-30:], height=150)
