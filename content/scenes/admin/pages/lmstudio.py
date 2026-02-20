"""LM Studio admin panel — server status, model lifecycle, benchmarking, KPI."""
from __future__ import annotations

import time
from typing import List, Optional

import streamlit as st


# ── Helpers ────────────────────────────────────────────────────────────

def _client():
    from engine.lmstudio import get_lmstudio_client
    return get_lmstudio_client()


def _manager():
    from engine.lmstudio import get_lmstudio_manager
    return get_lmstudio_manager()


def _model_manager():
    from engine.lmstudio import get_model_manager
    return get_model_manager()


def _config():
    try:
        from engine.config import get_config
        return get_config()
    except Exception:
        return None


# ── Section renderers ──────────────────────────────────────────────────

def _render_status(client, mgr):
    """Top status row: server reachability, loaded model, VRAM cap."""
    col1, col2, col3, col4 = st.columns(4)
    available = client.is_available()
    with col1:
        st.metric("REST API", "🟢 Online" if available else "🔴 Offline")
    with col2:
        running = mgr.is_server_running()
        st.metric("CLI Server", "🟢 Running" if running else "🔴 Stopped")
    with col3:
        model = client.get_loaded_model_id() or "—"
        st.metric("Loaded Model", model)
    with col4:
        st.metric("VRAM Cap", f"{mgr.vram_cap_mb:,} MB")

    if not available:
        st.warning(
            "LMStudio REST API not reachable. Make sure the server is running:\n"
            "```\nlms server start\n```"
        )


def _render_load_mode():
    """Load-mode selector with live config save."""
    st.subheader("⚙️ Model Loading Strategy")
    cfg = _config()
    current_mode = cfg.get("lmstudio.load_mode", "concurrent") if cfg else "concurrent"
    current_slots = int(cfg.get("lmstudio.concurrent_slots", 4) if cfg else 4)
    current_model = cfg.get("lmstudio.concurrent_model", "") if cfg else ""
    current_ttl = int(cfg.get("lmstudio.jit_ttl_seconds", 300) if cfg else 300)

    col_a, col_b = st.columns([1, 2])
    with col_a:
        mode = st.radio(
            "Mode",
            ["concurrent", "jit", "jit_ttl"],
            index=["concurrent", "jit", "jit_ttl"].index(current_mode),
            format_func=lambda m: {
                "concurrent": "🟦 Concurrent — one model, N parallel slots",
                "jit":        "🟨 JIT — load on demand, evict previous",
                "jit_ttl":    "🟧 JIT + TTL — auto-evict after idle timeout",
            }[m],
            help=(
                "**Concurrent**: keep one model resident and serve up to "
                "`concurrent_slots` requests at once (best for RTX 2060).\n\n"
                "**JIT**: swap models on each distinct request — slower but "
                "allows testing multiple models without manual unloading.\n\n"
                "**JIT+TTL**: like JIT but automatically unloads after the "
                "configured idle timeout."
            ),
        )

    with col_b:
        if mode in ("concurrent",):
            slots = st.number_input(
                "Concurrent slots",
                min_value=1, max_value=16,
                value=current_slots,
                help="Must match LMStudio Server → Advanced → Max parallel requests.",
            )
            pin_model = st.text_input(
                "Pinned model (optional)",
                value=current_model,
                placeholder="e.g. qwen3-vl-8b (leave empty = auto-resolve)",
            )
        if mode == "jit_ttl":
            ttl = st.number_input(
                "Idle TTL (seconds)",
                min_value=30, max_value=3600,
                value=current_ttl,
                step=30,
            )

    if st.button("💾 Save load strategy", key="save_load_mode"):
        try:
            mm = _model_manager()
            from engine.lmstudio import LoadMode
            mm.set_mode(LoadMode[mode.upper()])

            if cfg:
                cfg.set("lmstudio.load_mode", mode)
                if mode == "concurrent":
                    cfg.set("lmstudio.concurrent_slots", int(slots))
                    cfg.set("lmstudio.concurrent_model", pin_model.strip())
                if mode == "jit_ttl":
                    cfg.set("lmstudio.jit_ttl_seconds", int(ttl))
            st.success(f"Saved — mode set to **{mode}**")
        except Exception as exc:
            st.error(f"Failed: {exc}")


def _render_sessions():
    """Active model sessions table from ModelManager."""
    st.subheader("📋 Active Model Sessions")
    try:
        mm = _model_manager()
        status = mm.status()
        sessions = status.get("sessions", [])
        if sessions:
            import pandas as pd
            df = pd.DataFrame(sessions)
            # Friendly column labels
            col_map = {
                "model_key": "Model",
                "is_expired": "Expired",
                "request_count": "Requests",
                "ttl_seconds": "TTL (s)",
            }
            df = df.rename(columns=col_map)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No active sessions tracked yet.")

        st.caption(f"Mode: **{status.get('mode', '?')}** | Sessions: {status.get('session_count', 0)}")
    except Exception as exc:
        st.warning(f"Session data unavailable: {exc}")


def _render_model_controls(mgr, client):
    """Load / unload controls using ModelManager."""
    st.subheader("🔧 Model Controls")
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Load model**")
        available = st.session_state.get("lms_available", [])
        if not available:
            if st.button("🔄 Scan available models", key="scan_models"):
                with st.spinner("Scanning…"):
                    st.session_state["lms_available"] = mgr.get_available_models()
                st.rerun()
        else:
            search = st.text_input("Filter", key="model_filter")
            shown = [m for m in available if search.lower() in m.lower()] if search else available
            selected = st.selectbox("Select model", shown[:200], key="model_select")
            load_opts = st.expander("Load options")
            with load_opts:
                gpu_frac = st.slider("GPU fraction", 0.0, 1.0, float(mgr.default_gpu), 0.05)
                ctx_len  = st.number_input("Context length", 512, 32768, 4096, 512)
            if st.button("⬇️ Load", key="load_selected"):
                try:
                    from engine.lmstudio import get_model_manager
                    mm = get_model_manager()
                    mm.ensure_loaded(selected)
                    client.invalidate_model_cache()
                    st.success(f"Loaded `{selected}`")
                except Exception as exc:
                    st.error(str(exc))

    with col_r:
        st.markdown("**Unload model**")
        loaded_models = client.get_models()
        if not loaded_models:
            st.info("No models loaded.")
        else:
            for m in loaded_models:
                mid = m.get("id", "?")
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"• `{mid}`")
                with c2:
                    if st.button("Unload", key=f"unload_{mid}"):
                        try:
                            from engine.lmstudio import get_model_manager
                            mm = get_model_manager()
                            mm.release(mid)
                            client.invalidate_model_cache()
                            st.success(f"Unloaded `{mid}`")
                        except Exception as exc:
                            st.error(str(exc))


def _render_benchmark(client):
    """Benchmark runner: pick model(s), N runs, prompt → results table."""
    st.subheader("🏁 Benchmark")

    with st.form("bench_form"):
        bench_prompt = st.text_area(
            "Benchmark prompt",
            value="Write a short poem about autumn.",
            height=80,
        )
        bench_system = st.text_input(
            "System prompt",
            value="You are a helpful assistant.",
        )
        bench_models_raw = st.text_input(
            "Models to test (comma-separated, leave blank for current loaded)",
            placeholder="qwen3-vl-8b, llama3-8b",
        )
        col_x, col_y = st.columns(2)
        with col_x:
            n_runs = st.number_input("Runs per model", min_value=1, max_value=50, value=5)
        with col_y:
            max_tokens = st.number_input("Max tokens per run", min_value=10, max_value=2000, value=150)

        run_btn = st.form_submit_button("▶ Run Benchmark")

    if run_btn:
        models: Optional[List[str]] = None
        if bench_models_raw.strip():
            models = [m.strip() for m in bench_models_raw.split(",") if m.strip()]

        msgs = [
            {"role": "system", "content": bench_system},
            {"role": "user", "content": bench_prompt},
        ]

        with st.spinner(f"Running {n_runs} run(s){' per model' if models else ''}…"):
            try:
                report = client.benchmark_model(
                    msgs,
                    n_runs=int(n_runs),
                    models=models,
                    max_tokens=int(max_tokens),
                )
            except Exception as exc:
                st.error(f"Benchmark failed: {exc}")
                return

        st.success(f"Completed {report['total_runs']} total runs.")
        import pandas as pd
        rows = []
        for mdl, stats in report["results"].items():
            if stats.get("count", 0) == 0:
                rows.append({"Model": mdl, "Runs": 0, "Errors": stats.get("errors", "?"),
                             "Avg ms": "—", "P50 ms": "—", "P95 ms": "—",
                             "Avg tok/s": "—"})
            else:
                rows.append({
                    "Model":     mdl,
                    "Runs":      stats["count"],
                    "Errors":    stats["errors"],
                    "Avg ms":    stats["avg_latency_ms"],
                    "P50 ms":    stats["p50_ms"],
                    "P95 ms":    stats["p95_ms"],
                    "Min ms":    stats["min_ms"],
                    "Max ms":    stats["max_ms"],
                    "Avg tok/s": stats["avg_tps"],
                    "Std ms":    stats["stddev_ms"],
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        st.session_state["last_bench"] = report


def _render_kpi():
    """Live KPI table from engine.logging.benchmark."""
    st.subheader("📊 Live KPI (all lmstudio_chat calls)")
    try:
        from engine.logging.benchmark import get_llm_kpis, get_benchmarks
        kpis = get_llm_kpis("lmstudio_chat")
        if not kpis:
            st.info("No KPI data yet — send a message to generate some.")
            return

        # Show last 20 entries
        import pandas as pd
        recent = kpis[-20:]
        df = pd.DataFrame(recent)
        if "timestamp" in df.columns:
            df["time"] = pd.to_datetime(df["timestamp"], unit="s").dt.strftime("%H:%M:%S")
            df = df.drop(columns=["timestamp"])

        col_order = ["time", "model", "latency_ms", "tokens_in", "tokens_out", "tokens_per_sec", "first_token_ms"]
        df = df.reindex(columns=[c for c in col_order if c in df.columns])
        st.dataframe(df, use_container_width=True)

        # Summary row
        summary = get_benchmarks().get("lmstudio_chat", {})
        if summary:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total calls", summary.get("count", 0))
            c2.metric("Avg latency", f"{summary.get('avg_ms', 0):.0f} ms")
            c3.metric("P95 latency", f"{summary.get('p95_ms', 0):.0f} ms")
            c4.metric("Min latency", f"{summary.get('min_ms', 0):.0f} ms")

        if st.button("🔄 Refresh KPI", key="refresh_kpi"):
            st.rerun()

    except Exception as exc:
        st.warning(f"KPI unavailable: {exc}")


# ── Main entry point ───────────────────────────────────────────────────


def _render_activity_feed():
    """Live ActivityBus feed filtered to LLM inference events."""
    st.subheader("⚡ LLM Activity Feed")
    try:
        from engine.services.activity_bus import get_activity_bus
        bus = get_activity_bus()
        events = bus.get_recent(activity_type="llm_inference", limit=50)
        if not events:
            st.info("No LLM activity yet — send a message to generate some.")
        else:
            for ev in reversed(events):
                ts = ev.get("timestamp", "")[:19]
                desc = ev.get("description", "")
                data = ev.get("data", {})
                model = data.get("model", "?")
                tokens = data.get("tokens_out", "?")
                st.markdown(f"`{ts}` **{desc}** — model=`{model}` tokens_out=`{tokens}`")
        if st.button("🔄 Refresh", key="refresh_activity"):
            st.rerun()
    except Exception as exc:
        st.warning(f"Activity feed unavailable: {exc}")


def render():
    st.header("🤖 LM Studio")

    try:
        client = _client()
        mgr    = _manager()
    except Exception as exc:
        st.error(f"LMStudio modules not available: {exc}")
        return

    _render_status(client, mgr)
    st.markdown("---")

    tab_config, tab_sessions, tab_models, tab_bench, tab_kpi, tab_activity = st.tabs([
        "⚙️ Load Strategy",
        "📋 Sessions",
        "🔧 Model Controls",
        "🏁 Benchmark",
        "📊 KPI",
        "⚡ Activity",
    ])

    with tab_config:
        _render_load_mode()

    with tab_sessions:
        _render_sessions()

    with tab_models:
        _render_model_controls(mgr, client)

    with tab_bench:
        _render_benchmark(client)

    with tab_kpi:
        _render_kpi()

    with tab_activity:
        _render_activity_feed()

