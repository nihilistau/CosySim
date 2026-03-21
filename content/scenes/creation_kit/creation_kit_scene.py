"""
Creation Kit — Visual Scene Editor
====================================

Drag-and-drop scene construction tool. Visual editor for building CosySim
scenes from the shared component library without hand-coding HTML/JS/CSS.

Components are defined in ``engine.creation.component_registry``.
Layouts are saved as JSON and exported to working scene directories.

Version: v1.48.0 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.48.0 [2026-03-21] — v2: nested layouts, 10 new components, live
                            preview, drag reorder, export helpers
    v1.47.0 [2026-03-21] — Initial Creation Kit: visual editor, component
                            palette, property inspector, layout save/load,
                            HTML export pipeline
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from engine.scenes.base_scene import BaseScene
from engine.port_registry import get_port
from engine.creation.component_registry import (
    CATEGORIES,
    get_categories,
    get_component,
    get_component_count,
    list_components,
    list_components_by_category,
)
from engine.creation.scene_template import create_scene
from content.shared import register_shared_assets

logger = logging.getLogger(__name__)

SCENE_ID = "creation_kit"
DEFAULT_PORT = get_port(SCENE_ID, 5592)

_SCENE_DIR = Path(__file__).parent
_DATA_DIR = _SCENE_DIR / "data"
_LAYOUTS_DIR = _DATA_DIR / "layouts"


# ──── Layout Persistence ──────────────────────────────────────────────────

def _ensure_dirs() -> None:
    """Create data directories if missing."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _LAYOUTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_layout(layout_id: str, layout_data: Dict[str, Any]) -> Path:
    """Persist a layout to JSON file.

    Args:
        layout_id: Unique layout identifier.
        layout_data: Full layout dict (metadata + components).

    Returns:
        Path to the saved file.
    """
    _ensure_dirs()
    path = _LAYOUTS_DIR / f"{layout_id}.json"
    layout_data["updated_at"] = time.time()
    path.write_text(json.dumps(layout_data, indent=2), encoding="utf-8")
    logger.info("Layout saved: %s", path)
    return path


def _load_layout(layout_id: str) -> Optional[Dict[str, Any]]:
    """Load a layout from JSON file.

    Args:
        layout_id: Unique layout identifier.

    Returns:
        Layout dict, or None if not found.
    """
    path = _LAYOUTS_DIR / f"{layout_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_layouts() -> List[Dict[str, Any]]:
    """List all saved layouts with metadata.

    Returns:
        List of layout summary dicts.
    """
    _ensure_dirs()
    result = []
    for path in sorted(_LAYOUTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append({
                "id": path.stem,
                "name": data.get("name", path.stem),
                "description": data.get("description", ""),
                "scene_key": data.get("scene_key", ""),
                "accent_color": data.get("accent_color", "#06b6d4"),
                "component_count": len(data.get("components", [])),
                "updated_at": data.get("updated_at", 0),
            })
        except Exception as exc:
            logger.warning("Failed to read layout %s: %s", path, exc)
    return result


# ──── HTML Export Engine ──────────────────────────────────────────────────
# CONNECTS: component_registry templates, scene_template.py
# CALLED BY: /api/creation-kit/export route
# EMITS: Scene directory with HTML/CSS/JS/Python

def _export_component_html(comp: Dict[str, Any]) -> str:
    """Render a single component instance to HTML.

    Args:
        comp: Component instance with type + props.

    Returns:
        HTML string.
    """
    comp_def = get_component(comp.get("type", ""))
    if not comp_def:
        return f'<!-- Unknown component: {comp.get("type", "?")} -->'

    template = comp_def["html_template"]
    props = {**comp_def["default_props"], **comp.get("props", {})}

    # Handle computed props
    if "pct" not in props and "value" in props and "max_value" in props:
        max_v = max(1, props.get("max_value", 100))
        props["pct"] = round((props.get("value", 0) / max_v) * 100)

    if "variant_cls" not in props:
        variant = props.get("variant", "default")
        props["variant_cls"] = f" cs-glass-panel--{variant}" if variant != "default" else ""

    if "status_cls" not in props:
        status = props.get("status", "online")
        props["status_cls"] = f" cs-portrait-frame--{status}" if status != "online" else ""

    if "id_attr" not in props:
        btn_id = props.get("btn_id", "")
        props["id_attr"] = f' id="{btn_id}"' if btn_id else ""

    # Slots — render children
    for slot in comp_def.get("slots", []):
        slot_key = f"slot_{slot}"
        children = comp.get("children", {}).get(slot, [])
        if children:
            props[slot_key] = "\n".join(_export_component_html(c) for c in children)
        else:
            props[slot_key] = ""

    # Inventory slots helper
    if "inv_slots" not in props and comp.get("type") == "inventory_grid":
        count = int(props.get("slots", 12))
        props["inv_slots"] = "\n".join(
            '  <div class="inv-slot empty"></div>' for _ in range(count)
        )

    # Tab buttons helper
    if "tab_buttons" not in props and comp.get("type") == "tab_bar":
        tabs = [t.strip() for t in props.get("tabs", "").split(",")]
        active = int(props.get("active_tab", 0))
        props["tab_buttons"] = "\n".join(
            f'  <button class="mission-tab{" active" if i == active else ""}">{t}</button>'
            for i, t in enumerate(tabs)
        )

    # Faction rows helper
    if "faction_rows" not in props and comp.get("type") == "faction_bars":
        rows = []
        for entry in props.get("factions", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                name, color, power = parts
                rows.append(
                    f'  <div class="faction-row" data-faction="{name}">\n'
                    f'    <span class="faction-name" style="color:{color}">{name}</span>\n'
                    f'    <div class="faction-bar-track">\n'
                    f'      <div class="faction-bar-fill" style="width:{power}%;background:{color}"></div>\n'
                    f'    </div>\n'
                    f'    <span class="faction-power">{power}</span>\n'
                    f'  </div>'
                )
        props["faction_rows"] = "\n".join(rows)

    # Clock/credits helpers
    if comp.get("type") == "scene_header":
        props["clock_html"] = (
            '<div class="header-center">\n'
            '  <div class="world-clock" id="world-clock">\n'
            '    <span id="clock-display">LOADING...</span>\n'
            '  </div>\n'
            '</div>'
        ) if props.get("show_clock") else ""
        props["credits_html"] = (
            '<div class="header-right">\n'
            '  <div class="credit-display">\n'
            '    <span class="credit-icon">&#8354;</span>\n'
            '    <span id="credit-balance">&mdash;</span>\n'
            '  </div>\n'
            '</div>'
        ) if props.get("show_credits") else ""

    # Column slots
    if comp.get("type") == "column_layout":
        cols = int(props.get("columns", 3))
        col_htmls = []
        for i in range(1, cols + 1):
            slot_key = f"slot_col_{i}"
            children = comp.get("children", {}).get(f"col_{i}", [])
            if children:
                col_html = "\n".join(_export_component_html(c) for c in children)
            else:
                col_html = ""
            col_htmls.append(f'  <div class="ck-col">{col_html}</div>')
        props["slot_columns"] = "\n".join(col_htmls)

    # v1.48.0 — Economy panel helpers
    if comp.get("type") == "economy_panel":
        props["intel_html"] = (
            '<div class="intel-buy">\n'
            '  <div class="intel-row">\n'
            '    <input type="text" class="intel-input" placeholder="Topic">\n'
            '    <input type="number" class="intel-cost-input" value="50" min="10">\n'
            '    <button class="cs-glass-btn cs-glass-btn--accent">BUY INTEL</button>\n'
            '  </div>\n'
            '</div>'
        ) if props.get("show_intel") else ""
        props["exchange_html"] = (
            '<div class="exchange-row">\n'
            '  <input type="number" class="exchange-input" value="100" min="1">\n'
            '  <select class="exchange-dir">\n'
            '    <option value="in">Deposit</option>\n'
            '    <option value="out">Withdraw</option>\n'
            '  </select>\n'
            '  <button class="cs-glass-btn">EXCHANGE</button>\n'
            '</div>'
        ) if props.get("show_exchange") else ""

    # Progress tracker steps
    if comp.get("type") == "progress_tracker":
        steps = [s.strip() for s in props.get("steps", "").split(",")]
        current = int(props.get("current_step", 0))
        items = []
        for i, step in enumerate(steps):
            cls = "done" if i < current else ("active" if i == current else "")
            items.append(
                f'  <div class="ck-progress-step {cls}">'
                f'<span class="ck-step-dot"></span>{step}</div>'
            )
        props["step_items"] = "\n".join(items)

    # Alert banner dismiss button
    if comp.get("type") == "alert_banner":
        props["dismiss_btn"] = (
            '<button class="ck-alert__dismiss" '
            'onclick="this.parentElement.style.display=\'none\'">&#10005;</button>'
        ) if props.get("dismissible") else ""

    # Data table header + body
    if comp.get("type") == "data_table":
        cols = [c.strip() for c in props.get("columns", "").split(",")]
        props["header_cells"] = "".join(f"<th>{c}</th>" for c in cols)
        rows = int(props.get("rows", 5))
        props["body_rows"] = "\n".join(
            "    <tr>" + "".join(f"<td>&mdash;</td>" for _ in cols) + "</tr>"
            for _ in range(rows)
        )

    # Image display helpers
    if comp.get("type") == "image_display":
        glow = props.get("glow_color", "")
        props["glow_style"] = f";box-shadow:0 0 16px {glow}" if glow else ""
        caption = props.get("caption", "")
        props["caption_html"] = (
            f'  <figcaption style="font-size:0.7rem;color:#888;margin-top:4px;'
            f'text-align:center">{caption}</figcaption>'
        ) if caption else ""

    # v1.49.0 — Canvas widget overlay
    if comp.get("type") == "canvas_widget":
        children = comp.get("children", {}).get("overlay_content", [])
        if props.get("overlay") and children:
            overlay_inner = "\n".join(_export_component_html(c) for c in children)
            props["overlay_html"] = (
                f'<div class="ck-canvas-overlay">{overlay_inner}</div>'
            )
        elif props.get("overlay"):
            props["overlay_html"] = '<div class="ck-canvas-overlay"></div>'
        else:
            props["overlay_html"] = ""

    # HUD badge row
    if comp.get("type") == "hud_badge_row":
        items = []
        for entry in props.get("badges", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                bid, val, icon = parts[0], parts[1], parts[2]
                items.append(
                    f'  <span class="ck-hud-badge" id="badge-{bid}">'
                    f'{icon} <span id="badge-val-{bid}">{val}</span></span>'
                )
        props["badge_items"] = "\n".join(items)

    # NPC roster cards
    if comp.get("type") == "npc_roster":
        cards = []
        for entry in props.get("npcs", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                name, role, color = parts[0], parts[1], parts[2]
                npc_id = name.lower().replace(" ", "_")
                cards.append(
                    f'  <div class="ck-npc-card" data-npc="{npc_id}" '
                    f'style="--npc-color:{color}">\n'
                    f'    <div class="ck-npc-name">{name}</div>\n'
                    f'    <div class="ck-npc-role">{role}</div>\n'
                    f'    <div class="cs-stat-bar cs-stat-bar--thick">\n'
                    f'      <div class="cs-stat-bar__track">\n'
                    f'        <div class="cs-stat-bar__fill" id="rep-{npc_id}" '
                    f'style="width:50%;background:{color}"></div>\n'
                    f'      </div>\n'
                    f'    </div>\n'
                    f'  </div>'
                )
        props["npc_cards"] = "\n".join(cards)

    # Button group
    if comp.get("type") == "button_group":
        items = []
        for entry in props.get("buttons", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                text, variant, bid = parts[0], parts[1], parts[2]
                items.append(
                    f'  <button class="cs-glass-btn cs-glass-btn--{variant}" '
                    f'id="{bid}">{text}</button>'
                )
        props["button_items"] = "\n".join(items)

    # Select dropdown options
    if comp.get("type") == "select_dropdown":
        opts = [o.strip() for o in props.get("options", "").split(",")]
        props["option_items"] = "\n".join(
            f'    <option value="{o}">{o}</option>' for o in opts
        )

    # Text block heading
    if comp.get("type") == "text_block":
        heading = props.get("heading", "")
        props["heading_html"] = f'<h3 class="ck-text-heading">{heading}</h3>' if heading else ""

    # Render template with safe formatting
    try:
        return template.format(**props)
    except KeyError as exc:
        logger.warning("Template render failed for %s: missing %s", comp.get("type"), exc)
        return f'<!-- Render error: {comp.get("type")} missing {exc} -->'


def export_layout_html(layout: Dict[str, Any]) -> str:
    """Export a full layout to a scene HTML template body.

    Args:
        layout: Full layout dict with components list.

    Returns:
        HTML string for the scene_content block.
    """
    components = layout.get("components", [])
    html_parts = []
    for comp in components:
        html_parts.append(_export_component_html(comp))
    return "\n\n".join(html_parts)


def export_full_template(layout: Dict[str, Any]) -> str:
    """Export a complete Jinja2 template that extends neon_base.html.

    Args:
        layout: Full layout dict.

    Returns:
        Complete Jinja2 template string.
    """
    scene_key = layout.get("scene_key", "custom_scene")
    display_name = layout.get("name", "Custom Scene").upper()
    accent = layout.get("accent_color", "#06b6d4")

    # Compute accent RGB from hex
    hex_clean = accent.lstrip("#")
    try:
        r, g, b = int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)
        accent_rgb = f"{r} {g} {b}"
    except (ValueError, IndexError):
        accent_rgb = "6 182 212"

    body_html = export_layout_html(layout)
    desc = layout.get("description", "")

    return (
        f"{{% extends 'neon_base.html' %}}\n"
        f"{{% set scene_key = '{scene_key}' %}}\n"
        f"{{% set scene_display_name = '{display_name}' %}}\n"
        f"{{% set scene_accent = '{accent}' %}}\n"
        f"{{% set scene_accent_rgb = '{accent_rgb}' %}}\n"
        f"\n"
        f"{{#\n"
        f"  {display_name} — CosySim Scene\n"
        f"  {'=' * (len(display_name) + len(' — CosySim Scene'))}\n"
        f"  {desc}\n"
        f"\n"
        f"  Generated by Creation Kit v1.47\n"
        f"  Version: v1.47.0 [2026-03-21]\n"
        f"#}}\n"
        f"\n"
        f"{{% block head_css %}}\n"
        f'  <link rel="stylesheet" href="{{{{ url_for(\'static\', filename=\'{scene_key}.css\') }}}}">\n'
        f"{{% endblock %}}\n"
        f"\n"
        f"{{% block scene_content %}}\n"
        f"{body_html}\n"
        f"{{% endblock %}}\n"
        f"\n"
        f"{{% block body_scripts %}}\n"
        f'  <script src="{{{{ url_for(\'static\', filename=\'{scene_key}.js\') }}}}" defer></script>\n'
        f"  <script src=\"/shared/js/cosysim-voice.js\"></script>\n"
        f"{{% endblock %}}\n"
    )


# ──── CSS Generation Engine ───────────────────────────────────────────────
# v1.49.0 [2026-03-21] — Generate scene-specific CSS from layout
# CONNECTS: accent color, component types used
# CALLED BY: export_scene route
# EMITS: CSS file content

def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 6, 182, 212  # fallback cyan


def _darken(r: int, g: int, b: int, factor: float = 0.6) -> str:
    """Darken an RGB color by factor."""
    return f"rgb({int(r*factor)},{int(g*factor)},{int(b*factor)})"


def _lighten(r: int, g: int, b: int, factor: float = 1.4) -> str:
    """Lighten an RGB color by factor."""
    return f"rgb({min(255,int(r*factor))},{min(255,int(g*factor))},{min(255,int(b*factor))})"


def _collect_types(components: List[Dict[str, Any]]) -> set:
    """Collect all component types used in a layout (including nested)."""
    types = set()
    for comp in components:
        types.add(comp.get("type", ""))
        if comp.get("children"):
            for slot_children in comp["children"].values():
                types |= _collect_types(slot_children)
    return types


def _collect_ids(components: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Collect all element IDs from component props."""
    ids = []
    for comp in components:
        props = comp.get("props", {})
        comp_type = comp.get("type", "")
        for key, val in props.items():
            if key.endswith("_id") and isinstance(val, str) and val:
                ids.append({"id": val, "type": comp_type, "prop": key})
        if comp.get("children"):
            for slot_children in comp["children"].values():
                ids.extend(_collect_ids(slot_children))
    return ids


def export_scene_css(layout: Dict[str, Any]) -> str:
    """Generate scene-specific CSS from layout configuration.

    Derives a full color palette from the accent color and generates
    styles for all CK-prefixed components used in the layout.

    Args:
        layout: Full layout dict.

    Returns:
        CSS file content string.
    """
    accent = layout.get("accent_color", "#06b6d4")
    scene_key = layout.get("scene_key", "scene")
    name = layout.get("name", "Scene")
    r, g, b = _hex_to_rgb(accent)

    types = _collect_types(layout.get("components", []))

    css = f"""/* ============================================================
   {name} — Scene Styles
   Generated by Creation Kit v1.49
   Accent: {accent}

   Version: v1.49.0 [2026-03-21]
   ============================================================ */

/* ── Scene palette (derived from accent {accent}) ──────── */
:root {{
  --scene-accent: {accent};
  --scene-accent-rgb: {r} {g} {b};
  --scene-accent-dim: {_darken(r, g, b, 0.65)};
  --scene-accent-light: {_lighten(r, g, b, 1.3)};
  --scene-accent-faint: rgba({r},{g},{b},0.08);
  --scene-accent-glow: rgba({r},{g},{b},0.25);
  --scene-accent-border: rgba({r},{g},{b},0.3);
  --scene-bg: #0a0a0f;
  --scene-panel: #10101a;
  --scene-border: #1a1a2e;
  --scene-text: #c8ccd8;
  --scene-muted: #4a5068;
}}

"""

    # Component-specific CSS — only for types actually used
    if "ck-alert" in str(types) or "alert_banner" in types:
        css += """/* ── Alert banners ──────────────────────────────────────── */
.ck-alert {
  padding: 8px 14px;
  border-radius: 4px;
  font-size: 0.78rem;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
}
.ck-alert--info    { background: rgba(59,130,246,0.08); border-left: 3px solid #3b82f6; color: #93bbfc; }
.ck-alert--warning { background: rgba(245,158,11,0.08); border-left: 3px solid #f59e0b; color: #fcd68d; }
.ck-alert--danger  { background: rgba(239,68,68,0.08);  border-left: 3px solid #ef4444; color: #fca5a5; }
.ck-alert--success { background: rgba(34,197,94,0.08);  border-left: 3px solid #22c55e; color: #86efac; }
.ck-alert__dismiss {
  background: none; border: none; color: inherit; cursor: pointer;
  opacity: 0.5; font-size: 1rem; margin-left: auto;
}
.ck-alert__dismiss:hover { opacity: 1; }

"""

    if "hud_badge_row" in types:
        css += f"""/* ── HUD badge row ─────────────────────────────────────── */
.ck-hud-badges {{
  display: flex;
  gap: 12px;
  padding: 6px 12px;
  background: rgba({r},{g},{b},0.04);
  border: 1px solid rgba({r},{g},{b},0.12);
  border-radius: 4px;
  margin: 6px 0;
}}
.ck-hud-badge {{
  font-size: 0.78rem;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--scene-text);
}}
.ck-hud-badge span {{ font-weight: 600; color: var(--scene-accent); }}

"""

    if "toast_container" in types:
        css += """/* ── Toast notifications ───────────────────────────────── */
.ck-toast-container {
  position: fixed;
  z-index: 9000;
  display: flex;
  flex-direction: column;
  gap: 6px;
  pointer-events: none;
}
.ck-toast--top-right    { top: 80px; right: 20px; align-items: flex-end; }
.ck-toast--top-center   { top: 80px; left: 50%; transform: translateX(-50%); align-items: center; }
.ck-toast--bottom-right { bottom: 20px; right: 20px; align-items: flex-end; }
.ck-toast--bottom-center{ bottom: 20px; left: 50%; transform: translateX(-50%); align-items: center; }
.ck-toast {
  padding: 8px 16px;
  background: rgba(0,0,0,0.9);
  border: 1px solid var(--scene-accent-border);
  border-radius: 6px;
  font-size: 0.78rem;
  color: var(--scene-text);
  pointer-events: all;
  animation: ck-toast-in 0.3s ease-out;
}
@keyframes ck-toast-in { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }

"""

    if "npc_roster" in types:
        css += """/* ── NPC roster ────────────────────────────────────────── */
.ck-npc-roster {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}
.ck-npc-card {
  padding: 10px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--scene-border);
  border-left: 3px solid var(--npc-color, var(--scene-accent));
  border-radius: 4px;
  text-align: center;
}
.ck-npc-name { font-weight: 600; font-size: 0.8rem; color: var(--npc-color, var(--scene-accent)); }
.ck-npc-role { font-size: 0.65rem; color: var(--scene-muted); margin: 2px 0 6px; }

"""

    if "progress_tracker" in types:
        css += f"""/* ── Progress tracker ──────────────────────────────────── */
.ck-progress-tracker {{
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 8px 0;
}}
.ck-progress-step {{
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  color: var(--scene-muted);
  flex: 1;
}}
.ck-progress-step.active {{ color: var(--scene-accent); font-weight: 600; }}
.ck-progress-step.done {{ color: rgba({r},{g},{b},0.5); }}
.ck-step-dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--scene-border);
  flex-shrink: 0;
}}
.ck-progress-step.active .ck-step-dot {{ background: var(--scene-accent); box-shadow: 0 0 6px var(--scene-accent); }}
.ck-progress-step.done .ck-step-dot {{ background: rgba({r},{g},{b},0.4); }}

"""

    if "data_table" in types:
        css += """/* ── Data table ────────────────────────────────────────── */
.ck-table-wrap { overflow-x: auto; margin: 6px 0; }
.ck-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.ck-table th {
  text-align: left;
  padding: 6px 10px;
  background: rgba(255,255,255,0.03);
  color: var(--scene-accent);
  font-size: 0.65rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  border-bottom: 1px solid var(--scene-border);
}
.ck-table td {
  padding: 5px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  color: var(--scene-text);
}
.ck-table tr:hover td { background: rgba(255,255,255,0.02); }

"""

    if "canvas_widget" in types:
        css += """/* ── Canvas widget ─────────────────────────────────────── */
.ck-canvas-widget { position: relative; }
.ck-canvas-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

"""

    if "button_group" in types:
        css += """/* ── Button group ──────────────────────────────────────── */
.ck-btn-group { display: flex; gap: 6px; flex-wrap: wrap; }
.ck-btn-group--vertical { flex-direction: column; }

"""

    if "select_dropdown" in types:
        css += """/* ── Select dropdown ───────────────────────────────────── */
.ck-select-field { margin: 6px 0; }
.ck-select-label {
  display: block;
  font-size: 0.65rem;
  color: var(--scene-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 3px;
}
.ck-select {
  width: 100%;
  padding: 6px 10px;
  background: var(--scene-panel);
  border: 1px solid var(--scene-border);
  border-radius: 4px;
  color: var(--scene-text);
  font-size: 0.78rem;
}

"""

    if "text_block" in types:
        css += """/* ── Text block ────────────────────────────────────────── */
.ck-text-block { margin: 8px 0; }
.ck-text-heading { font-size: 0.85rem; color: var(--scene-accent); margin-bottom: 4px; }
.ck-text-block p { font-size: 0.78rem; line-height: 1.6; color: var(--scene-text); }
.ck-text--narrative p { font-style: italic; color: rgba(200,204,216,0.7); }
.ck-text--system p { font-family: var(--cs-mono, monospace); font-size: 0.7rem; color: var(--scene-muted); }
.ck-text--emphasis p { font-weight: 600; color: var(--scene-accent); }

"""

    if "timer_display" in types:
        css += f"""/* ── Timer display ─────────────────────────────────────── */
.ck-timer {{ display: flex; align-items: center; gap: 6px; }}
.ck-timer__label {{ font-size: 0.6rem; color: var(--scene-muted); text-transform: uppercase; letter-spacing: 1px; }}
.ck-timer__value {{ font-weight: 700; color: var(--scene-accent); }}
.ck-timer--badge {{
  padding: 3px 10px;
  background: rgba({r},{g},{b},0.08);
  border: 1px solid rgba({r},{g},{b},0.2);
  border-radius: 4px;
}}
.ck-timer--large .ck-timer__value {{ font-size: 1.6rem; }}
.ck-timer--countdown .ck-timer__value {{ font-family: var(--cs-mono, monospace); }}

"""

    if "image_display" in types:
        css += """/* ── Image display ─────────────────────────────────────── */
.ck-image { margin: 8px 0; }
.ck-image img { display: block; }

"""

    # Always include scrollbar
    css += """/* ── Scrollbar ─────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-thumb { background: var(--scene-border); border-radius: 2px; }

/* ── Responsive ───────────────────────────────────────── */
@media (max-width: 900px) {
  .ck-columns { grid-template-columns: 1fr 1fr !important; }
}
@media (max-width: 600px) {
  .ck-columns { grid-template-columns: 1fr !important; }
}
"""

    return css


# ──── JS Generation Engine ────────────────────────────────────────────────
# v1.49.0 [2026-03-21] — Generate scene-specific JS from layout
# CONNECTS: component IDs, Socket.IO, stat bars, chat logs, buttons
# CALLED BY: export_scene route
# EMITS: JS file content

def export_scene_js(layout: Dict[str, Any]) -> str:
    """Generate scene-specific JavaScript from layout configuration.

    Creates Socket.IO connection, element bindings, stat bar updaters,
    chat log handlers, button wiring, toast system, and lifecycle.

    Args:
        layout: Full layout dict.

    Returns:
        JS file content string.
    """
    scene_key = layout.get("scene_key", "scene")
    name = layout.get("name", "Scene")
    components = layout.get("components", [])
    types = _collect_types(components)
    ids = _collect_ids(components)

    # Collect stat bar IDs
    stat_ids = [i for i in ids if i["type"] == "stat_bar" and i["prop"] == "stat_id"]
    # Collect chat log IDs
    chat_ids = [i for i in ids if i["type"] == "chat_log" and i["prop"] == "chat_id"]
    chat_input_ids = [i for i in ids if i["type"] == "chat_log" and i["prop"] == "input_id"]
    # Collect button IDs
    btn_ids = [i for i in ids if i["type"] == "button" and i["prop"] == "btn_id" and i["id"]]
    # Collect button_group buttons
    btn_group_buttons = []
    for comp in _flatten_components(components):
        if comp.get("type") == "button_group":
            for entry in comp.get("props", {}).get("buttons", "").split(","):
                parts = entry.strip().split(":")
                if len(parts) >= 3:
                    btn_group_buttons.append({"text": parts[0], "id": parts[2]})

    class_name = "".join(w.capitalize() for w in scene_key.split("_")) + "Scene"

    js = f"""/**
 * {name} — Scene Controller
 * Generated by Creation Kit v1.49
 *
 * Socket.IO connection, stat bar updaters, chat log, button wiring,
 * toast notifications, and scene lifecycle.
 *
 * Version: v1.49.0 [2026-03-21]
 * CONNECTS: Socket.IO, DOM elements
 * CALLED BY: DOMContentLoaded
 */
'use strict';

class {class_name} {{
  constructor() {{
    this.socket = null;
    this.state = null;
  }}

  // ── Lifecycle ───────────────────────────────────────────────────

  init() {{
    this._setupSocket();
    this._setupUI();
    this._loadInitialState();
  }}

  _setupSocket() {{
    this.socket = io();
    this.socket.on('connect', () => this._log('Connected to {name}', 'system'));
    this.socket.on('disconnect', () => this._log('Disconnected', 'system'));
    this.socket.on('state_update', (data) => this._applyState(data));
    this.socket.on('error', (data) => this._showToast(data.message || 'Error', 'danger'));
  }}

  _loadInitialState() {{
    fetch('/api/status')
      .then(r => r.ok ? r.json() : null)
      .then(data => {{ if (data) this._applyState(data); }})
      .catch(() => {{}});
  }}

  // ── State application ───────────────────────────────────────────

  _applyState(state) {{
    if (!state) return;
    this.state = state;
"""

    # Stat bar updaters
    for sid in stat_ids:
        bar_id = sid["id"]
        val_id = f"val-{bar_id}"
        js += f"""
    // Stat bar: {bar_id}
    if (state['{bar_id}'] !== undefined) {{
      const el = document.getElementById('{bar_id}');
      const valEl = document.getElementById('{val_id}');
      const max = state['{bar_id}_max'] || 100;
      const pct = Math.round((state['{bar_id}'] / max) * 100);
      if (el) el.style.width = pct + '%';
      if (valEl) valEl.textContent = state['{bar_id}'];
    }}
"""

    # HUD badge updaters
    if "hud_badge_row" in types:
        js += """
    // HUD badge updates
    document.querySelectorAll('.ck-hud-badge span').forEach(el => {
      const key = el.id?.replace('badge-val-', '');
      if (key && state[key] !== undefined) el.textContent = state[key];
    });
"""

    js += "  }\n\n"

    # UI setup — wire buttons
    js += "  // ── UI wiring ──────────────────────────────────────────────────\n\n"
    js += "  _setupUI() {\n"

    for btn in btn_ids:
        bid = btn["id"]
        # Map drink buttons to drink action
        if bid.startswith("drink-"):
            drink = bid.replace("drink-", "")
            js += f"    document.getElementById('{bid}')?.addEventListener('click', () => this._action('order_drink', {{drink: '{drink}'}}));\n"
        elif bid.startswith("btn-"):
            action = bid.replace("btn-", "")
            js += f"    document.getElementById('{bid}')?.addEventListener('click', () => this._action('{action}'));\n"

    for btn in btn_group_buttons:
        js += f"    document.getElementById('{btn['id']}')?.addEventListener('click', () => this._action('{btn['id']}'));\n"

    # Chat form submit
    for chat_input in chat_input_ids:
        cid = chat_input["id"]
        js += f"""
    // Chat input: {cid}
    const chatInput = document.getElementById('{cid}');
    if (chatInput) {{
      chatInput.addEventListener('keydown', (e) => {{
        if (e.key === 'Enter' && chatInput.value.trim()) {{
          this._sendMessage(chatInput.value.trim());
          chatInput.value = '';
        }}
      }});
    }}
    // Send button (sibling of input)
    chatInput?.parentElement?.querySelector('button')?.addEventListener('click', () => {{
      if (chatInput.value.trim()) {{
        this._sendMessage(chatInput.value.trim());
        chatInput.value = '';
      }}
    }});
"""

    js += "  }\n\n"

    # Action helper
    js += """  // ── Actions ──────────────────────────────────────────────────

  _action(action, data = {}) {
    if (this.socket) {
      this.socket.emit('action', { action, ...data });
      this._log(`Action: ${action}`, 'system');
    }
  }

  _sendMessage(text) {
    this._addChatLine(text, 'user');
    if (this.socket) {
      this.socket.emit('action', { action: 'message', text });
    }
  }

"""

    # Chat log helper
    if chat_ids:
        primary_chat = chat_ids[0]["id"]
        js += f"""  // ── Chat log ──────────────────────────────────────────────────

  _addChatLine(text, type = '') {{
    const feed = document.getElementById('{primary_chat}');
    if (!feed) return;
    const div = document.createElement('div');
    div.className = 'chat-entry ' + type;
    div.textContent = text;
    feed.appendChild(div);
    feed.scrollTop = feed.scrollHeight;
    while (feed.children.length > 80) feed.removeChild(feed.firstChild);
  }}

  _log(text, type) {{ this._addChatLine(text, type); }}

"""
    else:
        js += """  _addChatLine(text, type) { console.log(`[${type}] ${text}`); }
  _log(text, type) { this._addChatLine(text, type); }

"""

    # Toast system
    if "toast_container" in types:
        js += """  // ── Toast notifications ────────────────────────────────────

  _showToast(text, severity = 'info') {
    const container = document.querySelector('.ck-toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'ck-toast';
    toast.textContent = text;
    toast.style.borderLeftColor = severity === 'danger' ? '#ef4444' :
      severity === 'success' ? '#22c55e' : severity === 'warning' ? '#f59e0b' : 'var(--scene-accent)';
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

"""
    else:
        js += """  _showToast(text) { console.log('[toast]', text); }

"""

    # v1.49.2 [2026-03-22] — API-first data fetchers
    # Generate client-side fetch + render for data-driven components
    all_comps = _flatten_components(components)

    # Inventory grid → fetch + render
    inv_comps = [c for c in all_comps if c.get("type") == "inventory_grid"]
    if inv_comps:
        grid_id = inv_comps[0].get("props", {}).get("grid_id", "inventory-grid")
        js += f"""  // ── Inventory (API-first) ────────────────────────────────────

  async _loadInventory() {{
    try {{
      const res = await fetch('/api/inventory');
      const data = await res.json();
      this._renderInventory(data.items || []);
    }} catch {{}}
  }}

  _renderInventory(items) {{
    const el = document.getElementById('{grid_id}');
    if (!el) return;
    if (!items.length) {{ el.innerHTML = '<div class="inv-slot empty"></div>'.repeat(12); return; }}
    el.innerHTML = items.map(item =>
      `<div class="inv-slot" title="${{item.name}}" data-id="${{item.id}}">${{item.icon || item.name?.[0] || '?'}}</div>`
    ).join('');
  }}

"""

    # Event feed → fetch + render
    feed_comps = [c for c in all_comps if c.get("type") == "event_feed"]
    if feed_comps:
        feed_id = feed_comps[0].get("props", {}).get("feed_id", "events-list")
        js += f"""  // ── Event feed (API-first) ────────────────────────────────────

  async _loadEvents() {{
    try {{
      const res = await fetch('/api/world/events');
      const data = await res.json();
      this._renderEvents(data.events || []);
    }} catch {{}}
  }}

  _renderEvents(events) {{
    const el = document.getElementById('{feed_id}');
    if (!el) return;
    if (!events.length) {{ el.innerHTML = '<div class="event-item system">No active events.</div>'; return; }}
    el.innerHTML = events.map(ev =>
      `<div class="event-card ev-${{ev.event_type || 'unknown'}}">
        <div class="ev-title">${{ev.title || ev.description || '???'}}</div>
      </div>`
    ).join('');
  }}

"""

    # Faction bars → fetch + render
    faction_comps = [c for c in all_comps if c.get("type") == "faction_bars"]
    if faction_comps:
        js += """  // ── Faction bars (API-first) ──────────────────────────────────

  async _loadFactions() {
    try {
      const res = await fetch('/api/city/factions');
      const data = await res.json();
      const list = document.getElementById('faction-list');
      if (!list) return;
      list.innerHTML = Object.entries(data).map(([name, f]) =>
        `<div class="faction-row" data-faction="${name}">
          <span class="faction-name" style="color:${f.color}">${name}</span>
          <div class="faction-bar-track">
            <div class="faction-bar-fill" style="width:${f.power}%;background:${f.color}"></div>
          </div>
          <span class="faction-power">${Math.round(f.power)}</span>
        </div>`
      ).join('');
    } catch {}
  }

"""

    # NPC roster → fetch + render
    npc_comps = [c for c in all_comps if c.get("type") == "npc_roster"]
    if npc_comps:
        roster_id = npc_comps[0].get("props", {}).get("roster_id", "npc-roster")
        js += f"""  // ── NPC roster (API-first) ──────────────────────────────────

  async _loadNPCs() {{
    try {{
      const res = await fetch('/api/characters');
      const data = await res.json();
      const el = document.getElementById('{roster_id}');
      if (!el) return;
      const chars = data.characters || [];
      el.innerHTML = chars.map(c =>
        `<div class="ck-npc-card" data-npc="${{c.id}}" style="--npc-color:${{c.accent || 'var(--scene-accent)'}}">
          <div class="ck-npc-name">${{c.name}}</div>
          <div class="ck-npc-role">${{c.role || ''}}</div>
        </div>`
      ).join('') || '<div style="color:var(--scene-muted)">No NPCs present</div>';
    }} catch {{}}
  }}

"""

    # Mission board → fetch + render
    mission_comps = [c for c in all_comps if c.get("type") == "mission_board"]
    if mission_comps:
        board_id = mission_comps[0].get("props", {}).get("board_id", "mission-list")
        js += f"""  // ── Mission board (API-first) ───────────────────────────────

  async _loadMissions() {{
    try {{
      const res = await fetch('/api/missions');
      const data = await res.json();
      const el = document.getElementById('{board_id}');
      if (!el) return;
      const missions = [...(data.available || []), ...(data.active || [])];
      if (!missions.length) {{ el.innerHTML = '<div class="mission-empty">No missions available.</div>'; return; }}
      el.innerHTML = missions.map(m =>
        `<div class="mission-item" data-id="${{m.id}}">
          <span class="mission-type">${{m.type || 'MISSION'}}</span>
          <span class="mission-name">${{m.title || m.name}}</span>
        </div>`
      ).join('');
    }} catch {{}}
  }}

"""

    # Crew roster → fetch + render
    crew_comps = [c for c in all_comps if c.get("type") == "crew_roster"]
    if crew_comps:
        roster_id = crew_comps[0].get("props", {}).get("roster_id", "crew-roster")
        js += f"""  // ── Crew roster (API-first) ─────────────────────────────────

  async _loadCrew() {{
    try {{
      const res = await fetch('/api/crew');
      const data = await res.json();
      const el = document.getElementById('{roster_id}');
      if (!el) return;
      const members = data.members || [];
      if (!members.length) {{ el.innerHTML = '<div class="crew-empty">No crew recruited.</div>'; return; }}
      el.innerHTML = members.map(m =>
        `<div class="crew-member" data-id="${{m.id}}">
          <span class="crew-name">${{m.name}}</span>
          <span class="crew-role">${{m.role || ''}}</span>
        </div>`
      ).join('');
    }} catch {{}}
  }}

"""

    # Data table → fetch + render
    table_comps = [c for c in all_comps if c.get("type") == "data_table"]
    if table_comps:
        table_id = table_comps[0].get("props", {}).get("table_id", "data-table")
        js += f"""  // ── Data table (API-first) ──────────────────────────────────

  async _loadTableData(apiPath, columns) {{
    try {{
      const res = await fetch(apiPath);
      const data = await res.json();
      const table = document.getElementById('{table_id}');
      if (!table) return;
      const tbody = table.querySelector('tbody');
      if (!tbody) return;
      const rows = data.rows || data.items || [];
      tbody.innerHTML = rows.map(row =>
        '<tr>' + columns.map(col => `<td>${{row[col] ?? ''}}</td>`).join('') + '</tr>'
      ).join('');
    }} catch {{}}
  }}

"""

    # Add data loading calls to _loadInitialState
    load_calls = []
    if inv_comps:
        load_calls.append("this._loadInventory();")
    if feed_comps:
        load_calls.append("this._loadEvents();")
    if faction_comps:
        load_calls.append("this._loadFactions();")
    if npc_comps:
        load_calls.append("this._loadNPCs();")
    if mission_comps:
        load_calls.append("this._loadMissions();")
    if crew_comps:
        load_calls.append("this._loadCrew();")

    if load_calls:
        js += "  // ── Load all data on init ──────────────────────────────────\n\n"
        js += "  _loadAllData() {\n"
        for call in load_calls:
            js += f"    {call}\n"
        js += "  }\n\n"

    # Bootstrap — include _loadAllData in init
    init_extra = "\n    this._loadAllData();" if load_calls else ""

    js += f"""}}

// ── Bootstrap ───────────────────────────────────────────────────────
const SceneApp = new {class_name}();
document.addEventListener('DOMContentLoaded', () => {{
  SceneApp.init();{init_extra}
}});
"""

    return js


def _flatten_components(components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten nested component tree into a single list."""
    result = []
    for comp in components:
        result.append(comp)
        if comp.get("children"):
            for slot_children in comp["children"].values():
                result.extend(_flatten_components(slot_children))
    return result


# ──── Flask Scene ─────────────────────────────────────────────────────────

class CreationKitScene(BaseScene):
    """Creation Kit — visual scene editor.

    CONNECTS: component_registry, scene_template, asset_registry
    CALLED BY: launcher.py, TUI
    EMITS: REST API for editor UI
    """

    SCENE_METADATA = {
        "name": SCENE_ID,
        "display_name": "CREATION KIT",
        "port": DEFAULT_PORT,
        "type": "tool",
        "accent_color": "#f59e0b",
        "description": "Visual drag-and-drop scene editor.",
    }

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        super().__init__(scene_name=SCENE_ID, host=host, port=port)

        self.app = Flask(
            __name__,
            template_folder=str(_SCENE_DIR / "templates"),
            static_folder=str(_SCENE_DIR / "static"),
            static_url_path=f"/{SCENE_ID}/static",
        )
        CORS(self.app)
        register_shared_assets(self.app)
        self.register_health_route(self.app)
        self._setup_routes()

    # v1.47.0 [2026-03-21] — Creation Kit routes
    def _setup_routes(self) -> None:
        """Register all Flask HTTP routes."""

        @self.app.route("/")
        def index():
            return render_template("creation_kit.html")

        # ── Component catalogue ───────────────────────────────────────

        @self.app.route("/api/components")
        def api_components():
            """Return all components grouped by category."""
            return jsonify({
                "categories": get_categories(),
                "components": list_components_by_category(),
                "total": get_component_count(),
            })

        @self.app.route("/api/components/<comp_type>")
        def api_component_detail(comp_type: str):
            """Return a single component definition."""
            comp = get_component(comp_type)
            if not comp:
                return jsonify({"error": "Component not found"}), 404
            return jsonify(comp)

        # ── Layout CRUD ───────────────────────────────────────────────

        @self.app.route("/api/layouts")
        def api_list_layouts():
            """List all saved layouts."""
            return jsonify({"layouts": _list_layouts()})

        @self.app.route("/api/layouts/<layout_id>")
        def api_get_layout(layout_id: str):
            """Load a specific layout."""
            layout = _load_layout(layout_id)
            if not layout:
                return jsonify({"error": "Layout not found"}), 404
            return jsonify(layout)

        @self.app.route("/api/layouts", methods=["POST"])
        def api_save_layout():
            """Save a layout (create or update)."""
            data = request.get_json(force=True) or {}
            layout_id = data.get("id") or f"layout_{uuid.uuid4().hex[:8]}"
            data["id"] = layout_id
            _save_layout(layout_id, data)
            return jsonify({"ok": True, "id": layout_id})

        @self.app.route("/api/layouts/<layout_id>", methods=["DELETE"])
        def api_delete_layout(layout_id: str):
            """Delete a saved layout."""
            path = _LAYOUTS_DIR / f"{layout_id}.json"
            if path.exists():
                path.unlink()
                return jsonify({"ok": True})
            return jsonify({"error": "Not found"}), 404

        # ── Export ────────────────────────────────────────────────────

        @self.app.route("/api/export/preview", methods=["POST"])
        def api_export_preview():
            """Generate HTML preview from layout without saving to disk."""
            data = request.get_json(force=True) or {}
            try:
                html = export_full_template(data)
                return jsonify({"ok": True, "html": html})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @self.app.route("/api/export/scene", methods=["POST"])
        # v1.49.0 [2026-03-21] — Full scene factory: HTML + CSS + JS
        def api_export_scene():
            """Export layout to a full scene directory with HTML, CSS, and JS."""
            data = request.get_json(force=True) or {}
            scene_key = data.get("scene_key", "")
            if not scene_key or not scene_key.isidentifier():
                return jsonify({"ok": False, "error": "Invalid scene_key"}), 400

            try:
                # Generate all three files
                html = export_full_template(data)
                css = export_scene_css(data)
                js = export_scene_js(data)

                # Use scene_template to scaffold directory
                display_name = data.get("name", scene_key.replace("_", " ").title())
                accent = data.get("accent_color", "#06b6d4")
                description = data.get("description", "Scene created by Creation Kit.")

                result = create_scene(
                    name=scene_key,
                    display_name=display_name,
                    accent=accent,
                    description=description,
                )

                # Overwrite scaffolded files with Kit-generated versions
                from engine.creation.scene_template import SCENES_DIR
                scene_dir = SCENES_DIR / scene_key

                # HTML template
                template_path = scene_dir / "templates" / f"{scene_key}.html"
                template_path.write_text(html, encoding="utf-8")

                # Scene CSS
                css_dir = scene_dir / "static" / "css"
                css_dir.mkdir(parents=True, exist_ok=True)
                css_path = scene_dir / "static" / f"{scene_key}.css"
                css_path.write_text(css, encoding="utf-8")

                # Scene JS
                js_dir = scene_dir / "static" / "js"
                js_dir.mkdir(parents=True, exist_ok=True)
                js_path = scene_dir / "static" / f"{scene_key}.js"
                js_path.write_text(js, encoding="utf-8")

                return jsonify({
                    "ok": True,
                    "scene_key": scene_key,
                    "path": str(scene_dir),
                    "files": {
                        "html": str(template_path),
                        "css": str(css_path),
                        "js": str(js_path),
                    },
                    "message": (
                        f"Scene '{display_name}' exported to content/scenes/{scene_key}/ "
                        f"(HTML + CSS + JS)"
                    ),
                })
            except Exception as exc:
                logger.error("Scene export failed: %s", exc, exc_info=True)
                return jsonify({"ok": False, "error": str(exc)}), 500

    def start(self) -> None:
        """Start the Creation Kit server."""
        logger.info("Creation Kit opening on %s:%d", self.host, self.port)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
