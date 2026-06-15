# Emergent Simulation Engine (v1.63 sub-project A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. Builds on the approved spec `docs/superpowers/specs/2026-06-15-emergent-living-world-v163-design.md`. This is the FOUNDATION; scenes B (Sprawl), C (War Room), D (Exchange) get their own plans and consume this engine.

**Goal:** A persistent, tick-driven engine where NPCs pursue prioritized goals via a hybrid utility planner (reusing v1.62 systems as action verbs), factions win/lose territory & power, crews form and betray, and consequences persist — all without overloading the local model.

**Architecture:** New package `engine/world/emergent/` with focused modules (store, factions, goals, planner, crews, consequences, engine). It EXTENDS existing singletons rather than replacing them: `get_world_sim()` (event daemon + `on_event`/`SimEvent`), `get_crew_manager()` (ops/loyalty/success-chance), `get_player_state()` (credits/heat/faction_standings — factions: OmniCorp, NeoTech, BlackMarket, Ghost_Net, SynthSec, DeepState), and the v1.62 verbs (`get_comms_log()`, `relationship_effects.apply_*`, `phone_hack`, `get_phone_os()`). Persistence copies the `comms_log.py` SQLite-WAL-singleton pattern. `Database` (`content/simulation/database/db.py`) gives `get_or_create_relationship`/`update_relationship`/`get_all_characters`.

**Tech Stack:** Python 3.13, SQLite (WAL), threading (own daemon + lock), pytest. Hybrid generation (mostly rule/utility, sparse LLM via the npc_comms pattern).

**Conventions:** module headers + Change Log + `# v1.63.0 [2026-06-15]` stamps; Oracle log format `[emergent] … (operation=…)`; `get_config()` for ALL cadence/weights (`emergent.*`); types + Google docstrings; pytest plain assert + mock external (Database/LLM/verbs) at the boundary; defensive (a sim failure never crashes a scene). Use `.venv\Scripts\python.exe`. Windows.

---

### Task A1: Persistent sim store
**Files:** Create `engine/world/emergent/__init__.py`, `engine/world/emergent/store.py`; Test `tests/test_emergent_store.py`.
Copy the `comms_log.py` pattern: SQLite WAL, path from `get_config().get("emergent.store.db_path","data/emergent.db")` via `engine.paths.ROOT`, single `threading.Lock`, lazy singleton `get_emergent_store()`, all ops defensive (log Oracle-format, never raise).
Tables: `faction_state(faction_id PK, power REAL, treasury INTEGER, data TEXT json)`, `territory(district_id PK, faction_id, contested INTEGER, data TEXT)`, `npc_goal(npc_id, goal_type, target, priority REAL, progress REAL, data TEXT, PRIMARY KEY(npc_id,goal_type,target))`, `world_event(id PK AUTOINCREMENT, ts, kind, actor, summary, payload TEXT json, persistent INTEGER)`.
API (typed): `upsert_faction/get_faction/all_factions`, `set_territory/get_territory/all_territory`, `set_goals(npc_id, goals:list)/get_goals(npc_id)`, `log_event(kind,actor,summary,payload,persistent=True)->int / recent_events(limit)`, plus `reset()` for tests.
- [ ] Write `tests/test_emergent_store.py`: faction upsert+read round-trips; territory set/get; goals replace-by-npc; event append+recent; concurrent writes (8 threads) don't corrupt; explicit-path constructor isolates from real db.
- [ ] Run `… -m pytest tests/test_emergent_store.py -q -o addopts=""` → FAIL (module missing).
- [ ] Implement `store.py` (mirror comms_log).
- [ ] Run the test → PASS.
- [ ] Commit: `feat(emergent): persistent sim store (SQLite WAL) (v1.63.0)`.

### Task A2: Faction model (territory / power / treasury / relations)
**Files:** Create `engine/world/emergent/factions.py`; Test `tests/test_emergent_factions.py`.
`FACTIONS = ["OmniCorp","NeoTech","BlackMarket","Ghost_Net","SynthSec","DeepState"]` (match `player_state._FACTION_NAMES` EXACTLY). `FactionRegistry` (singleton `get_factions()`) backed by the store: each faction has `power` (0–100), `treasury`, `territory` (set of district ids — seed from `engine/control_plane_registry` districts / a defined district list), `relations` (dict faction→{ally|war|neutral}). Methods: `seed_if_empty()`, `power_of/territory_of/treasury_of`, `shift_power(fid,delta)`, `flip_territory(district,new_fid,by)` (logs a world_event, persistent), `set_relation(a,b,kind)`, `recovery_tick()` (config `emergent.faction.recovery_floor` nudges crushed factions up so the world never flat-lines — WITHOUT undoing player-meaningful flips). Clamp power; treasury ≥0.
- [ ] Test: seed creates 6 factions; shift_power clamps; flip_territory reassigns + emits a persistent event + updates both factions' territory sets; recovery_tick lifts a 0-power faction toward the floor but leaves a healthy one; relations symmetric.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): faction territory/power/treasury model (v1.63.0)`.

### Task A3: NPC goals
**Files:** Create `engine/world/emergent/goals.py`; Test `tests/test_emergent_goals.py`.
`@dataclass Goal{type:str,target:str,priority:float,progress:float}`. Goal types: `wealth, rank, romance, revenge, lay_low, territory`. `generate_goals(npc_id, *, ctx) -> list[Goal]`: derive from inputs passed in (so it's pure/testable) — relationship signals (`Database.get_or_create_relationship`), faction membership (`faction_context._get_character_faction`), player-state-like heat, and stats; e.g. high heat → `lay_low` top; a strong negative relationship → `revenge(target)`; faction member + ambition → `rank`; always a baseline `wealth`. `reprioritize(goals, outcome)` bumps/decays after an action. Keep weights in `get_config().get("emergent.goals.*")`.
- [ ] Test (pure, mock ctx): high heat ⇒ lay_low is highest; a -0.8 relationship ⇒ a revenge goal targeting that npc; faction member ⇒ rank present; everyone has wealth; reprioritize raises a satisfied goal's… (decays it) and is deterministic with a seed.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): NPC goal generation + prioritization (v1.63.0)`.

### Task A4: Hybrid utility planner
**Files:** Create `engine/world/emergent/planner.py`; Test `tests/test_emergent_planner.py`.
`plan_action(npc_id, *, goals, ctx, rng) -> PlannedAction{verb, target, params, use_llm}`. Build candidate actions per top goals, score each by a utility = goal_priority × fit × feasibility (config weights `emergent.planner.*`), pick the argmax (rng tiebreak). Verb vocabulary maps to v1.62 systems (the planner returns the choice; a thin `execute(action)` dispatches): `message`/`leave_message`→`npc_comms` helpers, `hack`→`phone_hack`, `trade`→economy hook (A7/D), `form_crew`/`join_crew`/`run_job`/`betray`→`get_crew_manager()`, `move`→player_state/location, `contest_territory`→factions.flip attempt, `romance`→`relationship_effects.apply_exchange_effect`. `use_llm` true only for pivotal actions, gated by `emergent.planner.llm_chance` (mirror `npc_comms._is_important`). `execute()` is defensive and returns a result dict; DO NOT call the LLM inline in unit tests (inject/mocked).
- [ ] Test (mock the verb modules): a `lay_low` NPC does NOT pick `hack`/`contest` (low feasibility when hot); a `wealth` NPC prefers `trade`/`run_job`; a `revenge` NPC with a hostile target picks `hack` or `betray`; llm gating respects chance=0 (never use_llm) and chance=1 for a pivotal action; `execute` routes each verb to the right (mocked) system and never raises on failure.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): hybrid utility planner + verb dispatch (v1.63.0)`.

### Task A5: Crews & betrayal
**Files:** Create `engine/world/emergent/crews.py`; Test `tests/test_emergent_crews.py`.
Thin emergent layer over `get_crew_manager()`: `form_or_join(npc_id, goal)` (groups goal-aligned NPCs into a crew via existing recruit/ops), `run_job(crew, op_type)` → uses `start_operation`/`compute_success_chance`/`check_operations`; `maybe_betray(npc_id, crew)` → if member loyalty < `emergent.crew.betray_loyalty` and a payoff exists, trigger betrayal: leave crew + standing/relationship hit via `relationship_effects.apply_pair_delta` + a persistent world_event. Reuse the real crew op grading (don't reinvent).
- [ ] Test (mock CrewManager + Database): form_or_join recruits aligned members; run_job calls start_operation with the right crew + returns the graded outcome; low-loyalty member betrays (emits event, applies negative pair delta), high-loyalty doesn't; betrayal is bounded.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): emergent crews + loyalty-driven betrayal (v1.63.0)`.

### Task A6: Consequences & world-event feed
**Files:** Create `engine/world/emergent/consequences.py`; Test `tests/test_emergent_consequences.py`.
`apply(event) -> None`: translate a planned-action result / faction-flip / betrayal into PERSISTENT deltas (store.log_event(persistent=True), faction power/territory, player standing via `player_state.update_faction_standing`, economy hooks) AND fan it to the live feed: `get_world_sim()` (construct a `SimEvent` + the daemon's `on_event` subscribers) and optionally `get_comms_log().log(channel='world',…)` so the Oracle/Mail can surface it. `schedule(delay_ticks, fn)` + `due()` for delayed consequences (debt comes due, retaliation) — reuse the v1.62 consequence shape.
- [ ] Test: apply(faction_flip) persists territory + emits a SimEvent to a registered on_event spy; apply(betrayal) shifts standings; scheduled consequence fires only after its tick; feed emission is best-effort (a failing sink doesn't break apply).
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): persistent consequences + world-event feed (v1.63.0)`.

### Task A7: EmergentSim engine + world tick (wires it together)
**Files:** Create `engine/world/emergent/engine.py`, `engine/skills/builtin/emergent_skills.py`; Modify `config/default.yaml` (`emergent.*`); Test `tests/test_emergent_engine.py`. Wire startup where `WorldSim`/schedulers start (find the core start path — likely a scene lifecycle or `start_world_sim()` caller; mirror how `npc_comms` is started from the phone scene).
`EmergentSim` (singleton `get_emergent_sim()`): own daemon thread + own lock + `_stop_event.wait(interval)` (cadence `emergent.tick_interval`, default ~20s). Each tick: pick up to `emergent.active_npcs_per_tick` active NPCs (enumerate via `Database.get_all_characters()` + roster fallback), for each → `generate_goals`→`plan_action`→`execute`→`consequences.apply`; then `factions.recovery_tick()` + an economy step; respect TaskQueue/llm caps. `start()/stop()` (guard: enabled + ≥2 NPCs; never busy-wait). A minimal economy step here (NPC wealth goals nudge prices) — the FULL Exchange is sub-project D. `emergent_skills.py`: `@skill(pack="emergent")` to query world state + nudge (e.g. `world_status`, `faction_report`, `incite(faction)`), for scenes/agents.
- [ ] Test (short, mocked verbs/LLM, tiny interval, explicit-path store): one tick advances ≥1 NPC through goal→plan→execute→consequence; N ticks evolve faction power/territory + emit events; the tick never calls the LLM when `llm_chance=0`; start/stop is clean (thread joins, no busy-wait); engine survives a verb raising.
- [ ] Run → FAIL → implement → PASS.
- [ ] Live (LMStudio up): `… launcher.py phone` (or the core start) with emergent enabled; let it run ~90s headless; dump `get_emergent_store().all_factions()` + `recent_events()` → territory/power/relationships visibly shifted, mostly template actions, LLM rate ≈ `llm_chance` (model calm). Save to `docs/superpowers/artifacts/a7-emergent.txt`. `oracle.py --errors` clean.
- [ ] Commit `feat(emergent): EmergentSim world tick + skills + wiring (v1.63.0)`.

### Task A8: Integration verification + tuning + changelog
- [ ] Full emergent suite green: `… -m pytest tests/test_emergent_*.py -q -o addopts=""`.
- [ ] Run the broad smoke (`… -m pytest tests/ --smoke-only -q -o addopts=""`) to confirm the new daemon/wiring doesn't break other domains.
- [ ] Tune `emergent.*` weights/cadence from the live run (balance: world evolves but doesn't monopolize/flat-line; model calm). Document the knobs.
- [ ] CHANGELOG `## [1.63.0]` (start the entry; B/C/D append) + a README Features row (use the v1.62.1 extend-marker pattern). `oracle.py` clean.
- [ ] Commit `docs(emergent): v1.63.0 changelog + engine tuning notes (v1.63.0)`.

## Self-review
- Spec coverage: goals→A3, hybrid planner→A4, factions/territory/power→A2, crews/betrayal→A5, consequences/persistence/feed→A6+A1, world tick/engine→A7, economy seed→A7 (full Exchange = sub-project D), perf caps→A4/A7 config. ✓
- No placeholders: each task has concrete files, signatures, schema, and representative test assertions; integration points name real singletons/signatures from the audit. The few "find the core start path"/"district list" items are explicit lookups, not vague code.
- Type consistency: `get_emergent_store`, `get_factions`, `get_emergent_sim`, `Goal`, `PlannedAction` used consistently; faction ids match `player_state._FACTION_NAMES`.
