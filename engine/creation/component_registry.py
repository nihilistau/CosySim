"""
Component Registry — CosySim Creation Kit
==========================================

Defines the building blocks for the visual scene editor. Each component
maps to existing shared CSS classes and HTML patterns used across all
CosySim scenes.

Components are JSON-serializable definitions with:
- type: unique identifier
- label: human display name
- category: grouping for the palette
- icon: display icon (HTML entity)
- default_props: initial property values
- prop_schema: editable property definitions
- html_template: Jinja2 fragment for export
- css_classes: shared CSS classes this component uses
- slots: named child areas (for container components)

Version: v1.48.0 [2026-03-21]
Author:  CosySim Team

Change Log:
    v1.48.0 [2026-03-21] — Added 10 new components (economy, map, skills,
                            particles, progress, alerts, tables, images,
                            spacer, divider) — 28 total
    v1.47.0 [2026-03-21] — Initial component registry for Creation Kit
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──── Property Types ──────────────────────────────────────────────────────

PROP_TYPES = {
    "text":     {"type": "text",     "label": "Text"},
    "textarea": {"type": "textarea", "label": "Multiline Text"},
    "number":   {"type": "number",   "label": "Number"},
    "color":    {"type": "color",    "label": "Color"},
    "select":   {"type": "select",   "label": "Dropdown"},
    "boolean":  {"type": "boolean",  "label": "Toggle"},
    "range":    {"type": "range",    "label": "Slider"},
}


# ──── Component Categories ────────────────────────────────────────────────

CATEGORIES = [
    {"id": "layout",    "label": "Layout",     "icon": "&#9638;"},
    {"id": "display",   "label": "Display",    "icon": "&#9673;"},
    {"id": "input",     "label": "Input",      "icon": "&#9998;"},
    {"id": "data",      "label": "Data",       "icon": "&#9776;"},
    {"id": "media",     "label": "Media",      "icon": "&#9835;"},
    {"id": "game",      "label": "Game",       "icon": "&#9812;"},
    {"id": "nav",       "label": "Navigation", "icon": "&#9654;"},
]


# ──── Component Definitions ───────────────────────────────────────────────
# Each component maps directly to existing CosySim shared CSS patterns.

COMPONENTS: Dict[str, Dict[str, Any]] = {

    # ── Layout components ─────────────────────────────────────────────

    "glass_panel": {
        "type": "glass_panel",
        "label": "Glass Panel",
        "category": "layout",
        "icon": "&#9634;",
        "description": "Frosted glass container — the core building block.",
        "css_classes": ["cs-glass-panel"],
        "default_props": {
            "title": "Panel Title",
            "variant": "default",
            "padding": "14px",
            "min_height": "100px",
        },
        "prop_schema": [
            {"key": "title",      "label": "Title",   "type": "text"},
            {"key": "variant",    "label": "Variant",  "type": "select",
             "options": ["default", "glow", "strong", "light"]},
            {"key": "padding",    "label": "Padding",  "type": "text"},
            {"key": "min_height", "label": "Min Height", "type": "text"},
        ],
        "slots": ["content"],
        "html_template": (
            '<section class="cs-glass-panel{variant_cls}" style="padding:{padding};min-height:{min_height}">\n'
            '  <h3 class="panel-title">&#9670; {title}</h3>\n'
            '  <div class="panel-content">{slot_content}</div>\n'
            '</section>'
        ),
    },

    "column_layout": {
        "type": "column_layout",
        "label": "Column Layout",
        "category": "layout",
        "icon": "&#9783;",
        "description": "Multi-column grid container.",
        "css_classes": [],
        "default_props": {
            "columns": 3,
            "gap": "16px",
        },
        "prop_schema": [
            {"key": "columns", "label": "Columns", "type": "number", "min": 1, "max": 6},
            {"key": "gap",     "label": "Gap",     "type": "text"},
        ],
        "slots": ["col_1", "col_2", "col_3"],
        "html_template": (
            '<div class="ck-columns" style="display:grid;grid-template-columns:repeat({columns},1fr);gap:{gap}">\n'
            '  {slot_columns}\n'
            '</div>'
        ),
    },

    "sidebar": {
        "type": "sidebar",
        "label": "Sidebar",
        "category": "layout",
        "icon": "&#9611;",
        "description": "Fixed-width sidebar panel.",
        "css_classes": ["sidebar"],
        "default_props": {
            "width": "260px",
            "side": "left",
        },
        "prop_schema": [
            {"key": "width", "label": "Width", "type": "text"},
            {"key": "side",  "label": "Side",  "type": "select", "options": ["left", "right"]},
        ],
        "slots": ["content"],
        "html_template": (
            '<aside class="sidebar sidebar-{side}" style="width:{width}">\n'
            '  {slot_content}\n'
            '</aside>'
        ),
    },

    "section_divider": {
        "type": "section_divider",
        "label": "Section Title",
        "category": "layout",
        "icon": "&#9472;",
        "description": "Section heading with accent underline.",
        "css_classes": ["section-title"],
        "default_props": {
            "text": "SECTION TITLE",
            "icon": "&#9672;",
        },
        "prop_schema": [
            {"key": "text", "label": "Text", "type": "text"},
            {"key": "icon", "label": "Icon", "type": "text"},
        ],
        "slots": [],
        "html_template": '<h2 class="section-title">{icon} {text}</h2>',
    },

    # ── Display components ────────────────────────────────────────────

    "stat_bar": {
        "type": "stat_bar",
        "label": "Stat Bar",
        "category": "display",
        "icon": "&#9608;",
        "description": "Animated progress bar with label and value.",
        "css_classes": ["cs-stat-bar"],
        "default_props": {
            "label": "HP",
            "value": 75,
            "max_value": 100,
            "color": "var(--accent, #06b6d4)",
            "stat_id": "stat-hp",
        },
        "prop_schema": [
            {"key": "label",     "label": "Label",     "type": "text"},
            {"key": "value",     "label": "Value",     "type": "number", "min": 0},
            {"key": "max_value", "label": "Max Value", "type": "number", "min": 1},
            {"key": "color",     "label": "Color",     "type": "color"},
            {"key": "stat_id",   "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="cs-stat-bar">\n'
            '  <span class="cs-stat-bar__label">{label}</span>\n'
            '  <div class="cs-stat-bar__track">\n'
            '    <div class="cs-stat-bar__fill" id="{stat_id}" '
            'style="width:{pct}%;background:{color}"></div>\n'
            '  </div>\n'
            '  <span class="cs-stat-bar__value" id="val-{stat_id}">{value}</span>\n'
            '</div>'
        ),
    },

    "portrait": {
        "type": "portrait",
        "label": "Character Portrait",
        "category": "display",
        "icon": "&#9786;",
        "description": "Round character portrait with status indicator.",
        "css_classes": ["cs-portrait-frame"],
        "default_props": {
            "size": "md",
            "status": "online",
            "image_url": "/shared/img/default_portrait.png",
            "character_name": "Character",
        },
        "prop_schema": [
            {"key": "size",           "label": "Size",   "type": "select",
             "options": ["sm", "md", "lg", "xl"]},
            {"key": "status",         "label": "Status", "type": "select",
             "options": ["online", "away", "offline", "speaking"]},
            {"key": "image_url",      "label": "Image URL", "type": "text"},
            {"key": "character_name", "label": "Name",   "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="cs-portrait-frame cs-portrait-frame--{size}'
            '{status_cls}" title="{character_name}">\n'
            '  <img src="{image_url}" alt="{character_name}">\n'
            '</div>'
        ),
    },

    "ticker": {
        "type": "ticker",
        "label": "News Ticker",
        "category": "display",
        "icon": "&#8592;",
        "description": "Horizontally scrolling news/event feed.",
        "css_classes": ["neoncity-ticker"],
        "default_props": {
            "label": "CITY FEED",
            "ticker_id": "ticker-inner",
            "speed": 40,
        },
        "prop_schema": [
            {"key": "label",     "label": "Label",   "type": "text"},
            {"key": "ticker_id", "label": "Element ID", "type": "text"},
            {"key": "speed",     "label": "Speed (s)", "type": "number", "min": 10, "max": 120},
        ],
        "slots": [],
        "html_template": (
            '<div class="neoncity-ticker">\n'
            '  <span class="ticker-label">{label}</span>\n'
            '  <div class="ticker-track">\n'
            '    <div class="ticker-inner" id="{ticker_id}">\n'
            '      <span class="ticker-item">[SYSTEM] Connecting...</span>\n'
            '    </div>\n'
            '  </div>\n'
            '</div>'
        ),
    },

    # ── Input components ──────────────────────────────────────────────

    "chat_log": {
        "type": "chat_log",
        "label": "Chat Log",
        "category": "input",
        "icon": "&#128172;",
        "description": "Scrollable chat message area with input.",
        "css_classes": ["chat-log"],
        "default_props": {
            "chat_id": "chat-log",
            "input_id": "chat-input",
            "placeholder": "Type a message...",
            "title": "COMMS",
        },
        "prop_schema": [
            {"key": "chat_id",    "label": "Log Element ID", "type": "text"},
            {"key": "input_id",   "label": "Input Element ID", "type": "text"},
            {"key": "placeholder", "label": "Placeholder", "type": "text"},
            {"key": "title",      "label": "Title",    "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<section class="cs-glass-panel">\n'
            '  <h2 class="section-title">&#9672; {title}</h2>\n'
            '  <div class="chat-log" id="{chat_id}">\n'
            '    <div class="chat-entry system">\n'
            '      <span class="entry-src">[SYSTEM]</span> Connected.\n'
            '    </div>\n'
            '  </div>\n'
            '  <div class="chat-input-row">\n'
            '    <input type="text" id="{input_id}" class="chat-input"\n'
            '           placeholder="{placeholder}">\n'
            '    <button class="cs-glass-btn cs-glass-btn--accent">SEND</button>\n'
            '  </div>\n'
            '</section>'
        ),
    },

    "button": {
        "type": "button",
        "label": "Button",
        "category": "input",
        "icon": "&#9654;",
        "description": "Styled glass button with variants.",
        "css_classes": ["cs-glass-btn"],
        "default_props": {
            "text": "ACTION",
            "variant": "accent",
            "btn_id": "",
        },
        "prop_schema": [
            {"key": "text",    "label": "Text",    "type": "text"},
            {"key": "variant", "label": "Variant", "type": "select",
             "options": ["default", "accent", "danger", "hack"]},
            {"key": "btn_id",  "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<button class="cs-glass-btn cs-glass-btn--{variant}"'
            '{id_attr}>{text}</button>'
        ),
    },

    "tab_bar": {
        "type": "tab_bar",
        "label": "Tab Bar",
        "category": "input",
        "icon": "&#9783;",
        "description": "Horizontal tab switcher.",
        "css_classes": ["mission-tabs"],
        "default_props": {
            "tabs": "TAB 1,TAB 2,TAB 3",
            "active_tab": 0,
        },
        "prop_schema": [
            {"key": "tabs",       "label": "Tabs (comma-sep)", "type": "text"},
            {"key": "active_tab", "label": "Active Index",     "type": "number", "min": 0},
        ],
        "slots": [],
        "html_template": (
            '<div class="mission-tabs">\n'
            '  {tab_buttons}\n'
            '</div>'
        ),
    },

    # ── Data components ───────────────────────────────────────────────

    "card_grid": {
        "type": "card_grid",
        "label": "Card Grid",
        "category": "data",
        "icon": "&#9641;",
        "description": "Grid of clickable glass cards (districts, items, etc.).",
        "css_classes": ["district-cards"],
        "default_props": {
            "columns": 3,
            "card_count": 3,
            "card_template": "default",
        },
        "prop_schema": [
            {"key": "columns",       "label": "Columns",    "type": "number", "min": 1, "max": 5},
            {"key": "card_count",    "label": "Card Count", "type": "number", "min": 1, "max": 12},
            {"key": "card_template", "label": "Card Style", "type": "select",
             "options": ["default", "district", "mission", "inventory"]},
        ],
        "slots": ["cards"],
        "html_template": (
            '<div class="district-cards" style="grid-template-columns:repeat({columns},1fr)">\n'
            '  {slot_cards}\n'
            '</div>'
        ),
    },

    "inventory_grid": {
        "type": "inventory_grid",
        "label": "Inventory Grid",
        "category": "data",
        "icon": "&#9638;",
        "description": "Item slot grid (4x3 default).",
        "css_classes": ["inventory-grid"],
        "default_props": {
            "slots": 12,
            "grid_id": "inventory-grid",
        },
        "prop_schema": [
            {"key": "slots",   "label": "Slot Count", "type": "number", "min": 4, "max": 24},
            {"key": "grid_id", "label": "Element ID",  "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="inventory-grid" id="{grid_id}">\n'
            '  {inv_slots}\n'
            '</div>'
        ),
    },

    "faction_bars": {
        "type": "faction_bars",
        "label": "Faction Bars",
        "category": "data",
        "icon": "&#9876;",
        "description": "Horizontal power bars for factions/skills.",
        "css_classes": ["faction-list"],
        "default_props": {
            "factions": "OmniCorp:#3b82f6:78,NeoTech:#8b5cf6:52,BlackMarket:#f97316:22",
        },
        "prop_schema": [
            {"key": "factions", "label": "Factions (name:color:power,...)", "type": "textarea"},
        ],
        "slots": [],
        "html_template": (
            '<div class="faction-list" id="faction-list">\n'
            '  {faction_rows}\n'
            '</div>'
        ),
    },

    "event_feed": {
        "type": "event_feed",
        "label": "Event Feed",
        "category": "data",
        "icon": "&#9888;",
        "description": "Rich event card feed (v1.46 style).",
        "css_classes": ["events-panel"],
        "default_props": {
            "feed_id": "events-list",
            "title": "ACTIVE EVENTS",
            "max_height": "260px",
        },
        "prop_schema": [
            {"key": "feed_id",    "label": "Element ID",  "type": "text"},
            {"key": "title",      "label": "Title",       "type": "text"},
            {"key": "max_height", "label": "Max Height",  "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<section class="events-panel">\n'
            '  <h2 class="section-title">&#9672; {title}</h2>\n'
            '  <div class="events-list" id="{feed_id}" style="max-height:{max_height}">\n'
            '    <div class="event-item system">No active events detected.</div>\n'
            '  </div>\n'
            '  <button class="btn-refresh-events">&#8634; REFRESH FEED</button>\n'
            '</section>'
        ),
    },

    # ── Game components ───────────────────────────────────────────────

    "crew_roster": {
        "type": "crew_roster",
        "label": "Crew Roster",
        "category": "game",
        "icon": "&#9731;",
        "description": "Crew member list with status badges.",
        "css_classes": ["crew-panel"],
        "default_props": {
            "max_crew": 8,
            "roster_id": "crew-roster",
        },
        "prop_schema": [
            {"key": "max_crew",   "label": "Max Crew", "type": "number", "min": 1, "max": 12},
            {"key": "roster_id",  "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<section class="hud-panel crew-panel">\n'
            '  <h3 class="panel-title">&#9670; CREW '
            '<span class="crew-count" id="crew-count">0/{max_crew}</span></h3>\n'
            '  <div class="crew-roster" id="{roster_id}">\n'
            '    <div class="crew-empty">No crew recruited yet.</div>\n'
            '  </div>\n'
            '</section>'
        ),
    },

    "mission_board": {
        "type": "mission_board",
        "label": "Mission Board",
        "category": "game",
        "icon": "&#9873;",
        "description": "Mission list with Available/Active tabs.",
        "css_classes": ["mission-panel"],
        "default_props": {
            "board_id": "mission-list",
        },
        "prop_schema": [
            {"key": "board_id", "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<section class="hud-panel mission-panel">\n'
            '  <h3 class="panel-title">&#9670; MISSIONS '
            '<span class="mission-count" id="mission-count">0</span></h3>\n'
            '  <div class="mission-tabs">\n'
            '    <button class="mission-tab active" data-tab="available">AVAILABLE</button>\n'
            '    <button class="mission-tab" data-tab="active">ACTIVE</button>\n'
            '  </div>\n'
            '  <div class="mission-list" id="{board_id}">\n'
            '    <div class="mission-empty">Loading missions...</div>\n'
            '  </div>\n'
            '</section>'
        ),
    },

    # ── Navigation components ─────────────────────────────────────────

    "scene_header": {
        "type": "scene_header",
        "label": "Scene Header",
        "category": "nav",
        "icon": "&#9733;",
        "description": "Top header bar with title, clock, and credits.",
        "css_classes": ["neoncity-header"],
        "default_props": {
            "title": "SCENE NAME",
            "subtitle": "v1.0",
            "show_clock": True,
            "show_credits": True,
        },
        "prop_schema": [
            {"key": "title",        "label": "Title",        "type": "text"},
            {"key": "subtitle",     "label": "Subtitle",     "type": "text"},
            {"key": "show_clock",   "label": "Show Clock",   "type": "boolean"},
            {"key": "show_credits", "label": "Show Credits",  "type": "boolean"},
        ],
        "slots": [],
        "html_template": (
            '<header class="neoncity-header">\n'
            '  <div class="header-left">\n'
            '    <h1 class="city-title">{title}</h1>\n'
            '    <div class="city-version">{subtitle}</div>\n'
            '  </div>\n'
            '  {clock_html}\n'
            '  {credits_html}\n'
            '</header>'
        ),
    },

    "modal": {
        "type": "modal",
        "label": "Modal Dialog",
        "category": "nav",
        "icon": "&#9744;",
        "description": "Overlay modal with header, body, and footer.",
        "css_classes": ["district-modal"],
        "default_props": {
            "title": "MODAL TITLE",
            "modal_id": "custom-modal",
        },
        "prop_schema": [
            {"key": "title",    "label": "Title",      "type": "text"},
            {"key": "modal_id", "label": "Element ID",  "type": "text"},
        ],
        "slots": ["body", "footer"],
        "html_template": (
            '<div class="district-modal" id="{modal_id}" style="display:none">\n'
            '  <div class="modal-overlay"></div>\n'
            '  <div class="modal-content">\n'
            '    <div class="modal-header">\n'
            '      <h3 class="modal-title">{title}</h3>\n'
            '      <button class="modal-close">&#10005;</button>\n'
            '    </div>\n'
            '    <div class="modal-body">{slot_body}</div>\n'
            '    <div class="modal-footer">{slot_footer}</div>\n'
            '  </div>\n'
            '</div>'
        ),
    },

    # ── v1.48.0 [2026-03-21] — New components ─────────────────────

    "economy_panel": {
        "type": "economy_panel",
        "label": "Economy Panel",
        "category": "data",
        "icon": "&#8354;",
        "description": "Balance display with intel buy and exchange controls.",
        "css_classes": ["economy-panel"],
        "default_props": {
            "balance_id": "econ-balance",
            "show_intel": True,
            "show_exchange": True,
        },
        "prop_schema": [
            {"key": "balance_id",   "label": "Balance Element ID", "type": "text"},
            {"key": "show_intel",   "label": "Show Intel Buy",     "type": "boolean"},
            {"key": "show_exchange", "label": "Show Exchange",      "type": "boolean"},
        ],
        "slots": [],
        "html_template": (
            '<section class="cs-glass-panel">\n'
            '  <h2 class="section-title">&#9672; ECONOMY</h2>\n'
            '  <div class="econ-balance">\n'
            '    <span class="econ-label">BALANCE</span>\n'
            '    <span class="econ-value" id="{balance_id}">&#8354; &mdash;</span>\n'
            '  </div>\n'
            '  {intel_html}\n'
            '  {exchange_html}\n'
            '</section>'
        ),
    },

    "map_widget": {
        "type": "map_widget",
        "label": "City Map",
        "category": "nav",
        "icon": "&#9673;",
        "description": "Location display with travel buttons to neighbors.",
        "css_classes": ["map-panel"],
        "default_props": {
            "location_name": "Loading...",
            "map_id": "map-neighbors",
        },
        "prop_schema": [
            {"key": "location_name", "label": "Default Location", "type": "text"},
            {"key": "map_id",        "label": "Neighbors ID",     "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<section class="hud-panel map-panel">\n'
            '  <h3 class="panel-title">&#9670; CITY MAP</h3>\n'
            '  <div class="map-location" id="map-current">\n'
            '    <span class="loc-icon">&#9673;</span>\n'
            '    <span id="map-loc-name">{location_name}</span>\n'
            '  </div>\n'
            '  <div class="map-neighbors" id="{map_id}"></div>\n'
            '</section>'
        ),
    },

    "skill_tree": {
        "type": "skill_tree",
        "label": "Skill Progression",
        "category": "game",
        "icon": "&#9733;",
        "description": "Skill list with XP bars and level indicators.",
        "css_classes": ["player-skills"],
        "default_props": {
            "skills_id": "player-skills",
            "skill_count": 8,
        },
        "prop_schema": [
            {"key": "skills_id",   "label": "Element ID",  "type": "text"},
            {"key": "skill_count", "label": "Skill Count", "type": "number", "min": 1, "max": 16},
        ],
        "slots": [],
        "html_template": (
            '<section class="hud-panel">\n'
            '  <h3 class="panel-title">&#9670; SKILLS</h3>\n'
            '  <div class="player-skills" id="{skills_id}">\n'
            '    <!-- Populated by JS: {skill_count} skill bars -->\n'
            '  </div>\n'
            '</section>'
        ),
    },

    "particle_canvas": {
        "type": "particle_canvas",
        "label": "Particle Canvas",
        "category": "media",
        "icon": "&#10022;",
        "description": "Background particle effect layer (3D or 2D).",
        "css_classes": ["particle-canvas"],
        "default_props": {
            "mode": "3d",
            "opacity": 0.35,
        },
        "prop_schema": [
            {"key": "mode",    "label": "Mode",    "type": "select", "options": ["2d", "3d"]},
            {"key": "opacity", "label": "Opacity", "type": "range", "min": 0, "max": 1},
        ],
        "slots": [],
        "html_template": (
            '<canvas id="particle-canvas" class="particle-canvas" '
            'style="position:fixed;inset:0;pointer-events:none;z-index:0;opacity:{opacity}"></canvas>'
        ),
    },

    "progress_tracker": {
        "type": "progress_tracker",
        "label": "Progress Tracker",
        "category": "display",
        "icon": "&#9632;",
        "description": "Stepped progress bar with labeled milestones.",
        "css_classes": [],
        "default_props": {
            "steps": "Start,Research,Build,Deploy,Complete",
            "current_step": 1,
            "tracker_id": "progress-tracker",
        },
        "prop_schema": [
            {"key": "steps",        "label": "Steps (comma-sep)", "type": "text"},
            {"key": "current_step", "label": "Current Step",      "type": "number", "min": 0},
            {"key": "tracker_id",   "label": "Element ID",        "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-progress-tracker" id="{tracker_id}">\n'
            '  {step_items}\n'
            '</div>'
        ),
    },

    "alert_banner": {
        "type": "alert_banner",
        "label": "Alert Banner",
        "category": "display",
        "icon": "&#9888;",
        "description": "Dismissible alert/notification banner.",
        "css_classes": [],
        "default_props": {
            "text": "System alert: something important happened.",
            "severity": "info",
            "banner_id": "alert-banner",
            "dismissible": True,
        },
        "prop_schema": [
            {"key": "text",        "label": "Text",        "type": "text"},
            {"key": "severity",    "label": "Severity",    "type": "select",
             "options": ["info", "warning", "danger", "success"]},
            {"key": "banner_id",   "label": "Element ID",  "type": "text"},
            {"key": "dismissible", "label": "Dismissible", "type": "boolean"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-alert ck-alert--{severity}" id="{banner_id}">\n'
            '  <span class="ck-alert__text">{text}</span>\n'
            '  {dismiss_btn}\n'
            '</div>'
        ),
    },

    "data_table": {
        "type": "data_table",
        "label": "Data Table",
        "category": "data",
        "icon": "&#9638;",
        "description": "Styled data table with header row.",
        "css_classes": [],
        "default_props": {
            "columns": "Name,Value,Status",
            "table_id": "data-table",
            "rows": 5,
        },
        "prop_schema": [
            {"key": "columns",  "label": "Columns (comma-sep)", "type": "text"},
            {"key": "table_id", "label": "Element ID",          "type": "text"},
            {"key": "rows",     "label": "Placeholder Rows",    "type": "number", "min": 0, "max": 20},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-table-wrap">\n'
            '  <table class="ck-table" id="{table_id}">\n'
            '    <thead><tr>{header_cells}</tr></thead>\n'
            '    <tbody>{body_rows}</tbody>\n'
            '  </table>\n'
            '</div>'
        ),
    },

    "image_display": {
        "type": "image_display",
        "label": "Image Display",
        "category": "media",
        "icon": "&#128444;",
        "description": "Styled image with optional caption and border glow.",
        "css_classes": [],
        "default_props": {
            "src": "/shared/img/placeholder.png",
            "alt": "Image",
            "caption": "",
            "glow_color": "",
            "max_width": "100%",
            "border_radius": "6px",
        },
        "prop_schema": [
            {"key": "src",           "label": "Image URL",     "type": "text"},
            {"key": "alt",           "label": "Alt Text",      "type": "text"},
            {"key": "caption",       "label": "Caption",       "type": "text"},
            {"key": "glow_color",    "label": "Glow Color",    "type": "color"},
            {"key": "max_width",     "label": "Max Width",     "type": "text"},
            {"key": "border_radius", "label": "Border Radius", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<figure class="ck-image" style="max-width:{max_width}">\n'
            '  <img src="{src}" alt="{alt}" '
            'style="width:100%;border-radius:{border_radius}{glow_style}">\n'
            '  {caption_html}\n'
            '</figure>'
        ),
    },

    "spacer": {
        "type": "spacer",
        "label": "Spacer",
        "category": "layout",
        "icon": "&#8597;",
        "description": "Vertical space between components.",
        "css_classes": [],
        "default_props": {
            "height": "20px",
        },
        "prop_schema": [
            {"key": "height", "label": "Height", "type": "text"},
        ],
        "slots": [],
        "html_template": '<div style="height:{height}"></div>',
    },

    "divider_line": {
        "type": "divider_line",
        "label": "Divider Line",
        "category": "layout",
        "icon": "&#9472;",
        "description": "Horizontal line separator with accent glow.",
        "css_classes": [],
        "default_props": {
            "color": "var(--accent, #06b6d4)",
            "opacity": "0.3",
        },
        "prop_schema": [
            {"key": "color",   "label": "Color",   "type": "color"},
            {"key": "opacity", "label": "Opacity", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<hr style="border:none;height:1px;background:{color};opacity:{opacity};'
            'box-shadow:0 0 8px {color}">'
        ),
    },

    # ── v1.49.0 [2026-03-21] — Scene factory components ──────────

    "custom_html": {
        "type": "custom_html",
        "label": "Custom HTML",
        "category": "layout",
        "icon": "&#60;&#47;&#62;",
        "description": "Raw HTML injection — escape hatch for scene-specific elements.",
        "css_classes": [],
        "default_props": {
            "html": '<div class="custom-block">Custom content here</div>',
            "comment": "Custom HTML block",
        },
        "prop_schema": [
            {"key": "html",    "label": "HTML Code",   "type": "textarea"},
            {"key": "comment", "label": "Comment",     "type": "text"},
        ],
        "slots": [],
        "html_template": "<!-- {comment} -->\n{html}",
    },

    "canvas_widget": {
        "type": "canvas_widget",
        "label": "Canvas Widget",
        "category": "media",
        "icon": "&#127912;",
        "description": "HTML canvas element for particles, animations, or visualizations.",
        "css_classes": [],
        "default_props": {
            "canvas_id": "scene-canvas",
            "width": "100%",
            "height": "160px",
            "background": "radial-gradient(ellipse, rgba(var(--accent-rgb)/.08), transparent)",
            "overlay": True,
        },
        "prop_schema": [
            {"key": "canvas_id",  "label": "Canvas ID",  "type": "text"},
            {"key": "width",      "label": "Width",      "type": "text"},
            {"key": "height",     "label": "Height",     "type": "text"},
            {"key": "background", "label": "Background", "type": "text"},
            {"key": "overlay",    "label": "Has Overlay", "type": "boolean"},
        ],
        "slots": ["overlay_content"],
        "html_template": (
            '<div class="ck-canvas-widget" style="position:relative;width:{width};height:{height};'
            'background:{background};border-radius:6px;overflow:hidden">\n'
            '  <canvas id="{canvas_id}" style="width:100%;height:100%"></canvas>\n'
            '  {overlay_html}\n'
            '</div>'
        ),
    },

    "hud_badge_row": {
        "type": "hud_badge_row",
        "label": "HUD Badge Row",
        "category": "display",
        "icon": "&#9670;",
        "description": "Horizontal row of metric badges (time, gold, heat, etc.).",
        "css_classes": [],
        "default_props": {
            "badges": "time:DUSK:&#127750;,gold:50g:&#128176;,heat:0/100:&#128293;,turn:0:&#9201;",
        },
        "prop_schema": [
            {"key": "badges", "label": "Badges (id:value:icon,...)", "type": "textarea"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-hud-badges">\n'
            '  {badge_items}\n'
            '</div>'
        ),
    },

    "toast_container": {
        "type": "toast_container",
        "label": "Toast Container",
        "category": "nav",
        "icon": "&#128172;",
        "description": "Mount point for toast notifications. Place once per scene.",
        "css_classes": [],
        "default_props": {
            "position": "bottom-center",
            "toast_id": "toast-container",
        },
        "prop_schema": [
            {"key": "position", "label": "Position", "type": "select",
             "options": ["top-right", "top-center", "bottom-right", "bottom-center"]},
            {"key": "toast_id", "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-toast-container ck-toast--{position}" id="{toast_id}"></div>'
        ),
    },

    "npc_roster": {
        "type": "npc_roster",
        "label": "NPC Roster",
        "category": "game",
        "icon": "&#9731;",
        "description": "Grid of NPC portraits with names, roles, and reputation bars.",
        "css_classes": [],
        "default_props": {
            "npcs": "Greta:Barkeeper:#f97316,Bard:Musician:#8b5cf6,Merchant:Trader:#22c55e,Stranger:???:#ef4444",
            "roster_id": "npc-roster",
        },
        "prop_schema": [
            {"key": "npcs",      "label": "NPCs (name:role:color,...)", "type": "textarea"},
            {"key": "roster_id", "label": "Element ID",                 "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-npc-roster" id="{roster_id}">\n'
            '  {npc_cards}\n'
            '</div>'
        ),
    },

    "timer_display": {
        "type": "timer_display",
        "label": "Timer / Clock",
        "category": "display",
        "icon": "&#9201;",
        "description": "Countdown timer or clock display with label.",
        "css_classes": [],
        "default_props": {
            "label": "TIME",
            "value": "--:--",
            "timer_id": "scene-timer",
            "style": "badge",
        },
        "prop_schema": [
            {"key": "label",    "label": "Label",      "type": "text"},
            {"key": "value",    "label": "Default Value", "type": "text"},
            {"key": "timer_id", "label": "Element ID",  "type": "text"},
            {"key": "style",    "label": "Style",       "type": "select",
             "options": ["badge", "large", "countdown"]},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-timer ck-timer--{style}" id="{timer_id}">\n'
            '  <span class="ck-timer__label">{label}</span>\n'
            '  <span class="ck-timer__value">{value}</span>\n'
            '</div>'
        ),
    },

    "button_group": {
        "type": "button_group",
        "label": "Button Group",
        "category": "input",
        "icon": "&#9776;",
        "description": "Horizontal or vertical group of action buttons.",
        "css_classes": [],
        "default_props": {
            "buttons": "Action 1:default:btn-1,Action 2:accent:btn-2,Action 3:danger:btn-3",
            "direction": "horizontal",
            "group_id": "btn-group",
        },
        "prop_schema": [
            {"key": "buttons",   "label": "Buttons (text:variant:id,...)", "type": "textarea"},
            {"key": "direction", "label": "Direction", "type": "select",
             "options": ["horizontal", "vertical"]},
            {"key": "group_id",  "label": "Group ID",  "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-btn-group ck-btn-group--{direction}" id="{group_id}">\n'
            '  {button_items}\n'
            '</div>'
        ),
    },

    "select_dropdown": {
        "type": "select_dropdown",
        "label": "Dropdown Select",
        "category": "input",
        "icon": "&#9660;",
        "description": "Styled dropdown selector with label.",
        "css_classes": [],
        "default_props": {
            "label": "Choose",
            "options": "Option A,Option B,Option C",
            "select_id": "scene-select",
        },
        "prop_schema": [
            {"key": "label",     "label": "Label",    "type": "text"},
            {"key": "options",   "label": "Options (comma-sep)", "type": "text"},
            {"key": "select_id", "label": "Element ID", "type": "text"},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-select-field">\n'
            '  <label class="ck-select-label">{label}</label>\n'
            '  <select class="ck-select" id="{select_id}">\n'
            '    {option_items}\n'
            '  </select>\n'
            '</div>'
        ),
    },

    "text_block": {
        "type": "text_block",
        "label": "Text Block",
        "category": "display",
        "icon": "&#84;",
        "description": "Styled text paragraph with optional heading.",
        "css_classes": [],
        "default_props": {
            "heading": "",
            "text": "Scene description or narrative text goes here.",
            "text_style": "body",
        },
        "prop_schema": [
            {"key": "heading",    "label": "Heading",    "type": "text"},
            {"key": "text",       "label": "Text",       "type": "textarea"},
            {"key": "text_style", "label": "Style",      "type": "select",
             "options": ["body", "narrative", "system", "emphasis"]},
        ],
        "slots": [],
        "html_template": (
            '<div class="ck-text-block ck-text--{text_style}">\n'
            '  {heading_html}\n'
            '  <p>{text}</p>\n'
            '</div>'
        ),
    },
}


# ──── Public API ──────────────────────────────────────────────────────────

def get_component(component_type: str) -> Optional[Dict[str, Any]]:
    """Return a deep copy of a component definition.

    Args:
        component_type: Component type identifier.

    Returns:
        Component definition dict, or None if not found.
    """
    comp = COMPONENTS.get(component_type)
    return copy.deepcopy(comp) if comp else None


def list_components() -> List[Dict[str, Any]]:
    """Return all component definitions for the palette.

    Returns:
        List of component dicts (deep copies).
    """
    return [copy.deepcopy(c) for c in COMPONENTS.values()]


def list_components_by_category() -> Dict[str, List[Dict[str, Any]]]:
    """Return components grouped by category.

    Returns:
        Dict mapping category ID to list of component dicts.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for comp in COMPONENTS.values():
        cat = comp.get("category", "other")
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(copy.deepcopy(comp))
    return grouped


def get_categories() -> List[Dict[str, Any]]:
    """Return the category list for palette UI.

    Returns:
        List of category dicts with id, label, icon.
    """
    return copy.deepcopy(CATEGORIES)


def get_component_count() -> int:
    """Return total number of registered components."""
    return len(COMPONENTS)
