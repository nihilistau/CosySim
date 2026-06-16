# CosySim v1.63 — "Emergent Living World" — Design Spec (REUSE-FIRST, revised)

**Date:** 2026-06-15
**Status:** Awaiting review (revised after discovering the existing world-sim substrate)
**Builds on:** v1.62 "Living City" + the EXISTING world simulation: `LivingWorld`, `TerritoryManager`, `FactionAI`, `Market`, `RoutineManager`, `faction_politics`, plus v1.62's `comms_log`/`npc_comms`/`relationship_effects`/`phone_hack`/`phone_os`/`CrewManager`.

## Premise
v1.62 made the city talk; v1.63 makes it **act** — at the level of *individual NPCs pursuing personal goals*. Crucially, **most of the world substrate already exists** and is REUSED, not rebuilt.

## What already exists (REUSE — do not duplicate)
- **`LivingWorld`** (`get_living_world()`) — the orchestrator daemon (60s tick): drives `RoutineManager` (NPC movement), `FactionAI.tick()` (every 5th), `Market.tick()`, weather, world events. **This is the loop we hook into.**
- **`TerritoryManager`** (`get_territory_manager()`) — district control %, `shift_control`, `simulate_faction_tick`, wars, `CrewHQ`/`HQRoom`, persistence. **Owns territory/power/wars.**
- **`FactionAI`** (`get_faction_ai()`) — autonomous, player-aware faction strategy. **Owns faction-level decisions.**
- **`Market`** (`get_market()`) — full economy (supply/demand, prices, buy/sell, contracts, territory pricing, event shocks). **This IS The Exchange engine.**
- **`RoutineManager`**, **`faction_politics.FactionManager`** (player↔faction standing).

## The genuine v1.63 gap (what we BUILD)
1. **Per-NPC goal→verb agency** — nothing drives *individual* NPCs to pursue personal goals via the v1.62 verbs. `FactionAI` is faction-level; `RoutineManager` only schedules movement. New: NPCs get goals (wealth/rank/revenge/romance/lay_low/territory) and a hybrid utility planner that makes them *act* (message, hack, trade, form/betray crew, contest a district via `TerritoryManager.shift_control`, romance) on the `LivingWorld` tick.
2. **The Sprawl** & **The Faction War Room** — two new scenes that surface (and let the player drive) the existing TerritoryManager/FactionAI/Market/routines + the new agency feed.
3. **The Exchange** — *surface the existing `Market`* in The Grid + a new OS Markets app (no new economy engine).
4. **Persistence + unification** — persist NPC goals/agency across sessions (SQLite); optionally fold the parallel scripted `WorldSim` events into `LivingWorld` so there's one coherent loop.

## Decisions locked
Hybrid planner + sparse LLM · War Room = pick one faction & run it · Sprawl = avatar walks · consequences fully persistent · **reuse existing managers; the engine is a thin orchestrator, not a parallel sim.**

## Conventions
Reuse-first (CLAUDE.md rule 2); extend `LivingWorld`/`TerritoryManager`/`Market`, never reimplement; module headers + `# v1.63.0` stamps; Oracle log format; `get_config()` for all knobs; pytest + mock at boundary; proof-before-done; hybrid + caps for model load.

---

## Decomposition (build A first)

### A · NPC Goal→Verb Agency layer  *(the new brain; thin orchestrator)*
`engine/world/emergent/` — REUSE-FIRST:
- **`store.py`** (already built, to be SLIMMED): persist **NPC goals** + an **agency-event log** (the genuinely-new state). Faction/territory tables are RETIRED — `TerritoryManager` owns those.
- **`goals.py`**: generate/prioritize per-NPC goals from stats/relationships (`Database.get_or_create_relationship`), faction standing (`faction_politics`), heat (`player_state`).
- **`planner.py`**: hybrid utility planner → action over goals; verbs dispatch to EXISTING systems: message/leave-message (`npc_comms`), hack (`phone_hack`), trade/contract (`Market`), form/join/run-job/**betray** (`CrewManager`), move (`RoutineManager`/location), **contest territory (`TerritoryManager.shift_control`)**, romance (`relationship_effects`). Sparse LLM (gated, own budget).
- **`agency.py` / engine hook**: a per-tick driver REGISTERED WITH `LivingWorld` (hook its tick, or `add_listener`) — runs goal→plan→execute for up to N active NPCs/tick, persists goals/events, emits agency events to the EXISTING feed (LivingWorld event log / EventBus / `comms_log`) so the Oracle & scenes pick them up. Reads TerritoryManager/FactionAI/Market for context.
- **Retire** `factions.py` (A2) — delegate to `TerritoryManager` + `faction_politics`.
- **Verify:** goal/planner units (mock verbs); a driver tick makes NPCs act via the (mocked) existing managers; live — NPCs visibly pursue goals (trades move Market, contests move TerritoryManager) with the model calm; no parallel sim.

### B · The Sprawl  *(new scene — living city map)*
Registered like `executive_suite`. Neon district map reading **TerritoryManager** control % (shaded territory), NPC tokens from **RoutineManager** locations + agency events, a live feed from the agency/world event log, **FactionAI** activity, and the **player avatar** that travels + intervenes (intercept/recruit/deal/hack/fight via v1.62 verbs). Surfaces existing data; player actions call existing managers.
- **Verify:** boots/registered; map renders live territory + NPC movement + events; avatar can act; 0 console errors.

### C · The Faction War Room  *(new scene — play as a faction)*
Pick allegiance (one of 6). Dashboard reads **TerritoryManager** (control/ranking/HQs/wars), **FactionAI** (rival decisions), **CrewManager** (your crews/ops), **faction_politics** (standing). Player commands by calling EXISTING managers: assign a crew an op (`CrewManager.start_operation`), contest a district (`TerritoryManager.shift_control`), build/upgrade an HQ (`establish_hq`/`build_room`), broker alliance/war (`faction_politics`/`FactionAI`). Rivals are the emergent FactionAI. Rise in rank as control grows.
- **Verify:** boots/registered; pick faction; issue a crew op + contest a district → existing managers resolve it, control/ranking update, rivals act back; 0 console errors.

### D · The Exchange  *(surface existing Market — two UIs)*
No new economy. Surface `Market` in **The Grid** (deepen: live prices/contracts/broker from `Market`) and a new **Markets app in Executive Suite OS** (tickers, positions, contracts) — both over the one `Market` singleton. NPC `wealth` goals (from A) trade through `Market`, moving prices that both UIs show.
- **Verify:** both UIs read the same `Market`; an NPC trade (from A) moves prices visible in both; player buy/sell works in each.

## Reconciliation of already-built A1/A2 (this revision)
- **Keep** `store.py` but slim to `npc_goal` + `world_event` (agency feed); drop `faction_state`/`territory` tables+methods + their tests. Remove `emergent.faction.*` config.
- **Delete** `factions.py` + `test_emergent_factions.py` (duplicated `TerritoryManager`).
- Commit as a reuse-first reconciliation before continuing.

## Risks
Model load (hybrid+caps); two parallel daemons (`LivingWorld` vs scripted `WorldSim`) — consider unifying so agency events don't collide; balance (utility weights, contest magnitudes via `TerritoryManager.CONTROL_SHIFT_RANGE`); scope (A + 2 scenes + 2 Exchange UIs, but far smaller now that managers are reused).

## Verification (whole release)
NPCs pursue goals by acting through the EXISTING managers (trades move Market, contests move Territory, betrayals shift relationships) with the model calm; The Sprawl shows it live + avatar intervenes; the War Room runs a faction via existing managers with emergent rivals; The Exchange surfaces Market in Grid + OS; suite green; CHANGELOG `## [1.63.0]` + README Features row.
