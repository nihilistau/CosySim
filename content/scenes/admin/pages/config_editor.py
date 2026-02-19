"""Config Editor — type-aware inputs, validation, save & apply."""
import streamlit as st
import json
import os
from pathlib import Path


def render():
    st.header("⚙️ Configuration Editor")

    tab1, tab2, tab3 = st.tabs(["📋 View", "✏️ Edit", "🔄 Environment"])

    with tab1:
        _render_view()
    with tab2:
        _render_edit()
    with tab3:
        _render_env()


def _render_view():
    """Read-only view of current config."""
    config = st.session_state.config
    st.subheader("Current Configuration")
    try:
        data = dict(config._config)
        st.json(data)
    except Exception as e:
        st.error(f"Error reading config: {e}")


def _render_edit():
    """Interactive config editor with validation."""
    st.subheader("Edit Configuration")

    config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "default.yaml"

    if not config_path.exists():
        st.error(f"Config file not found: {config_path}")
        return

    try:
        import yaml
    except ImportError:
        st.error("PyYAML not installed")
        return

    # Load current YAML
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
        data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        st.error("Config is not a valid YAML dictionary")
        return

    modified = False
    updated = {}

    for section, values in sorted(data.items()):
        with st.expander(f"📁 {section}", expanded=False):
            if isinstance(values, dict):
                for key, val in sorted(values.items()):
                    new_val = _editable_field(f"{section}.{key}", val)
                    if new_val != val:
                        modified = True
                    if section not in updated:
                        updated[section] = {}
                    updated[section][key] = new_val
            else:
                new_val = _editable_field(section, values)
                if new_val != values:
                    modified = True
                updated[section] = new_val

    # Validate
    st.markdown("---")
    if st.button("🔍 Validate"):
        _validate(updated)

    # Save
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Save & Apply", disabled=not modified, type="primary"):
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)
                # Reload config singleton
                from engine.config import get_config
                cfg = get_config()
                cfg.reload()
                st.success("✅ Config saved and reloaded")
            except Exception as e:
                st.error(f"Save failed: {e}")
    with col2:
        if st.button("↩️ Reset to file"):
            st.rerun()

    if modified:
        st.info("⚠️ You have unsaved changes")


def _render_env():
    """Environment variable overrides."""
    st.subheader("Environment Variables")
    env_vars = {k: v for k, v in os.environ.items()
                if k.startswith("COSYSIM_") or k.startswith("COSYVOICE_")}

    if env_vars:
        st.json(env_vars)
        st.caption("These values override the YAML config")
    else:
        st.info("No COSYSIM_* or COSYVOICE_* environment variables set")

    # Show config file location
    st.markdown("---")
    st.markdown("**Config Files:**")
    st.code(
        "config/default.yaml       — Base configuration\n"
        "config/development.yaml   — Development overrides\n"
        "config/production.yaml    — Production settings"
    )


def _editable_field(key: str, value):
    """Render an appropriate input widget based on value type."""
    if isinstance(value, bool):
        return st.checkbox(key, value=value, key=f"cfg_{key}")
    elif isinstance(value, int):
        return st.number_input(key, value=value, step=1, key=f"cfg_{key}")
    elif isinstance(value, float):
        return st.number_input(key, value=value, step=0.01, format="%.4f", key=f"cfg_{key}")
    elif isinstance(value, str):
        return st.text_input(key, value=value, key=f"cfg_{key}")
    elif isinstance(value, list):
        edited = st.text_area(key, value=json.dumps(value, indent=2), key=f"cfg_{key}")
        try:
            return json.loads(edited)
        except json.JSONDecodeError:
            st.warning(f"Invalid JSON for {key}")
            return value
    elif isinstance(value, dict):
        edited = st.text_area(key, value=json.dumps(value, indent=2), key=f"cfg_{key}")
        try:
            return json.loads(edited)
        except json.JSONDecodeError:
            st.warning(f"Invalid JSON for {key}")
            return value
    elif value is None:
        return st.text_input(key, value="", key=f"cfg_{key}") or None
    else:
        return st.text_input(key, value=str(value), key=f"cfg_{key}")


def _validate(config: dict):
    """Run config validation and show results."""
    try:
        from engine.config_validator import validate_config
        warnings = validate_config(config)
        if warnings:
            for w in warnings:
                st.warning(f"⚠️ {w}")
        else:
            st.success("✅ Configuration is valid")
    except ImportError:
        st.info("Config validator not available")
    except Exception as e:
        st.error(f"Validation error: {e}")
