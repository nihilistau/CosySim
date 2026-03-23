"""
Creation Kit — Visual Scene Editor
====================================

Drag-and-drop scene construction tool. Visual editor for building CosySim
scenes from the shared component library without hand-coding HTML/JS/CSS.

Components are defined in ``engine.creation.component_registry``.
Layouts are saved as JSON and exported to working scene directories.

Version: v1.51.0 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.51.0 [2026-03-22] — Migrated to FlaskScene base class
    v1.50.0 [2026-03-22] — Asset browser API, 8 new component export helpers
                            (dice_roller, action_menu, combat_log, leaderboard,
                            resource_bar, dialogue_choice, poker_table, mini_map),
                            extension hook in JS generator
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

from flask import jsonify, render_template, request

from engine.scenes.flask_scene import FlaskScene
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

def _compute_shared_props(
    comp: Dict[str, Any],
    comp_def: Dict[str, Any],
    props: Dict[str, Any],
) -> None:
    """Compute shared/universal props: pct, variant_cls, status_cls, id_attr, slots, inv_slots, tab_buttons.

    Mutates *props* in-place.

    Args:
        comp: Component instance with type + props.
        comp_def: Component definition from the registry.
        props: Merged default + instance props dict.
    """
    # Percentage for stat bars
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


def _compute_component_props(comp: Dict[str, Any], props: Dict[str, Any]) -> None:
    """Compute per-component-type props (all the if/elif blocks).

    Mutates *props* in-place.

    Args:
        comp: Component instance with type + props.
        props: Merged default + instance props dict.
    """
    # Faction rows helper
    if comp.get("type") == "faction_bars":
        if "faction_rows" not in props:
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

    # v1.50.0 [2026-03-22] — Dice roller faces
    if comp.get("type") == "dice_roller":
        count = int(props.get("dice_count", 2))
        sides = props.get("sides", "d6")
        props["dice_faces"] = "\n".join(
            f'    <span class="ck-die" data-sides="{sides}">?</span>'
            for _ in range(count)
        )

    # v1.50.0 [2026-03-22] — Action menu items (with cost badges)
    if comp.get("type") == "action_menu":
        items = []
        show_cost = props.get("show_cost", True)
        for entry in props.get("items", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 4:
                name, cost, variant, bid = parts[0], parts[1], parts[2], parts[3]
                cost_badge = (
                    f'<span class="ck-action-cost">{cost}g</span>'
                    if show_cost else ""
                )
                items.append(
                    f'  <button class="cs-glass-btn cs-glass-btn--{variant} '
                    f'ck-action-btn" id="{bid}">'
                    f'{name}{cost_badge}</button>'
                )
        props["action_items"] = "\n".join(items)

    # v1.50.0 [2026-03-22] — Leaderboard rows (ranked)
    if comp.get("type") == "leaderboard":
        cols = [c.strip() for c in props.get("columns", "").split(",")]
        props["header_cells"] = "".join(f"<th>{c}</th>" for c in cols)
        rows = int(props.get("rows", 5))
        lb_rows = []
        for i in range(1, rows + 1):
            rank_cls = " ck-rank-gold" if i == 1 else (" ck-rank-silver" if i == 2 else (" ck-rank-bronze" if i == 3 else ""))
            cells = "".join(
                f"<td>{i if j == 0 else '&mdash;'}</td>" for j in range(len(cols))
            )
            lb_rows.append(f'    <tr class="ck-lb-row{rank_cls}">{cells}</tr>')
        props["leaderboard_rows"] = "\n".join(lb_rows)

    # v1.50.0 [2026-03-22] — Resource bar items
    if comp.get("type") == "resource_bar":
        items = []
        for entry in props.get("resources", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                name, value, color = parts[0], parts[1], parts[2]
                rid = name.lower().replace(" ", "_")
                items.append(
                    f'  <div class="ck-resource" id="res-{rid}">\n'
                    f'    <span class="ck-resource__label">{name}</span>\n'
                    f'    <span class="ck-resource__value" style="color:{color}">{value}</span>\n'
                    f'  </div>'
                )
        props["resource_items"] = "\n".join(items)

    # v1.50.0 [2026-03-22] — Dialogue choices
    if comp.get("type") == "dialogue_choice":
        items = []
        for entry in props.get("choices", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 2:
                text, cid = parts[0], parts[1]
                items.append(
                    f'  <button class="ck-dialogue-option" id="{cid}" '
                    f'data-choice="{cid}">{text}</button>'
                )
        props["choice_items"] = "\n".join(items)
        title = props.get("title", "")
        props["title_html"] = (
            f'<div class="ck-dialogue-prompt">{title}</div>' if title else ""
        )

    # v1.50.0 [2026-03-22] — Poker table helpers
    if comp.get("type") == "poker_table":
        props["pot_html"] = (
            f'<div class="ck-poker-pot" id="{props.get("table_id", "poker-table")}-pot">'
            f'<span class="ck-pot-label">POT</span> '
            f'<span class="ck-pot-value">0</span></div>'
        ) if props.get("show_pot") else ""
        seats = int(props.get("max_players", 4))
        props["player_seats"] = "\n".join(
            f'    <div class="ck-poker-seat" data-seat="{i}">Seat {i}</div>'
            for i in range(1, seats + 1)
        )

    # v1.50.0 [2026-03-22] — Mini map zone buttons
    if comp.get("type") == "mini_map":
        buttons = []
        current = props.get("current_zone", "")
        for entry in props.get("zones", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 2:
                label, zid = parts[0], parts[1]
                active = " ck-zone--active" if zid == current else ""
                buttons.append(
                    f'  <button class="ck-zone-btn{active}" data-zone="{zid}">'
                    f'{label}</button>'
                )
        props["zone_buttons"] = "\n".join(buttons)


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

    _compute_shared_props(comp, comp_def, props)
    _compute_component_props(comp, props)

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


def _css_root_palette(accent: str, r: int, g: int, b: int, name: str) -> str:
    """Generate the file header and :root CSS block with the scene palette.

    Args:
        accent: Hex accent color string.
        r: Red component (0-255).
        g: Green component (0-255).
        b: Blue component (0-255).
        name: Human-readable scene name.

    Returns:
        CSS string for the header + :root block.
    """
    return f"""/* ============================================================
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


def _css_component_blocks(types: set, r: int, g: int, b: int) -> str:
    """Generate conditional per-component CSS blocks.

    Only emits CSS for component types actually present in *types*.

    Args:
        types: Set of component type strings used in the layout.
        r: Red component (0-255).
        g: Green component (0-255).
        b: Blue component (0-255).

    Returns:
        CSS string with all matched component blocks.
    """
    css = ""

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

    # v1.50.0 [2026-03-22] — New game/interaction component styles

    if "dice_roller" in types:
        css += f"""/* ── Dice roller ───────────────────────────────────────── */
.ck-dice-roller {{
  text-align: center;
  padding: 12px;
  background: rgba({r},{g},{b},0.04);
  border: 1px solid rgba({r},{g},{b},0.15);
  border-radius: 6px;
  margin: 6px 0;
}}
.ck-dice-display {{
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-bottom: 10px;
}}
.ck-die {{
  width: 44px; height: 44px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.3rem; font-weight: 700;
  background: rgba(0,0,0,0.4);
  border: 2px solid rgba({r},{g},{b},0.3);
  border-radius: 6px;
  color: var(--scene-accent);
  transition: transform 0.3s ease;
}}
.ck-die.rolling {{ animation: ck-die-roll 0.4s ease-in-out; }}
@keyframes ck-die-roll {{
  0%,100% {{ transform: rotateX(0); }}
  25% {{ transform: rotateX(90deg) scale(0.9); }}
  50% {{ transform: rotateX(180deg) scale(1.1); }}
  75% {{ transform: rotateX(270deg) scale(0.9); }}
}}
.ck-dice-result {{
  font-size: 1.6rem; font-weight: 700;
  color: var(--scene-accent);
  margin-bottom: 8px;
  text-shadow: 0 0 12px var(--scene-accent-glow);
}}

"""

    if "action_menu" in types:
        css += f"""/* ── Action menu ───────────────────────────────────────── */
.ck-action-menu {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0;
}}
.ck-action-menu--vertical {{ flex-direction: column; }}
.ck-action-btn {{
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}}
.ck-action-cost {{
  font-size: 0.6rem;
  padding: 1px 5px;
  background: rgba({r},{g},{b},0.15);
  border-radius: 3px;
  color: var(--scene-accent);
  font-weight: 600;
}}

"""

    if "combat_log" in types:
        css += f"""/* ── Combat log ────────────────────────────────────────── */
.ck-combat-log {{
  font-size: 0.75rem;
  line-height: 1.5;
}}
.ck-combat-entry {{
  padding: 3px 8px;
  border-left: 2px solid transparent;
  margin: 2px 0;
}}
.ck-combat-entry.attack {{ border-left-color: #ef4444; color: #fca5a5; }}
.ck-combat-entry.defend {{ border-left-color: #3b82f6; color: #93bbfc; }}
.ck-combat-entry.heal   {{ border-left-color: #22c55e; color: #86efac; }}
.ck-combat-entry.system {{ border-left-color: rgba({r},{g},{b},0.3); color: var(--scene-muted); }}
.ck-combat-entry .ck-dmg {{
  font-weight: 700;
  color: #ef4444;
  text-shadow: 0 0 6px rgba(239,68,68,0.4);
}}

"""

    if "leaderboard" in types:
        css += f"""/* ── Leaderboard ───────────────────────────────────────── */
.ck-leaderboard {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}}
.ck-leaderboard th {{
  text-align: left;
  padding: 6px 10px;
  font-size: 0.65rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--scene-accent);
  border-bottom: 1px solid var(--scene-border);
}}
.ck-leaderboard td {{
  padding: 5px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  color: var(--scene-text);
}}
.ck-lb-row:hover td {{ background: rgba(255,255,255,0.02); }}
.ck-rank-gold td:first-child   {{ color: #fbbf24; font-weight: 700; }}
.ck-rank-silver td:first-child {{ color: #94a3b8; font-weight: 600; }}
.ck-rank-bronze td:first-child {{ color: #d97706; font-weight: 600; }}
.ck-rank-gold   {{ background: rgba(251,191,36,0.04); }}
.ck-rank-silver {{ background: rgba(148,163,184,0.03); }}
.ck-rank-bronze {{ background: rgba(217,119,6,0.03); }}

"""

    if "resource_bar" in types:
        css += f"""/* ── Resource bar ──────────────────────────────────────── */
.ck-resource-bar {{
  display: flex;
  gap: 16px;
  padding: 6px 12px;
  background: rgba({r},{g},{b},0.04);
  border: 1px solid rgba({r},{g},{b},0.12);
  border-radius: 4px;
  margin: 6px 0;
}}
.ck-resource {{
  display: flex;
  align-items: center;
  gap: 5px;
}}
.ck-resource__label {{
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--scene-muted);
}}
.ck-resource__value {{
  font-weight: 700;
  font-size: 0.85rem;
}}

"""

    if "dialogue_choice" in types:
        css += f"""/* ── Dialogue choices ──────────────────────────────────── */
.ck-dialogue-choices {{
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
}}
.ck-dialogue-prompt {{
  font-size: 0.78rem;
  color: var(--scene-muted);
  font-style: italic;
  margin-bottom: 4px;
}}
.ck-dialogue-option {{
  display: block;
  width: 100%;
  text-align: left;
  padding: 10px 14px;
  background: rgba({r},{g},{b},0.04);
  border: 1px solid rgba({r},{g},{b},0.15);
  border-left: 3px solid rgba({r},{g},{b},0.3);
  border-radius: 4px;
  color: var(--scene-text);
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.2s ease;
}}
.ck-dialogue-option:hover {{
  background: rgba({r},{g},{b},0.1);
  border-left-color: var(--scene-accent);
  color: var(--scene-accent);
  transform: translateX(4px);
}}

"""

    if "poker_table" in types:
        css += f"""/* ── Poker table ───────────────────────────────────────── */
.ck-poker-table {{
  padding: 16px;
  background: radial-gradient(ellipse, rgba(34,80,50,0.4) 0%, rgba(10,10,15,0.6) 100%);
  border: 2px solid rgba({r},{g},{b},0.2);
  border-radius: 120px / 60px;
  text-align: center;
  margin: 8px 0;
}}
.ck-poker-community, .ck-poker-hand {{
  display: flex;
  justify-content: center;
  gap: 8px;
  margin: 12px 0;
}}
.ck-card {{
  width: 48px; height: 68px;
  background: linear-gradient(135deg, #1a1a2e, #0f0f1a);
  border: 1px solid rgba({r},{g},{b},0.25);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; font-weight: 700;
  color: var(--scene-text);
}}
.ck-card.back {{
  background: repeating-linear-gradient(45deg, rgba({r},{g},{b},0.05), rgba({r},{g},{b},0.05) 4px, transparent 4px, transparent 8px);
}}
.ck-poker-pot {{
  font-size: 0.85rem;
  color: #fbbf24;
  font-weight: 600;
}}
.ck-pot-label {{ font-size: 0.6rem; color: var(--scene-muted); text-transform: uppercase; }}
.ck-poker-players {{
  display: flex;
  justify-content: space-around;
  margin-top: 10px;
}}
.ck-poker-seat {{
  padding: 4px 12px;
  font-size: 0.7rem;
  border: 1px solid var(--scene-border);
  border-radius: 4px;
  color: var(--scene-muted);
}}

"""

    if "mini_map" in types:
        css += f"""/* ── Mini map ──────────────────────────────────────────── */
.ck-mini-map {{
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  padding: 6px;
  background: rgba({r},{g},{b},0.04);
  border: 1px solid rgba({r},{g},{b},0.12);
  border-radius: 4px;
  margin: 6px 0;
}}
.ck-zone-btn {{
  padding: 6px 14px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--scene-border);
  border-radius: 4px;
  color: var(--scene-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}}
.ck-zone-btn:hover {{
  color: var(--scene-text);
  border-color: rgba({r},{g},{b},0.4);
}}
.ck-zone-btn.ck-zone--active {{
  color: var(--scene-accent);
  border-color: var(--scene-accent);
  background: rgba({r},{g},{b},0.1);
  box-shadow: 0 0 8px var(--scene-accent-glow);
}}

"""

    return css


def _css_responsive() -> str:
    """Generate the scrollbar and responsive CSS (always included).

    Returns:
        CSS string for scrollbar + responsive media queries.
    """
    return """/* ── Scrollbar ─────────────────────────────────────────── */
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
    name = layout.get("name", "Scene")
    r, g, b = _hex_to_rgb(accent)

    types = _collect_types(layout.get("components", []))

    css = _css_root_palette(accent, r, g, b, name)
    css += _css_component_blocks(types, r, g, b)
    css += _css_responsive()

    return css


# ──── JS Generation Engine ────────────────────────────────────────────────
# v1.49.0 [2026-03-21] — Generate scene-specific JS from layout
# CONNECTS: component IDs, Socket.IO, stat bars, chat logs, buttons
# CALLED BY: export_scene route
# EMITS: JS file content

def _js_class_header(class_name: str, name: str) -> str:
    """Generate JS class boilerplate: file header, constructor, lifecycle methods.

    Args:
        class_name: PascalCase JS class name.
        name: Human-readable scene name.

    Returns:
        JS string through the start of _applyState.
    """
    return f"""/**
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

  // v1.50.0 [2026-03-22] — Extension hook: add methods via
  // {class_name}.prototype._initExtensions = function() {{ ... }}
  init() {{
    this._setupSocket();
    this._setupUI();
    this._loadInitialState();
    if (typeof this._initExtensions === 'function') this._initExtensions();
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


def _js_stat_updaters(stat_ids: List[Dict[str, str]], types: set) -> str:
    """Generate stat bar update code inside _applyState.

    Args:
        stat_ids: List of stat bar ID dicts.
        types: Set of component type strings.

    Returns:
        JS string for stat bar + HUD badge updaters, closing _applyState.
    """
    js = ""
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
    return js


def _js_ui_wiring(
    btn_ids: List[Dict[str, str]],
    btn_group_buttons: List[Dict[str, str]],
    chat_input_ids: List[Dict[str, str]],
    components: List[Dict[str, Any]],
) -> str:
    """Generate _setupUI method: button, chat, and interactive component wiring.

    Args:
        btn_ids: List of button ID dicts.
        btn_group_buttons: List of button-group button dicts.
        chat_input_ids: List of chat input ID dicts.
        components: Full component tree (for flattening).

    Returns:
        JS string for the complete _setupUI method + action/sendMessage helpers.
    """
    js = ""
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

    # v1.50.0 [2026-03-22] — Wire new interactive components in _setupUI

    # Dice roller buttons
    for dc in [c for c in _flatten_components(components) if c.get("type") == "dice_roller"]:
        rid = dc.get("props", {}).get("roll_id", "dice-roller")
        fn_name = f"_rollDice_{rid.replace('-', '_')}"
        js += f"    document.getElementById('{rid}-btn')?.addEventListener('click', () => this.{fn_name}());\n"

    # Action menu buttons
    for ac in [c for c in _flatten_components(components) if c.get("type") == "action_menu"]:
        for entry in ac.get("props", {}).get("items", "").split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 4:
                name, cost, variant, bid = parts[0], parts[1], parts[2], parts[3]
                if bid.startswith("drink-"):
                    drink = bid.replace("drink-", "")
                    js += f"    document.getElementById('{bid}')?.addEventListener('click', () => this._action('order_drink', {{drink: '{drink}', cost: {cost}}}));\n"
                else:
                    js += f"    document.getElementById('{bid}')?.addEventListener('click', () => this._action('{bid}', {{cost: {cost}}}));\n"

    # Dialogue choice buttons
    for dc in [c for c in _flatten_components(components) if c.get("type") == "dialogue_choice"]:
        cid = dc.get("props", {}).get("choice_id", "dialogue-choices")
        js += f"""
    // Dialogue choices: {cid}
    document.querySelectorAll('#{cid} .ck-dialogue-option')?.forEach(btn => {{
      btn.addEventListener('click', () => this._action('dialogue_choice', {{ choice: btn.dataset.choice }}));
    }});
"""

    # Mini map zone buttons
    for mc in [c for c in _flatten_components(components) if c.get("type") == "mini_map"]:
        mid = mc.get("props", {}).get("map_id", "mini-map")
        js += f"""
    // Mini map zone nav: {mid}
    document.querySelectorAll('#{mid} .ck-zone-btn')?.forEach(btn => {{
      btn.addEventListener('click', () => {{
        this._setActiveZone(btn.dataset.zone);
        this._action('navigate_zone', {{ zone: btn.dataset.zone }});
      }});
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

    return js


def _js_api_fetchers(components: List[Dict[str, Any]]) -> tuple:
    """Generate API data fetcher methods for data-driven components.

    Args:
        components: Full component tree (for flattening).

    Returns:
        Tuple of (js_string, load_calls_list) where load_calls_list
        contains the ``this._loadX()`` call strings for bootstrap.
    """
    js = ""
    all_comps = _flatten_components(components)

    # Inventory grid
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

    # Event feed
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

    # Faction bars
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

    # NPC roster
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

    # Mission board
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

    # Crew roster
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

    # Data table
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

    # Build load_calls list
    load_calls: List[str] = []
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

    return js, load_calls


def _js_interactive_components(components: List[Dict[str, Any]]) -> str:
    """Generate JS for dice roller, combat log, dialogue choices, and minimap.

    Args:
        components: Full component tree (for flattening).

    Returns:
        JS string with interactive component methods.
    """
    js = ""
    all_comps = _flatten_components(components)

    # v1.50.0 [2026-03-22] — Dice roller JS
    dice_comps = [c for c in all_comps if c.get("type") == "dice_roller"]
    if dice_comps:
        for dc in dice_comps:
            rid = dc.get("props", {}).get("roll_id", "dice-roller")
            sides_str = dc.get("props", {}).get("sides", "d6")
            js += f"""  // ── Dice roller: {rid} ─────────────────────────────────────

  _rollDice_{rid.replace('-', '_')}() {{
    const sides = parseInt('{sides_str}'.replace('d', ''));
    const dice = document.querySelectorAll('#{rid} .ck-die');
    const resultEl = document.getElementById('{rid}-result');
    let total = 0;
    dice.forEach(die => {{
      die.classList.add('rolling');
      const val = Math.floor(Math.random() * sides) + 1;
      total += val;
      setTimeout(() => {{
        die.textContent = val;
        die.classList.remove('rolling');
      }}, 400);
    }});
    setTimeout(() => {{
      if (resultEl) resultEl.textContent = total;
      this._action('dice_roll', {{ sides: '{sides_str}', result: total }});
    }}, 450);
  }}

"""

    # v1.50.0 [2026-03-22] — Combat log JS
    combat_comps = [c for c in all_comps if c.get("type") == "combat_log"]
    if combat_comps:
        lid = combat_comps[0].get("props", {}).get("log_id", "combat-log")
        max_entries = combat_comps[0].get("props", {}).get("max_entries", 50)
        js += f"""  // ── Combat log: {lid} ─────────────────────────────────────

  _addCombatEntry(text, type = 'system') {{
    const log = document.getElementById('{lid}');
    if (!log) return;
    const entry = document.createElement('div');
    entry.className = 'ck-combat-entry ' + type;
    entry.innerHTML = text;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
    while (log.children.length > {max_entries}) log.removeChild(log.firstChild);
  }}

"""

    # v1.50.0 [2026-03-22] — Dialogue choice JS
    dialogue_comps = [c for c in all_comps if c.get("type") == "dialogue_choice"]
    if dialogue_comps:
        cid = dialogue_comps[0].get("props", {}).get("choice_id", "dialogue-choices")
        js += f"""  // ── Dialogue choices: {cid} ──────────────────────────────

  _setChoices(choices) {{
    const el = document.getElementById('{cid}');
    if (!el) return;
    const buttons = el.querySelectorAll('.ck-dialogue-option');
    buttons.forEach(b => b.remove());
    choices.forEach(c => {{
      const btn = document.createElement('button');
      btn.className = 'ck-dialogue-option';
      btn.dataset.choice = c.id;
      btn.textContent = c.text;
      btn.addEventListener('click', () => this._action('dialogue_choice', {{ choice: c.id }}));
      el.appendChild(btn);
    }});
  }}

"""

    # v1.50.0 [2026-03-22] — Mini map JS
    minimap_comps = [c for c in all_comps if c.get("type") == "mini_map"]
    if minimap_comps:
        mid = minimap_comps[0].get("props", {}).get("map_id", "mini-map")
        js += f"""  // ── Mini map: {mid} ──────────────────────────────────────

  _setActiveZone(zoneId) {{
    const map = document.getElementById('{mid}');
    if (!map) return;
    map.querySelectorAll('.ck-zone-btn').forEach(btn => {{
      btn.classList.toggle('ck-zone--active', btn.dataset.zone === zoneId);
    }});
  }}

"""

    return js


def _js_bootstrap(class_name: str, load_calls: List[str]) -> str:
    """Generate _loadAllData method (if needed) and DOMContentLoaded bootstrap.

    Args:
        class_name: PascalCase JS class name.
        load_calls: List of ``this._loadX()`` call strings.

    Returns:
        JS string closing the class and adding bootstrap code.
    """
    js = ""

    if load_calls:
        js += "  // ── Load all data on init ──────────────────────────────────\n\n"
        js += "  _loadAllData() {\n"
        for call in load_calls:
            js += f"    {call}\n"
        js += "  }\n\n"

    init_extra = "\n    this._loadAllData();" if load_calls else ""

    js += f"""}}

// ── Bootstrap ───────────────────────────────────────────────────────
const SceneApp = new {class_name}();
document.addEventListener('DOMContentLoaded', () => {{
  SceneApp.init();{init_extra}
}});
"""

    return js


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

    js = _js_class_header(class_name, name)
    js += _js_stat_updaters(stat_ids, types)
    js += _js_ui_wiring(btn_ids, btn_group_buttons, chat_input_ids, components)

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
    fetcher_js, load_calls = _js_api_fetchers(components)
    js += fetcher_js

    js += _js_interactive_components(components)
    js += _js_bootstrap(class_name, load_calls)

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

# v1.51.0 [2026-03-22] — Migrated to FlaskScene
class CreationKitScene(FlaskScene):
    """Creation Kit — visual scene editor.

    CONNECTS: component_registry, scene_template, asset_registry, FlaskScene
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
        super().__init__(host=host, port=port)

        # Custom static URL path for the creation kit
        self.app.static_url_path = f"/{SCENE_ID}/static"

        # Scene-specific routes (FlaskScene handles Flask, SocketIO, CORS,
        # shared assets, and health routes)
        self._setup_routes()

    # v1.47.0 [2026-03-21] — Creation Kit routes
    def _setup_routes(self) -> None:
        """Register all Flask HTTP routes."""

        @self.app.route("/")
        def index():
            return render_template("creation_kit.html")

        self._setup_component_routes()
        self._setup_layout_routes()
        self._setup_asset_routes()
        self._setup_export_routes()

    def _setup_component_routes(self) -> None:
        """Register component catalogue routes."""

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

    def _setup_layout_routes(self) -> None:
        """Register layout CRUD routes."""

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

    def _setup_asset_routes(self) -> None:
        """Register asset browsing routes."""

        # ── Asset browsing ─────────────────────────────────────────
        # v1.50.0 [2026-03-22] — Asset library + registry browsing
        # CONNECTS: engine.asset_studio.asset_library, engine.creation.asset_registry
        # CALLED BY: Creation Kit asset browser drawer
        # EMITS: JSON asset lists for thumbnail grid

        @self.app.route("/api/assets/library")
        def api_asset_library():
            """List assets from the Asset Library (generated assets)."""
            try:
                from engine.asset_studio.asset_library import get_asset_library
                lib = get_asset_library()
                assets = lib.list_assets(
                    asset_type=request.args.get("type"),
                    scene=request.args.get("scene"),
                    character_id=request.args.get("character"),
                    favorites_only=request.args.get("favorites") == "1",
                    limit=int(request.args.get("limit", 50)),
                    offset=int(request.args.get("offset", 0)),
                    search=request.args.get("q"),
                )
                return jsonify({"assets": assets, "source": "library"})
            except Exception as exc:
                logger.warning("Asset library query failed: %s", exc)
                return jsonify({"assets": [], "source": "library", "error": str(exc)})

        @self.app.route("/api/assets/library/stats")
        def api_asset_library_stats():
            """Return asset library stats (counts by type)."""
            try:
                from engine.asset_studio.asset_library import get_asset_library
                return jsonify(get_asset_library().stats())
            except Exception as exc:
                return jsonify({"total": 0, "by_type": {}, "error": str(exc)})

        @self.app.route("/api/assets/registry")
        def api_asset_registry():
            """List assets from the Asset Registry (filesystem scan)."""
            try:
                from engine.creation.asset_registry import AssetRegistry
                registry = AssetRegistry()
                asset_type = request.args.get("type")
                query = request.args.get("q", "")

                if query:
                    entries = registry.search(query, asset_type)
                else:
                    entries = registry.scan()
                    if asset_type:
                        entries = [e for e in entries if e.asset_type == asset_type]

                return jsonify({
                    "assets": [e.to_dict() for e in entries],
                    "total": len(entries),
                    "source": "registry",
                })
            except Exception as exc:
                logger.warning("Asset registry scan failed: %s", exc)
                return jsonify({"assets": [], "total": 0, "source": "registry", "error": str(exc)})

        @self.app.route("/api/assets/combined")
        def api_asset_combined():
            """Combined search across Asset Library + Asset Registry."""
            asset_type = request.args.get("type")
            query = request.args.get("q", "")
            limit = int(request.args.get("limit", 50))
            combined = []

            # Library (generated assets)
            try:
                from engine.asset_studio.asset_library import get_asset_library
                lib = get_asset_library()
                lib_assets = lib.list_assets(
                    asset_type=asset_type,
                    search=query or None,
                    limit=limit,
                )
                for a in lib_assets:
                    combined.append({
                        "id": a.get("id", ""),
                        "name": a.get("title", ""),
                        "url": a.get("url", ""),
                        "type": a.get("asset_type", ""),
                        "source": "library",
                        "favorite": a.get("favorite", False),
                    })
            except Exception as exc:
                logger.debug("Asset library unavailable: %s", exc)

            # Registry (filesystem assets)
            try:
                from engine.creation.asset_registry import AssetRegistry
                registry = AssetRegistry()
                if query:
                    reg_entries = registry.search(query, asset_type)
                else:
                    reg_entries = registry.scan()
                    if asset_type:
                        reg_entries = [e for e in reg_entries if e.asset_type == asset_type]

                seen_urls = {a["url"] for a in combined}
                for e in reg_entries:
                    url = str(e.path)
                    if url not in seen_urls:
                        combined.append({
                            "id": e.asset_id,
                            "name": e.name,
                            "url": url,
                            "type": e.asset_type,
                            "source": "registry",
                            "favorite": False,
                        })
            except Exception as exc:
                logger.debug("Asset registry unavailable: %s", exc)

            return jsonify({
                "assets": combined[:limit],
                "total": len(combined),
            })

        @self.app.route("/api/assets/file/<path:asset_path>")
        def api_asset_file(asset_path: str):
            """Serve an asset file for thumbnail preview (sandboxed to project root)."""
            from flask import send_from_directory, abort
            project_root = Path(__file__).resolve().parents[3]
            full_path = (project_root / asset_path).resolve()
            # Security: ensure path stays within project
            if not str(full_path).startswith(str(project_root)):
                abort(403)
            if not full_path.is_file():
                abort(404)
            return send_from_directory(
                str(full_path.parent),
                full_path.name,
            )

    def _setup_export_routes(self) -> None:
        """Register export routes."""

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
        # v1.52.0 [2026-03-22] — Full scene factory with auto-registration
        # CONNECTS: create_scene(), control_plane_registry, launcher.yaml
        # CALLED BY: Creation Kit editor "Export" button
        # EMITS: Scene directory with HTML + CSS + JS + test + registration
        def api_export_scene():
            """Export layout to a full scene directory with auto-registration.

            Generates HTML, CSS, JS from the layout, scaffolds the scene
            directory with a FlaskScene subclass, creates a test file,
            and registers the scene in control_plane_registry.py and
            launcher.yaml so it's immediately launchable.
            """
            data = request.get_json(force=True) or {}
            scene_key = data.get("scene_key", "")
            if not scene_key or not scene_key.isidentifier():
                return jsonify({"ok": False, "error": "Invalid scene_key"}), 400

            try:
                # Generate all three files from layout
                html = export_full_template(data)
                css = export_scene_css(data)
                js = export_scene_js(data)

                # Use scene_template to scaffold directory + register
                display_name = data.get("name", scene_key.replace("_", " ").title())
                accent = data.get("accent_color", "#06b6d4")
                description = data.get("description", "Scene created by Creation Kit.")

                # v1.52.0 — create_scene now also generates test file
                # and auto-registers in control_plane_registry + launcher.yaml
                result = create_scene(
                    name=scene_key,
                    display_name=display_name,
                    accent=accent,
                    description=description,
                    generate_test=True,
                    auto_register=True,
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

                # v1.52.0 — Find the next available port for launch instructions
                from engine.port_registry import get_port
                scene_port = get_port(scene_key, 5590)

                return jsonify({
                    "ok": True,
                    "scene_key": scene_key,
                    "path": str(scene_dir),
                    "port": scene_port,
                    "files": {
                        "html": str(template_path),
                        "css": str(css_path),
                        "js": str(js_path),
                        "scene_py": str(scene_dir / f"{scene_key}_scene.py"),
                        "test": str(SCENES_DIR.parent.parent / "tests" / f"test_{scene_key}.py"),
                    },
                    "registered": True,
                    "launch_cmd": f"python launcher.py {scene_key}",
                    "url": f"http://localhost:{scene_port}",
                    "message": (
                        f"Scene '{display_name}' exported to content/scenes/{scene_key}/ "
                        f"(HTML + CSS + JS + test). Registered in launcher. "
                        f"Launch with: python launcher.py {scene_key}"
                    ),
                })
            except FileExistsError:
                return jsonify({
                    "ok": False,
                    "error": f"Scene '{scene_key}' already exists. Delete it first or choose a different name.",
                }), 409
            except Exception as exc:
                logger.error("Scene export failed: %s", exc, exc_info=True)
                return jsonify({"ok": False, "error": str(exc)}), 500

    # v1.51.0 [2026-03-22] — FlaskScene handles start()/stop(); use hooks

    def on_shutdown(self) -> None:
        """Scene-specific cleanup on shutdown."""
        logger.info("Creation Kit stopped")
