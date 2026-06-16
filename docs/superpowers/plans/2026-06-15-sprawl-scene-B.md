# The Sprawl (v1.63 sub-project B) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Builds on the approved reuse-first spec + the now-live emergent engine (sub-project A) and the populated world (20 factioned NPCs). The Sprawl is a SURFACE onto existing systems — it renders live data and lets the player intervene; it does NOT own world state.

**Goal:** A new neon city-map scene `the_sprawl` showing the living world in real time — faction territory shading, NPC tokens moving, a live emergent-event feed, and the player avatar traveling district→district and intervening — all read from the existing managers + the agency feed.

**Architecture:** New Flask scene (registered like `executive_suite`) on port **5597**. Frontend reads live data over Socket.IO + REST; the player's actions call the EXISTING managers (travel = `player_state.set_location`; intervene = v1.62 verbs / district actions). Reuse: `get_territory_manager()` (`get_all_control`, `get_faction_ranking`, `get_event_history`), `get_routine_manager()` (`get_npc_location`, `list_npcs`), `get_emergent_store().recent_events()` + the `emergent_action`/`living_world_tick` EventBus events, `Database.get_all_characters()` (names/factions/traits), `player_state`. Districts: `territory.DISTRICT_NAMES` (DOWNTOWN/COMBAT_ZONE/HIGHRISE/UNDERWORLD/TECH_DISTRICT/OUTSKIRTS) + `DISTRICT_SCENES` mapping.

**Tech Stack:** Python Flask/Socket.IO scene (FlaskScene base), vanilla JS + the CosySim design system, SVG/canvas map. Live data from the running core stack (Nexus/neoncity up).

**Conventions:** reuse-first (no new world state); `# v1.63.0 [2026-06-15]` stamps; Oracle log format `[the_sprawl] …`; `get_config()`; vanilla JS 2-space/single-quote, Jinja2; proof-before-done (`launcher.py the_sprawl` + chrome-devtools/headless console, 0 uncaught errors); reuse `executive_suite` patterns for shell/registration.

---

### B-T1: Scaffold + register the scene
**Files:** `content/scenes/the_sprawl/{__init__.py, the_sprawl_scene.py, templates/the_sprawl.html, static/css/the_sprawl.css, static/js/the_sprawl.js}`; modify `engine/control_plane_registry.py` (SCENE_DEFS), `engine/port_registry.py` (_DEFAULT_PORTS `the_sprawl:5597` + HUB_CATALOGUE_TARGETS), `config/launcher.yaml` (scenes + game pillar auto_start), `content/scenes/hub/hub_scene.py` (_build_scene_categories) + `content/scenes/hub/hub_flask.py` (_SCENE_PRESENTATION — REQUIRED so the hub doesn't KeyError, the lesson from executive_suite).
Mirror `content/scenes/executive_suite/executive_suite_scene.py` (FlaskScene subclass, `SCENE_METADATA` name/display_name/port 5597/type game/accent, `__init__(config=None, host=...)`, `register_bench_route`, routes, socketio). Placeholder page first.
- [ ] Boot: `… launcher.py the_sprawl` → `/api/health` 200, `/` 200; appears in `--list` (auto-start) + TUI + hub (no KeyError). `oracle.py --errors` clean. Commit `feat(the_sprawl): scaffold + register living-map scene (v1.63.0)`.

### B-T2: Live data backend (read-only endpoints + socket push)
**Files:** `the_sprawl_scene.py`.
Endpoints over the EXISTING managers: `/api/sprawl/state` → `{districts:[{id,control:{faction:pct},dominant,contested}], factions:get_faction_ranking(), npcs:[{id,name,sex,faction,district,activity}], player:{location,credits,heat}}`; `/api/sprawl/events?since=` → merged `get_emergent_store().recent_events()` + `get_territory_manager().get_event_history()`. Subscribe to EventBus `living_world_tick`/`emergent_action`/`territory_shift` and push `sprawl_update`/`sprawl_event` over Socket.IO. Defensive; never 500.
- [ ] Unit-test the state assembler (mock managers) + a live curl showing real territory/NPC/event data from the running stack. Commit `feat(the_sprawl): live world-state + event endpoints (v1.63.0)`.

### B-T3: The map UI (territory + NPC tokens + feed)
**Files:** `the_sprawl.html`, `the_sprawl.css`, `the_sprawl.js`.
A stylized 6-district neon map (SVG): each district shaded by dominant faction (color) + contested hatching, NPC tokens placed by district (hover → name/faction/activity), a live **City Pulse** event ticker (from `sprawl_event`), and a faction-power leaderboard. Live-update on `sprawl_update`. Reuse the design-system palette + the executive_suite skyline aesthetic.
- [ ] Live (chrome-devtools): map renders real territory shading + NPC tokens + a streaming event; territory visibly shifts when a contest fires; 0 uncaught console errors. Screenshot. Commit `feat(the_sprawl): living city map UI (v1.63.0)`.

### B-T4: Player avatar + intervene
**Files:** `the_sprawl.js`, `the_sprawl_scene.py`.
Player avatar marker on the map at `player.location`; **travel** (click a district → `POST /api/sprawl/travel` → `player_state.set_location` + energy/time) moves the avatar. **Intervene** on a district/NPC/event: a small action menu wired to existing verbs (talk → relationships/`npc_comms`, hack → `phone_hack`, deal → `Market`, recruit → `CrewManager`, contest → `TerritoryManager.shift_control` for the player's faction). Each action returns a result + emits an event to the feed.
- [ ] Live: travel moves the avatar; an intervene action calls the real manager (e.g. a player contest shifts control); 0 console errors. Screenshot. Commit `feat(the_sprawl): player avatar travel + intervene (v1.63.0)`.

### B-T5: Integration verify + changelog
- [ ] `launcher.py the_sprawl` full run against the live stack: map alive (NPCs move, territory shifts from the agency), avatar travels + intervenes, feed streams. `browser_test`/headless 0 console errors; `oracle.py` clean; affected tests green.
- [ ] CHANGELOG `## [1.63.0]` — add The Sprawl bullet; README Features row note. Commit `docs(the_sprawl): v1.63.0 changelog (v1.63.0)`.

## Self-review
- Reuse-first: every datum is read from an existing manager/the agency feed; no new world state. ✓
- Registration completeness incl. `hub_flask._SCENE_PRESENTATION` (the executive_suite KeyError lesson). ✓
- Verification is live against the running core stack. ✓
