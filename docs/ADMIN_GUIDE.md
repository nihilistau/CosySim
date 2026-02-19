# 🎛️ Admin Panel Guide

## Overview

The CosySim Admin Panel is a multi-panel diagnostic and control center built with Streamlit.

**Launch:** `python launcher.py --mode admin` (port 8502)

---

## Architecture

The admin panel is a thin router (`admin_panel.py`, ~120 lines) that delegates to 12 page modules in `content/scenes/admin/pages/`.

```
admin_panel.py          → Sidebar navigation, session state init
pages/
├── dashboard.py        → System overview + health
├── logs.py             → Log viewer + benchmarks
├── chains.py           → EventChain browser
├── config_editor.py    → Interactive config editing
├── rag_editor.py       → RAG message editor
├── god_mode.py         → Full override access
├── character_manager.py→ Character CRUD
├── scene_manager.py    → Scene registry
├── media.py            → Media gallery
├── lmstudio.py         → LMStudio management
├── backup.py           → Backup & restore
└── assets.py           → Asset browser
```

Each page exports a `render()` function.

---

## Pages

### 📊 Dashboard

The landing page shows:
- **Service Health** — green/red indicators for LMStudio, ComfyUI, Database, EventChain
- **System Metrics** — CPU%, RAM, GPU VRAM via SystemMonitor
- **Loaded Model** — name + parameter count from LMStudio
- **Benchmark Summary** — table of operations with avg/p95/max timings

### 📋 Logs

- **File logs** — reads from disk log files
- **Ring buffer** — recent in-memory entries from CosyLogger
- **Benchmark table** — timing statistics
- **Filters** — level (DEBUG/INFO/WARNING/ERROR), search text
- **Export** — download as JSON/CSV

### 🔗 EventChain Browser

- Browse chains with filters: scene, character, event type, date
- **Tree view** — recursive display showing causal hierarchy (parent_id → child events)
- Event icons by type (📨 message, 🧠 llm_request, 💾 memory, etc.)
- Click to expand full JSON payload

### ⚙️ Config Editor

- Organized by YAML section (system, scenes, llm, media_standards)
- **Type-aware inputs** — booleans as toggles, numbers as sliders, strings as text
- **Validation** — red border + message for invalid values
- **Save & Apply** — writes to YAML, reloads ConfigManager singleton
- **Env var indicator** — shows which values are overridden by environment

### ✏️ RAG Editor

Edit stored conversations, memories, and interactions.

**Logic Guards:**
- Cannot submit empty messages
- Cannot change event_type
- Cannot set character_id to non-existent character
- Cannot edit events older than threshold (unless GOD mode)
- All edits logged as `rag_edit` events in EventChain

### 🔴 GOD Mode

Password-protected full override access (default password: `cosysim`).

**Capabilities:**
| Feature | Description |
|---------|-------------|
| Raw SQL | Execute arbitrary queries on the database |
| Event Injection | Insert events into any chain |
| Force State | Override character mood, arousal, relationship values |
| DB Browser | View any table with pagination |
| Danger Zone | Clear all events, conversations, or specific tables |

**Safety:**
- Red banner when active: "⚠️ GOD MODE ACTIVE"
- All actions logged as `god_mode_action` events in EventChain
- Cannot be accidentally triggered (requires explicit password entry)

---

## Session State

Shared via `st.session_state`:

| Key | Type | Purpose |
|-----|------|---------|
| `asset_manager` | AssetManager | Asset CRUD |
| `config` | ConfigManager | Configuration access |
| `god_mode` | bool | GOD mode toggle |

---

## Adding a New Page

1. Create `pages/my_page.py` with a `render()` function
2. Add to `_PAGES` dict in `admin_panel.py`:
   ```python
   _PAGES = {
       ...
       "🆕 My Page": my_page.render,
   }
   ```
3. Import at top of `admin_panel.py`

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `R` | Refresh / rerun |
| `Ctrl+C` | Stop admin panel |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Module not found" errors | Ensure you're in the CosySim root and conda env is active |
| Dashboard shows all services down | Services need to be running independently |
| Config changes not taking effect | Click "Save & Apply" — changes write to YAML and reload singleton |
| GOD mode password forgotten | Default is `cosysim` (hardcoded in `god_mode.py`) |
