"""Scene Template Generator — scaffolds new scene directories.

Creates the standard directory structure and boilerplate files for a new
CosySim scene, ready to be registered in the control-plane registry.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENES_DIR = PROJECT_ROOT / "content" / "scenes"

_SCENE_PY_TEMPLATE = '''\
"""
{display_name} — CosySim Scene
{"=" * (len(display_name) + len(" — CosySim Scene"))}
Port {port}, accent {accent}.

Usage:
    python launcher.py {name}
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, render_template
from engine.scenes.base_scene import BaseScene
from content.shared import register_shared_assets
from engine.port_registry import get_port

logger = logging.getLogger(__name__)

SCENE_ID = "{name}"
DEFAULT_PORT = get_port(SCENE_ID, {port})

_SCENE_DIR = Path(__file__).parent


class {class_name}(BaseScene):
    """{display_name} scene."""

    SCENE_METADATA = {{
        "name": SCENE_ID,
        "display_name": "{display_name}",
        "port": DEFAULT_PORT,
        "type": "scene",
        "accent_color": "{accent}",
        "description": "{description}",
    }}

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self.app = Flask(
            __name__,
            template_folder=str(_SCENE_DIR / "templates"),
            static_folder=str(_SCENE_DIR / "static"),
            static_url_path=f"/{SCENE_ID}/static",
        )
        register_shared_assets(self.app)
        self.register_health_route(self.app)
        self.register_hud_route(self.app)
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.route("/")
        def index():
            return render_template(
                "{name}.html",
                **self.inject_navbar_context(),
            )

    def start(self) -> None:
        logger.info("{display_name} opening on %s:%d", self.host, self.port)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
'''

_HTML_TEMPLATE = '''\
{{% extends "neon_base.html" %}}

{{% block title %}}{display_name}{{% endblock %}}

{{% block scene_accent %}}
<style>
  :root {{
    --cs-scene-accent: {accent};
    --cs-scene-glow: {accent}59;
  }}
</style>
{{% endblock %}}

{{% block content %}}
<div class="{name}-scene" data-scene="{name}">
  <h1>{display_name}</h1>
  <p>Scene is online.</p>
</div>
{{% endblock %}}
'''

_JS_TEMPLATE = '''\
/**
 * {name}.js — {display_name} scene controller
 */
'use strict';

document.addEventListener('DOMContentLoaded', () => {{
  console.log('[{display_name}] Scene loaded');
}});
'''

_CSS_TEMPLATE = '''\
/* {name}.css — {display_name} scene styles */

.{name}-scene {{
  padding: var(--cs-space-xl, 24px);
  color: var(--cs-text-primary, #e5e7eb);
}}
'''


def create_scene(
    name: str,
    display_name: Optional[str] = None,
    port: int = 5590,
    accent: str = "#00e5ff",
    description: str = "",
    template: str = "basic",
) -> Path:
    """Scaffold a new scene directory with boilerplate files.

    Args:
        name: Machine name (snake_case, e.g. ``"my_scene"``).
        display_name: Human-readable name. Defaults to title-cased *name*.
        port: Default port assignment.
        accent: CSS accent colour hex.
        description: Short scene description.
        template: Template variant (currently only ``"basic"``).

    Returns:
        Path to the created scene directory.

    Raises:
        FileExistsError: If the scene directory already exists.
    """
    scene_dir = SCENES_DIR / name
    if scene_dir.exists():
        raise FileExistsError(f"Scene directory already exists: {scene_dir}")

    display_name = display_name or name.replace("_", " ").title()
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Scene"

    ctx = {
        "name": name,
        "display_name": display_name,
        "class_name": class_name,
        "port": port,
        "accent": accent,
        "description": description or f"{display_name} scene",
    }

    # Create directory structure
    (scene_dir / "templates").mkdir(parents=True, exist_ok=True)
    (scene_dir / "static").mkdir(parents=True, exist_ok=True)

    # Write files
    (scene_dir / "__init__.py").write_text("", encoding="utf-8")
    (scene_dir / f"{name}_scene.py").write_text(
        _SCENE_PY_TEMPLATE.format(**ctx), encoding="utf-8"
    )
    (scene_dir / "templates" / f"{name}.html").write_text(
        _HTML_TEMPLATE.format(**ctx), encoding="utf-8"
    )
    (scene_dir / "static" / f"{name}.js").write_text(
        _JS_TEMPLATE.format(**ctx), encoding="utf-8"
    )
    (scene_dir / "static" / f"{name}.css").write_text(
        _CSS_TEMPLATE.format(**ctx), encoding="utf-8"
    )

    logger.info("Scaffolded scene '%s' at %s", name, scene_dir)
    return scene_dir
