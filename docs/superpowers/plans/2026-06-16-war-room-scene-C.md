# The Faction War Room (v1.63 sub-project C) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Reuse-first: a COMMAND surface over the existing managers (`TerritoryManager`, `FactionAI`, `CrewManager`, `faction_politics`) + the live emergent world. The player picks ONE faction and runs it; the other five are the emergent `FactionAI` rivals.

**Goal:** A new scene `war_room` (port **5598**) where the player chooses an allegiance and commands their faction — territory/power/treasury/rank dashboard, crew ops, district contests, HQ building, alliances/wars — all by calling the EXISTING managers. The player-faction contest gate (`PlayerState` allegiance) wired in B-T4 gets SET here.

**Architecture:** FlaskScene on 5598 (mirror `the_sprawl`/`executive_suite`). Read live state from `get_territory_manager()` / `get_faction_ai()` / `get_crew_manager()` / `faction_politics.FactionManager`; commands dispatch to those managers. Player allegiance persisted on `PlayerState` (small add) so both the War Room and the Sprawl/contest gate read it.

**Tech Stack:** Flask/Socket.IO scene, vanilla JS + design system. Live against the running core stack.

**Conventions:** reuse-first (no new faction/territory state); `# v1.63.0 [2026-06-16]` stamps; Oracle log `[war_room] …`; `get_config()`; proof-before-done (`launcher.py war_room` + headless, 0 console errors) against the live world; complete scene registration incl. `hub_flask._SCENE_PRESENTATION`.

---

### C-T1: Scaffold + register the scene
**Files:** `content/scenes/war_room/{__init__.py, war_room_scene.py, templates/war_room.html, static/css/war_room.css, static/js/war_room.js}`; register in `engine/control_plane_registry.py` SCENE_DEFS (`war_room`, flask, auto_start, pillar game), `engine/port_registry.py` (`war_room:5598` + HUB_CATALOGUE_TARGETS), `config/launcher.yaml` (scenes + game pillar), `content/scenes/hub/hub_scene.py` `_build_scene_categories`, `content/scenes/hub/hub_flask.py` `_SCENE_PRESENTATION` (REQUIRED). Mirror `the_sprawl_scene.py`. `SCENE_METADATA` accent e.g. `#ef4444`. Placeholder page.
- [ ] Boot `launcher.py war_room` → `/api/health` 200, `/` 200; in `--list` (auto-start) + hub imports clean (no KeyError); `oracle.py --errors` clean. Commit `feat(war_room): scaffold + register faction command scene (v1.63.0)`.

### C-T2: Allegiance + live dashboard backend
**Files:** `war_room_scene.py`; `engine/world/player_state.py` (add persisted `allegiance` get/set — minimal; saved to player_state.json; this is what B-T4's `_player_faction()` reads).
READ real signatures: `TerritoryManager` (`get_faction_ranking`, `get_faction_total_control`, `get_all_control`, `get_wars_active`, `get_hq(crew_id)`, `HQ_ROOM_TYPES`, `FACTION_TRAITS`), `FactionAI` (`get_faction_ai().get_history(faction,limit)`, `get_active_wars`, `get_stats`, `set_player_context`), `CrewManager` (`get_all_members`, `get_active_operations`, `compute_success_chance`), `faction_politics.FactionManager.get_instance().get/modify_standing`.
- `GET /api/warroom/factions` → the 6 with power/territory-total/treasury/relations + traits (for the allegiance picker).
- `POST /api/warroom/allegiance {faction}` → set `PlayerState.allegiance`; also set `FactionAI.set_player_context(standings, district)` so rivals react. Return state.
- `GET /api/warroom/state` → `{allegiance, my:{power,territory:[districts],treasury,rank,crews,hq}, rivals:[{faction,power,relation}], wars, recent_decisions:get_history(...), standings}`. Rank derived from `get_faction_total_control(allegiance)` thresholds.
- Socket push on `living_world_tick`/`territory_shift`/`faction_decision` → `warroom_update`.
- [ ] Unit-test the state assembler (mock managers) + persisted allegiance round-trip; live curl shows real faction data. Commit `feat(war_room): allegiance + live faction dashboard backend (v1.63.0)`.

### C-T3: Command center UI
**Files:** `war_room.html/css/js`.
Allegiance picker (first run) → then the dashboard: your faction crest/power/treasury/**rank ladder**, a territory list/mini-map of districts you control (reuse the Sprawl's faction colors), crew roster (from CrewManager), a **rivals panel** (other 5 with power + ally/war status), and a live **intel feed** of `FactionAI` rival decisions + territory shifts. Neon war-room aesthetic (red accent). Live-update on `warroom_update`.
- [ ] Live (headless): picker sets allegiance; dashboard renders real power/territory/rivals/crews/feed; rival decisions stream; 0 console errors. Screenshot. Commit `feat(war_room): command-center dashboard UI (v1.63.0)`.

### C-T4: Commands (dispatch to existing managers)
**Files:** `war_room_scene.py`, `war_room.js`.
`POST /api/warroom/command {cmd, ...}` → dispatch defensively:
- `contest {district}` → `TerritoryManager.shift_control(district, allegiance, delta∈CONTROL_SHIFT_RANGE, reason="war_room", source_faction=allegiance)`.
- `assign_op {op_type, crew:[ids]}` → `CrewManager.start_operation(...)` (+ `compute_success_chance` preview in the UI).
- `build_hq {district}` / `upgrade_room {room_type}` → `TerritoryManager.establish_hq(district, crew_id)` / `build_room`/`upgrade_room` (treasury-gated).
- `diplomacy {target_faction, kind}` → `faction_politics` set relation / `FactionAI` war + `modify_standing`.
Each returns a result + emits a `warroom_update`/feed event; treasury/rank update; rivals (FactionAI) respond on subsequent ticks. UI: command buttons with confirm + result toasts; disable when unaffordable/ineligible.
- [ ] Live: pick a faction; contest a district → control rises for it; assign a crew op → it runs; build an HQ → appears; declare war → relation flips + rivals react. 0 console errors. Screenshot. Commit `feat(war_room): faction commands via existing managers (v1.63.0)`.

### C-T5: Integration verify + changelog
- [ ] Full live run against the stack: pick allegiance, command (contest/op/HQ/diplomacy), watch rivals + territory respond, rank rise. Headless 0 console errors; `oracle.py` clean; `pytest tests/test_war_room*.py tests/test_emergent_*.py -q` green; confirm the Sprawl's contest gate now works (allegiance set). CHANGELOG `## [1.63.0]` War Room subsection + README row. Commit `docs(war_room): v1.63.0 changelog (v1.63.0)`.

## Self-review
- Reuse-first: all faction/territory/crew/diplomacy state via existing managers; only NEW state is the player's persisted `allegiance`. ✓
- Registration completeness incl. `hub_flask._SCENE_PRESENTATION`. ✓
- Closes the B-T4 loop (allegiance set → Sprawl contest enabled). ✓
