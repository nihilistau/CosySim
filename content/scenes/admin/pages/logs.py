"""Log Viewer — dropdown sources, level filter, live tail, benchmark summary."""
import streamlit as st
from pathlib import Path
from engine.paths import ROOT


def render():
    st.header("📜 Log Viewer")

    tab1, tab2, tab3 = st.tabs(["📋 File Logs", "🔄 Ring Buffer", "⏱️ Benchmarks"])

    with tab1:
        _render_file_logs()
    with tab2:
        _render_ring_buffer()
    with tab3:
        _render_benchmarks()


def _render_file_logs():
    """Log files from disk."""
    log_dir = ROOT / "logs"

    col1, col2, col3 = st.columns(3)
    with col1:
        log_level = st.selectbox("Level", ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"], key="file_level")
    with col2:
        max_lines = st.number_input("Max Lines", 10, 5000, 200, key="file_max")
    with col3:
        search_text = st.text_input("🔍 Search", key="file_search")

    if not log_dir.exists():
        st.info("No `logs/` directory found.")
        return

    log_files = sorted(log_dir.glob("*.log"), reverse=True)
    if not log_files:
        st.info("No log files.")
        return

    selected = st.selectbox("Log File", [f.name for f in log_files], key="file_select")
    if not selected:
        return

    try:
        with open(log_dir / selected, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Apply level filter
        if log_level != "ALL":
            lines = [l for l in lines if log_level in l]

        # Apply search filter
        if search_text:
            lines = [l for l in lines if search_text.lower() in l.lower()]

        # Tail
        lines = lines[-int(max_lines):]

        if lines:
            st.code("".join(lines), language="log")
            st.caption(f"Showing last {len(lines)} matching lines")

            # Export
            st.download_button(
                "📥 Export filtered logs",
                data="".join(lines),
                file_name=f"filtered_{selected}",
                mime="text/plain",
            )
        else:
            st.info("No matching lines.")
    except Exception as e:
        st.error(f"Error reading log: {e}")


def _render_ring_buffer():
    """In-memory CosyLogger ring buffer."""
    try:
        from engine.logging import get_logs, clear_logs

        col1, col2 = st.columns(2)
        with col1:
            level_filter = st.selectbox("Level", ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"], key="rb_level")
        with col2:
            if st.button("🗑️ Clear Buffer"):
                clear_logs()
                st.success("Buffer cleared")

        logs = get_logs()
        if not logs:
            st.info("Ring buffer is empty.")
            return

        if level_filter != "ALL":
            logs = [l for l in logs if level_filter in l]

        if logs:
            st.code("\n".join(logs), language="log")
            st.caption(f"{len(logs)} entries in buffer")
        else:
            st.info("No matching entries.")
    except ImportError:
        st.warning("engine.logging not available")


def _render_benchmarks():
    """Timing data from @timed decorator."""
    try:
        from engine.logging import get_benchmarks, reset_benchmarks

        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("🗑️ Reset"):
                reset_benchmarks()
                st.success("Benchmarks reset")

        benchmarks = get_benchmarks()
        if not benchmarks:
            st.info("No benchmark data yet. Use the scenes to generate timing data.")
            return

        rows = []
        for op, data in sorted(benchmarks.items()):
            rows.append({
                "Operation": op,
                "Calls": data["count"],
                "Total (ms)": f"{data['total_ms']:.0f}",
                "Avg (ms)": f"{data['avg_ms']:.1f}",
                "Min (ms)": f"{data['min_ms']:.1f}",
                "P95 (ms)": f"{data['p95_ms']:.1f}",
                "Max (ms)": f"{data['max_ms']:.1f}",
            })

        st.table(rows)

        # Export
        import json
        st.download_button(
            "📥 Export benchmarks",
            data=json.dumps(benchmarks, indent=2),
            file_name="benchmarks.json",
            mime="application/json",
        )
    except ImportError:
        st.warning("engine.logging not available")
