"""
Scene Creator — guided wizard for scaffolding new CosySim scenes.

Creates a complete scene directory structure with:
- {name}_scene.py extending BaseScene
- templates/{name}_ui.html
- static/js/{name}.js and static/css/{name}.css
- __init__.py

Launched from the admin panel or hub.
"""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
import os
os.chdir(project_root)

from engine.assets import AssetManager
from engine.config import ConfigManager

# ── Streamlit page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="CosySim Scene Creator",
    page_icon="🎨",
    layout="wide",
)

from content.shared.streamlit_theme import inject_dark_theme
inject_dark_theme()

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem; font-weight: bold;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
    }
    .step-card {
        background: #1e1e2e; border-radius: 12px; padding: 1.5rem;
        border-left: 4px solid #667eea; margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Templates ──────────────────────────────────────────────────────────

_TEMPLATES = {
    "blank": {
        "label": "🗂️ Blank Scene",
        "description": "Minimal BaseScene with /api/health and one HTML page.",
        "characters": 0,
    },
    "chat": {
        "label": "💬 Chat Scene",
        "description": "Single-character chat interface (like phone, but simpler).",
        "characters": 1,
    },
    "multi_agent": {
        "label": "👥 Multi-Agent Scene",
        "description": "Two or more characters with AgentLoop (like bedroom).",
        "characters": 2,
    },
    "dashboard": {
        "label": "📊 Dashboard Scene",
        "description": "Streamlit-based data viewer / diagnostic panel.",
        "characters": 0,
    },
}


def init_state():
    if "asset_manager" not in st.session_state:
        st.session_state.asset_manager = AssetManager()
    if "config" not in st.session_state:
        st.session_state.config = ConfigManager()
    for key, default in [
        ("sc_step", 0), ("sc_name", ""), ("sc_desc", ""),
        ("sc_template", "blank"), ("sc_port", 5560),
        ("sc_nsfw", False), ("sc_chars", []),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default


def main():
    init_state()

    st.markdown('<h1 class="main-header">🎨 Scene Creator</h1>', unsafe_allow_html=True)
    st.markdown("Create a new scene with guided steps. Files are scaffolded automatically.")
    st.markdown("---")

    step = st.session_state.sc_step

    # Progress bar
    steps = ["Name & Description", "Template", "Configuration", "Review & Create"]
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps)):
        status = "✅" if i < step else ("🔵" if i == step else "⬜")
        col.markdown(f"**{status} Step {i+1}:** {label}")

    st.markdown("---")

    if step == 0:
        _step_name()
    elif step == 1:
        _step_template()
    elif step == 2:
        _step_config()
    elif step == 3:
        _step_review()


def _step_name():
    st.subheader("Step 1: Name & Description")

    name = st.text_input("Scene Name (lowercase, no spaces)",
                         value=st.session_state.sc_name,
                         placeholder="my_scene")
    desc = st.text_area("Description",
                        value=st.session_state.sc_desc,
                        placeholder="A cool new scene for testing…")

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Next →", type="primary", disabled=not name.strip()):
            # Validate name
            clean = name.strip().lower().replace(" ", "_").replace("-", "_")
            if not clean.isidentifier():
                st.error("Name must be a valid Python identifier (letters, numbers, underscores)")
                return
            scenes_dir = project_root / "content" / "scenes" / clean
            if scenes_dir.exists():
                st.error(f"A scene named '{clean}' already exists!")
                return
            st.session_state.sc_name = clean
            st.session_state.sc_desc = desc.strip()
            st.session_state.sc_step = 1
            st.rerun()


def _step_template():
    st.subheader("Step 2: Choose Template")

    for key, tmpl in _TEMPLATES.items():
        selected = st.session_state.sc_template == key
        border = "3px solid #667eea" if selected else "1px solid #333"
        st.markdown(
            f'<div style="background:#1e1e2e;border:{border};border-radius:12px;'
            f'padding:1rem;margin-bottom:0.5rem;">'
            f'<b>{tmpl["label"]}</b><br>{tmpl["description"]}</div>',
            unsafe_allow_html=True,
        )
        if st.button(f"Select {tmpl['label']}", key=f"sel_{key}"):
            st.session_state.sc_template = key
            st.rerun()

    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        if st.button("← Back"):
            st.session_state.sc_step = 0
            st.rerun()
    with col2:
        if st.button("Next →", type="primary"):
            st.session_state.sc_step = 2
            st.rerun()


def _step_config():
    st.subheader("Step 3: Configuration")

    port = st.number_input("Port", 5000, 65535,
                           value=st.session_state.sc_port)
    nsfw = st.checkbox("NSFW Enabled", value=st.session_state.sc_nsfw)

    st.session_state.sc_port = port
    st.session_state.sc_nsfw = nsfw

    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        if st.button("← Back"):
            st.session_state.sc_step = 1
            st.rerun()
    with col2:
        if st.button("Next →", type="primary"):
            st.session_state.sc_step = 3
            st.rerun()


def _step_review():
    st.subheader("Step 4: Review & Create")

    name = st.session_state.sc_name
    tmpl = _TEMPLATES[st.session_state.sc_template]

    st.markdown(f"**Name:** `{name}`")
    st.markdown(f"**Description:** {st.session_state.sc_desc}")
    st.markdown(f"**Template:** {tmpl['label']}")
    st.markdown(f"**Port:** {st.session_state.sc_port}")
    st.markdown(f"**NSFW:** {'Yes' if st.session_state.sc_nsfw else 'No'}")

    st.markdown("---")
    st.markdown("**Files to be created:**")
    base = f"content/scenes/{name}/"
    files = [
        f"{base}__init__.py",
        f"{base}{name}_scene.py",
        f"{base}templates/{name}_ui.html",
        f"{base}static/js/{name}.js",
        f"{base}static/css/{name}.css",
    ]
    for f in files:
        st.markdown(f"- `{f}`")

    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        if st.button("← Back"):
            st.session_state.sc_step = 2
            st.rerun()
    with col2:
        if st.button("🚀 Create Scene", type="primary"):
            try:
                _scaffold_scene(name, st.session_state.sc_template,
                                st.session_state.sc_desc, st.session_state.sc_port,
                                st.session_state.sc_nsfw)
                st.success(f"✅ Scene '{name}' created!")
                st.balloons()
                st.markdown(f"Launch with: `python launcher.py --mode {name}`")
                # Reset wizard
                st.session_state.sc_step = 0
            except Exception as e:
                st.error(f"Creation failed: {e}")


# ── Scaffold ───────────────────────────────────────────────────────────

def _scaffold_scene(name: str, template: str, desc: str, port: int, nsfw: bool):
    """Create all files for a new scene."""
    scene_dir = project_root / "content" / "scenes" / name
    tmpl_dir = scene_dir / "templates"
    js_dir = scene_dir / "static" / "js"
    css_dir = scene_dir / "static" / "css"

    for d in [scene_dir, tmpl_dir, js_dir, css_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # __init__.py
    (scene_dir / "__init__.py").write_text(f'"""Scene: {name}"""\n', encoding="utf-8")

    # Scene class
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Scene"
    is_flask = template in ("blank", "chat", "multi_agent")

    if is_flask:
        scene_code = _flask_scene_template(name, class_name, desc, port, nsfw, template)
    else:
        scene_code = _streamlit_scene_template(name, class_name, desc, port)

    (scene_dir / f"{name}_scene.py").write_text(scene_code, encoding="utf-8")

    # HTML
    html = _html_template(name, class_name)
    (tmpl_dir / f"{name}_ui.html").write_text(html, encoding="utf-8")

    # JS
    js = _js_template(name)
    (js_dir / f"{name}.js").write_text(js, encoding="utf-8")

    # CSS
    css = _css_template(name)
    (css_dir / f"{name}.css").write_text(css, encoding="utf-8")


def _flask_scene_template(name, cls, desc, port, nsfw, template):
    return f'''"""
{cls} — {desc}

Auto-generated by Scene Creator.
"""
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, render_template, jsonify, send_from_directory
from engine.scenes.base_scene import BaseScene
from engine.config import get_config


class {cls}(BaseScene):
    """{desc}"""

    def __init__(self):
        super().__init__("{name}", port={port})
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        self._setup_routes()
        self.register_health_route(self.app)

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return render_template("{name}_ui.html")

        @self.app.route("/api/status")
        def status():
            return jsonify({{"scene": "{name}", "status": "ok"}})

    def start(self):
        config = get_config()
        host = config.get("scenes.{name}.host", "0.0.0.0")
        port = config.get("scenes.{name}.port", {port})
        self.app.run(host=host, port=port, debug=True, use_reloader=False)

    def stop(self):
        pass

    def get_plugin_info(self):
        return {{
            "name": "{name}",
            "description": "{desc}",
            "version": "1.0.0",
            "author": "CosySim",
            "port": {port},
            "tags": ["{name}"],
            "skill_packs": [],
            "routes": [
                {{"path": "/", "methods": ["GET"], "description": "Main UI"}},
                {{"path": "/api/status", "methods": ["GET"], "description": "Status"}},
                {{"path": "/api/health", "methods": ["GET"], "description": "Health check"}},
            ],
        }}


if __name__ == "__main__":
    {cls}().start()
'''


def _streamlit_scene_template(name, cls, desc, port):
    return f'''"""
{cls} — {desc}

Auto-generated by Scene Creator (Streamlit dashboard template).
"""
import streamlit as st
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(page_title="{name}", page_icon="📊", layout="wide")

from content.shared.streamlit_theme import inject_dark_theme
inject_dark_theme()

st.header("{name}")
st.markdown("{desc}")
st.info("This is a scaffold. Add your dashboard logic here.")
'''


def _html_template(name, cls):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{cls}</title>
    <link rel="stylesheet" href="/static/css/{name}.css">
</head>
<body>
    <div id="app">
        <header>
            <h1>🎮 {cls}</h1>
            <p>Scene is running</p>
        </header>
        <main>
            <div id="content">
                <p>Add your scene content here.</p>
            </div>
        </main>
    </div>
    <script src="/static/js/{name}.js"></script>
</body>
</html>
'''


def _js_template(name):
    return f'''// {name} scene JavaScript
document.addEventListener("DOMContentLoaded", () => {{
    console.log("{name} scene loaded");

    // Health check
    fetch("/api/health")
        .then(r => r.json())
        .then(data => console.log("Health:", data))
        .catch(e => console.warn("Health check failed:", e));
}});
'''


def _css_template(name):
    return f'''/* {name} scene styles — CosySim dark theme */
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    background: #0a0a0f;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
}}

header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 2rem;
    text-align: center;
    color: white;
}}

header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
header p {{ opacity: 0.8; }}

main {{
    max-width: 1200px;
    margin: 2rem auto;
    padding: 0 1rem;
}}

#content {{
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    padding: 2rem;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
}}
'''


if __name__ == "__main__":
    main()
