"""LM Studio panel — model management, server status, VRAM budget."""
import streamlit as st


def render():
    st.header("🤖 LM Studio")
    st.markdown(
        "Monitor and manage your local LM Studio instance."
    )

    try:
        from engine.lmstudio import get_lmstudio_manager
        mgr = get_lmstudio_manager()

        # Status row
        col1, col2, col3 = st.columns(3)
        running = mgr.is_server_running()
        with col1:
            st.metric("Server", "🟢 Online" if running else "🔴 Offline")
        with col2:
            st.metric("Host", mgr.host)
        with col3:
            st.metric("Port", str(mgr.port))

        if not running:
            st.warning("LM Studio server not reachable. Start it with:\n```\nlms server start\n```")
            return

        st.markdown("---")

        # Loaded models
        st.subheader("Loaded Models")
        loaded = mgr.list_loaded_models()
        if not loaded:
            st.info("No models currently loaded.")
        else:
            for m in loaded:
                model_path = m.get("path", m.get("id", "unknown"))
                with st.expander(f"📦 {model_path}", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**Status:** `{m.get('status', '?')}`")
                    with col_b:
                        if st.button("Unload", key=f"unload_{hash(model_path)}"):
                            try:
                                mgr.unload_model()
                                st.success("Model unloaded. Refresh to update.")
                            except Exception as e:
                                st.error(str(e))

        st.markdown("---")

        # Available models
        st.subheader("Available Models (on disk)")
        if st.button("🔄 Refresh model list"):
            st.session_state.pop("lms_available", None)

        if "lms_available" not in st.session_state:
            with st.spinner("Scanning models…"):
                st.session_state["lms_available"] = mgr.get_available_models()

        available = st.session_state.get("lms_available", [])
        if not available:
            st.info("No models found. Add models via the LM Studio app.")
        else:
            search = st.text_input("🔍 Filter models", "", key="lms_search")
            shown = [m for m in available if search.lower() in str(m).lower()] if search else available

            st.markdown(f"**{len(shown)} model(s)**")
            for m in shown[:100]:
                key = m if isinstance(m, str) else m.get("path", str(m))
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"• `{key}`")
                with col_b:
                    if st.button("Load", key=f"load_{hash(key)}"):
                        try:
                            mgr.load_model(key)
                            st.success(f"Load requested for `{key}`")
                        except Exception as e:
                            st.error(str(e))

        st.markdown("---")

        # VRAM budget
        st.subheader("VRAM Budget")
        st.markdown(
            f"**Cap:** {mgr.vram_cap_mb:,} MB  |  "
            f"**Default GPU fraction:** {mgr.default_gpu * 100:.0f}%"
        )

    except ImportError as e:
        st.error(f"LM Studio module not found: {e}")
    except Exception as e:
        st.error(f"Error: {e}")
