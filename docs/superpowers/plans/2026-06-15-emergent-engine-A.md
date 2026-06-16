# NPC Goal→Verb Agency Layer (v1.63 sub-project A) — Implementation Plan (REUSE-FIRST, revised)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. Revised after discovering the existing world-sim substrate — this layer is a THIN ORCHESTRATOR that adds per-NPC goal-driven agency on top of the EXISTING `LivingWorld`/`TerritoryManager`/`FactionAI`/`Market`/`CrewManager`/`RoutineManager` + v1.62 verbs. It does NOT re-implement factions/territory/economy/loop.

**Goal:** Individual NPCs pursue personal goals (wealth/rank/revenge/romance/lay_low/territory) and ACT on them through existing systems — trades move `Market`, contests move `TerritoryManager`, betrayals shift relationships — driven on the existing `LivingWorld` tick, hybrid (rule-first, sparse LLM), persisted across sessions.

**Architecture:** `engine/world/emergent/` = `store.py` (DONE — persists `npc_goal` + `world_event`), `goals.py` (generate/prioritize goals), `planner.py` (utility planner → action, verbs dispatch to existing managers), `agency.py` (per-tick driver subscribed to the `LivingWorld` loop). Reuses: `get_territory_manager().shift_control(district,faction,delta,reason,source_faction)`, `get_market()` buy/sell/contracts, `get_crew_manager().recruit/start_operation`, `npc_comms` exchange, `phone_hack.hack_phone`, `relationship_effects.apply_exchange_effect`, `Database.get_or_create_relationship`, `faction_context._get_character_faction`, `player_state`. Feed: emit to the existing EventBus/`comms_log`/`LivingWorld` event log (no new feed daemon).

**Tech Stack:** Python 3.13, SQLite (store done), pytest. Hybrid + caps via `get_config().get("emergent.*")`.

**Conventions:** reuse-first; `# v1.63.0 [2026-06-15]` stamps; Oracle log format `[emergent] … (operation=…)`; types + Google docstrings; pytest plain assert, mock existing managers/LLM at the boundary; defensive (a failure never breaks the LivingWorld tick). `.venv\Scripts\python.exe`, Windows.

**Status:** A1 store DONE (slimmed, reuse-first). A2 faction model RETIRED (delegate to `TerritoryManager`). Remaining: A3, A4, A5, A6.

---

### Task A3: NPC goals
**Files:** Create `engine/world/emergent/goals.py`; Test `tests/test_emergent_goals.py`.
`@dataclass Goal{type:str, target:str, priority:float, progress:float}`; types `wealth, rank, revenge, romance, lay_low, territory`. `generate_goals(npc_id, *, ctx) -> list[Goal]` PURE (ctx carries the inputs so it's testable): a `relationships` dict (from `Database.get_or_create_relationship`), `faction` (from `faction_context._get_character_faction`), `recently_hacked`/`in_trouble` flags, and basic stats. Rules (weights from `get_config().get("emergent.goals.*")`): always a baseline `wealth`; a strongly-negative relationship → `revenge(that_id)`; a strongly-positive one → `romance(that_id)`; faction member → `rank` + `territory`; `recently_hacked`/in_trouble → `lay_low` boosted to top. `reprioritize(goals, outcome)` decays a satisfied goal + bumps a thwarted one; deterministic with a seed. `load/save` via `get_emergent_store().get_goals/set_goals` (serialize Goal↔dict).
- [ ] Test (pure, mock ctx): baseline wealth always present; -0.8 rel ⇒ revenge targeting it; +0.8 ⇒ romance; faction member ⇒ rank present; recently_hacked ⇒ lay_low highest; reprioritize is deterministic; store round-trip via explicit-path store.
- [ ] Run `… -m pytest tests/test_emergent_goals.py -q -o addopts=""` → FAIL → implement → PASS → Commit `feat(emergent): per-NPC goal generation + persistence (v1.63.0)`.

### Task A4: Hybrid utility planner (verbs → EXISTING systems)
**Files:** Create `engine/world/emergent/planner.py`; Test `tests/test_emergent_planner.py`.
READ the real signatures first: `engine/world/territory.py` (`shift_control`, `CONTROL_SHIFT_RANGE`), `engine/world/market.py` (buy/sell/contracts), `engine/world/crew.py` (`recruit`, `start_operation`, `compute_success_chance`), `engine/world/npc_comms.py` (the exchange helper), `content/scenes/phone/phone_hack.py` (`hack_phone`), `engine/world/relationship_effects.py` (`apply_exchange_effect`).
`plan_action(npc_id, *, goals, ctx, rng) -> PlannedAction{verb,target,params,use_llm}` — candidate actions per top goals, utility = priority×fit×feasibility (config weights), argmax. `execute(action) -> dict` dispatches each verb to the EXISTING manager: `wealth`→`get_market()` trade/contract; `territory`→`get_territory_manager().shift_control(...)` bounded by `CONTROL_SHIFT_RANGE`; `rank`→crew op via `get_crew_manager()`; `revenge`→`hack_phone`/betray; `romance`→`relationship_effects.apply_exchange_effect`; `lay_low`→no-op/low-profile message; `message`→`npc_comms`. `use_llm` only for pivotal actions, gated `emergent.planner.llm_chance`. Defensive: `execute` never raises.
- [ ] Test (mock the manager modules): `lay_low` NPC avoids hack/contest; `wealth` NPC trades via Market mock; `territory` NPC calls `shift_control` within bounds; `revenge` NPC with hostile target hacks/betrays; llm gating respects chance 0/1; `execute` routes each verb to the right (mocked) manager and survives a manager raising.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): hybrid planner dispatching to existing managers (v1.63.0)`.

### Task A5: Agency driver (hook the existing LivingWorld loop)
**Files:** Create `engine/world/emergent/agency.py`; Test `tests/test_emergent_agency.py`. Wire into `engine/world/living_world.py` (subscribe to its tick — use its EventBus `living_world_tick` publish, or an `add_listener`/post-tick hook; READ living_world.py to pick the cleanest existing seam — do NOT start a second daemon).
`EmergentAgency` (singleton `get_emergent_agency()`): on each LivingWorld tick, pick up to `emergent.active_npcs_per_tick` NPCs (enumerate via `Database.get_all_characters()` + `RoutineManager`/roster fallback), for each → load/generate goals (A3) → `plan_action` (A4) → `execute` → persist goals + `store.log_event(...)` → emit an agency event to the EXISTING feed (EventBus + optionally `comms_log.log(channel='world',...)`). `start()` subscribes to the loop; `stop()` unsubscribes; guard enabled + ≥1 NPC; respect caps so the model stays calm. NEVER raise into LivingWorld.
- [ ] Test (mock LivingWorld seam + managers + tiny caps + explicit-path store): a simulated tick advances ≥1 NPC goal→plan→execute→persist+event; respects active-npcs cap; `llm_chance=0` ⇒ no LLM; a manager raising doesn't break the tick; start/stop subscribe/unsubscribe cleanly.
- [ ] Run → FAIL → implement → PASS → Commit `feat(emergent): agency driver on the LivingWorld tick (v1.63.0)`.

### Task A6: Integration verification + tuning + changelog
- [ ] Full emergent suite: `… -m pytest tests/test_emergent_*.py -q -o addopts=""` → PASS.
- [ ] Smoke sweep (`… -m pytest tests/ --smoke-only -q -o addopts=""`) — the LivingWorld hook didn't break other domains.
- [ ] Live (LMStudio up): start the core/living world (find how LivingWorld is started — likely a scene lifecycle / `get_living_world().start()`); run ~2 min; show NPCs ACTED through existing managers — `get_market().get_stats()` shows trades, `get_territory_manager().get_event_history()` shows contests, relationships shifted, `get_emergent_store().recent_events()` shows the agency feed — and the model stayed calm (mostly rule actions, LLM≈`llm_chance`). Save to `docs/superpowers/artifacts/a6-agency.txt`. `oracle.py --errors` clean.
- [ ] Tune `emergent.*` (active-npcs/tick, llm_chance, utility weights, contest magnitude) for liveliness without runaway/model overload; document knobs.
- [ ] CHANGELOG `## [1.63.0]` start + README Features row (extend-marker pattern). Commit `docs(emergent): v1.63.0 changelog + agency tuning (v1.63.0)`.

## Self-review
- Spec coverage: goals→A3, planner+verbs-to-existing-managers→A4, driver-on-LivingWorld→A5, integration/tuning→A6; factions/territory/economy/loop = REUSED (not built). ✓
- No parallel sim: every verb dispatches to an existing manager; the driver hooks the existing loop. ✓
- Type consistency: `Goal`, `PlannedAction`, `get_emergent_store`, `get_emergent_agency`; reuse `get_territory_manager`/`get_market`/`get_crew_manager` real signatures (verified at A4 read step).
